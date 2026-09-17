import logging
import time
from collections import deque
from dataclasses import dataclass, field

import httpx

from .deploy_history import DeployHistoryClient
from .loki_client import LokiClient
from .ollama_client import OllamaClient
from .prompt import build_prompt, parse_response
from .retriever import match_runbook
from .runbooks import Runbook

logger = logging.getLogger("diagnosis_agent.engine")

_UNGROUNDED_MESSAGE = (
    "No runbook covers metric '{metric}'. Diagnosis withheld rather than "
    "speculating - add a runbook covering this metric to enable diagnosis "
    "for it."
)


@dataclass
class Diagnosis:
    alert: dict
    grounded: bool
    runbook_id: str | None
    root_cause: str
    recommended_action: str
    raw_response: str
    logs: list[str]
    deploys: list[dict]
    created_at: float = field(default_factory=time.time)


class DiagnosisEngine:
    """Turns a predictor Alert into a grounded diagnosis: pulls recent logs
    and deploy history, retrieves the runbook that matches the alerting
    metric, and prompts the LLM to explain root cause + action citing that
    runbook. If no runbook matches, the LLM is never called - there is
    nothing to ground it in, so no diagnosis is produced rather than an
    invented one."""

    def __init__(
        self,
        runbooks: list[Runbook],
        loki: LokiClient,
        deploys: DeployHistoryClient,
        ollama: OllamaClient,
        target_job: str,
        argocd_app: str,
        log_lookback_seconds: float,
        deploy_lookback_seconds: float,
        log_line_limit: int,
        max_diagnoses: int = 200,
    ) -> None:
        self._runbooks = runbooks
        self._loki = loki
        self._deploys = deploys
        self._ollama = ollama
        self._target_job = target_job
        self._argocd_app = argocd_app
        self._log_lookback_seconds = log_lookback_seconds
        self._deploy_lookback_seconds = deploy_lookback_seconds
        self._log_line_limit = log_line_limit
        self._diagnoses: deque[Diagnosis] = deque(maxlen=max_diagnoses)

    @property
    def diagnoses(self) -> list[Diagnosis]:
        return list(self._diagnoses)

    async def diagnose(self, alert: dict) -> Diagnosis:
        metric = alert.get("metric", "")
        logs = await self._safe_logs()
        deploys = await self._safe_deploys()
        context = " ".join(logs) + " " + " ".join(d.get("revision") or "" for d in deploys)

        runbook = match_runbook(metric, context, self._runbooks)
        if runbook is None:
            diagnosis = Diagnosis(
                alert=alert,
                grounded=False,
                runbook_id=None,
                root_cause=_UNGROUNDED_MESSAGE.format(metric=metric),
                recommended_action="",
                raw_response="",
                logs=logs,
                deploys=deploys,
            )
            self._record(diagnosis)
            return diagnosis

        prompt = build_prompt(alert, runbook, logs, deploys)
        raw_response = await self._ollama.generate(prompt)
        root_cause, recommended_action, cited = parse_response(raw_response)

        diagnosis = Diagnosis(
            alert=alert,
            grounded=True,
            runbook_id=cited or runbook.id,
            root_cause=root_cause or raw_response.strip(),
            recommended_action=recommended_action or "",
            raw_response=raw_response,
            logs=logs,
            deploys=deploys,
        )
        self._record(diagnosis)
        return diagnosis

    async def _safe_logs(self) -> list[str]:
        now = time.time()
        start_ns = int((now - self._log_lookback_seconds) * 1e9)
        end_ns = int(now * 1e9)
        try:
            return await self._loki.recent_logs(self._target_job, start_ns, end_ns, self._log_line_limit)
        except httpx.HTTPError as exc:
            logger.warning("loki query failed error=%s", exc)
            return []

    async def _safe_deploys(self) -> list[dict]:
        since = time.time() - self._deploy_lookback_seconds
        try:
            return await self._deploys.recent_deploys(self._argocd_app, since)
        except httpx.HTTPError as exc:
            logger.warning("argocd query failed error=%s", exc)
            return []

    def _record(self, diagnosis: Diagnosis) -> None:
        self._diagnoses.append(diagnosis)
        logger.info(
            "DIAGNOSIS metric=%s grounded=%s runbook=%s root_cause=%r "
            "logs=%d deploys=%d alert=%s",
            diagnosis.alert.get("metric"),
            diagnosis.grounded,
            diagnosis.runbook_id,
            diagnosis.root_cause,
            len(diagnosis.logs),
            len(diagnosis.deploys),
            diagnosis.alert,
        )
