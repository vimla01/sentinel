import logging
from typing import Awaitable, Callable

import httpx
from prometheus_client import Gauge

from .db import STAGE_LEVELS, IncidentStore
from .diagnosis_client import DiagnosisAgentClient
from .predictor_client import PredictorClient
from .remediator_client import RemediatorClient

logger = logging.getLogger("api.sync")

incident_stage_level = Gauge(
    "sentinel_incident_stage_level",
    "Current lifecycle stage of a tracked incident: "
    "0=predicted 1=diagnosed 2=awaiting_approval 3=denied 4=remediated 5=failed",
    ["incident_id", "metric"],
)
incidents_by_stage = Gauge(
    "sentinel_incidents_by_stage",
    "Count of tracked incidents currently in each lifecycle stage",
    ["stage"],
)


class IncidentSync:
    """Correlates predictor/diagnosis-agent/remediator's independent,
    ephemeral histories into one persisted incident per alert, keyed by
    (metric, fired_at) - the same pair all three already use internally for
    their own dedup. Re-upserts everything on every cycle rather than
    tracking a "seen" set like the upstream services do, because a
    remediation's status mutates in place after a Slack decision and this
    is the one place that needs to notice the transition, not just the
    first sighting."""

    def __init__(
        self,
        predictor: PredictorClient,
        diagnosis: DiagnosisAgentClient,
        remediator: RemediatorClient,
        store: IncidentStore,
        max_history: int = 50,
    ) -> None:
        self._predictor = predictor
        self._diagnosis = diagnosis
        self._remediator = remediator
        self._store = store
        self._max_history = max_history
        self._tracked_gauge_ids: dict[str, str] = {}

    async def sync_once(self) -> int:
        updated = 0
        updated += await self._ingest(self._predictor.get_alerts, "predictor", self._store.upsert_predicted)
        updated += await self._ingest(
            self._diagnosis.get_diagnoses, "diagnosis-agent", self._store.upsert_diagnosis
        )
        updated += await self._ingest(
            self._remediator.get_remediations, "remediator", self._store.upsert_remediation
        )
        self._refresh_gauges()
        return updated

    async def _ingest(
        self,
        fetch: Callable[[], Awaitable[list[dict]]],
        name: str,
        upsert: Callable[[dict], str],
    ) -> int:
        try:
            items = await fetch()
        except httpx.HTTPError as exc:
            logger.warning("%s poll failed error=%s", name, exc)
            return 0

        count = 0
        for item in items:
            try:
                upsert(item)
                count += 1
            except (KeyError, TypeError):
                logger.exception("failed to upsert %s item=%s", name, item)
        return count

    def _refresh_gauges(self) -> None:
        rows = self._store.history(limit=self._max_history)
        current_ids = {row["id"]: row["metric"] for row in rows}

        for stale_id, stale_metric in self._tracked_gauge_ids.items():
            if stale_id not in current_ids:
                incident_stage_level.remove(stale_id, stale_metric)

        counts = {name: 0 for name in STAGE_LEVELS}
        for row in rows:
            incident_stage_level.labels(incident_id=row["id"], metric=row["metric"]).set(
                STAGE_LEVELS[row["stage"]]
            )
            counts[row["stage"]] += 1

        for stage_name, count in counts.items():
            incidents_by_stage.labels(stage=stage_name).set(count)

        self._tracked_gauge_ids = current_ids
