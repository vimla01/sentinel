import sqlite3
import time

_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    metric TEXT NOT NULL,
    predicted_at REAL NOT NULL,
    predicted_value REAL,
    predicted_mean REAL,
    predicted_stddev REAL,
    predicted_z_score REAL,
    diagnosed_at REAL,
    grounded INTEGER,
    runbook_id TEXT,
    root_cause TEXT,
    recommended_action TEXT,
    remediation_id TEXT,
    remediation_category TEXT,
    remediation_auto INTEGER,
    remediation_status TEXT,
    remediation_result TEXT,
    remediated_at REAL,
    updated_at REAL NOT NULL
);
"""

# Numeric encoding for the Prometheus state-timeline gauge - order matters,
# it's the axis Grafana's value mappings render.
STAGE_LEVELS = {
    "predicted": 0,
    "diagnosed": 1,
    "awaiting_approval": 2,
    "denied": 3,
    "remediated": 4,
    "failed": 5,
}


def incident_id(metric: str, fired_at: float) -> str:
    """The correlation key threading one incident across predictor,
    diagnosis-agent, and remediator - all three already key their own
    internal dedup off this same (metric, fired_at) pair, so no new
    correlation id needs inventing."""
    return f"{metric}:{fired_at}"


def stage(row: dict) -> str:
    """Derived, not stored - avoids a second source of truth that could
    drift from the underlying columns."""
    status = row.get("remediation_status")
    if status == "executed":
        return "remediated"
    if status in ("failed", "denied"):
        return status
    if status == "awaiting_approval":
        return "awaiting_approval"
    if row.get("diagnosed_at") is not None:
        return "diagnosed"
    return "predicted"


class IncidentStore:
    """SQLite-backed store for the full incident lifecycle - the one piece
    of durable state in this platform, deliberately: every other service
    (predictor, diagnosis-agent, remediator) keeps ephemeral in-memory
    history by design, but the whole point of this gateway is a persisted,
    auditable record tying prediction -> diagnosis -> approval ->
    remediation together."""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def upsert_predicted(self, alert: dict) -> str:
        iid = incident_id(alert["metric"], alert["fired_at"])
        self._conn.execute(
            """
            INSERT INTO incidents
                (id, metric, predicted_at, predicted_value, predicted_mean,
                 predicted_stddev, predicted_z_score, updated_at)
            VALUES (:id, :metric, :fired_at, :value, :mean, :stddev, :z_score, :now)
            ON CONFLICT(id) DO UPDATE SET
                predicted_value = excluded.predicted_value,
                predicted_mean = excluded.predicted_mean,
                predicted_stddev = excluded.predicted_stddev,
                predicted_z_score = excluded.predicted_z_score,
                updated_at = excluded.updated_at
            """,
            {
                "id": iid,
                "metric": alert["metric"],
                "fired_at": alert["fired_at"],
                "value": alert.get("value"),
                "mean": alert.get("mean"),
                "stddev": alert.get("stddev"),
                "z_score": alert.get("z_score"),
                "now": time.time(),
            },
        )
        self._conn.commit()
        return iid

    def upsert_diagnosis(self, diagnosis: dict) -> str:
        alert = diagnosis["alert"]
        iid = self.upsert_predicted(alert)
        self._conn.execute(
            """
            UPDATE incidents SET
                diagnosed_at = :diagnosed_at,
                grounded = :grounded,
                runbook_id = :runbook_id,
                root_cause = :root_cause,
                recommended_action = :recommended_action,
                updated_at = :now
            WHERE id = :id
            """,
            {
                "id": iid,
                "diagnosed_at": diagnosis.get("created_at", time.time()),
                "grounded": int(bool(diagnosis.get("grounded"))),
                "runbook_id": diagnosis.get("runbook_id"),
                "root_cause": diagnosis.get("root_cause"),
                "recommended_action": diagnosis.get("recommended_action"),
                "now": time.time(),
            },
        )
        self._conn.commit()
        return iid

    def upsert_remediation(self, remediation: dict) -> str:
        alert = remediation["alert"]
        iid = self.upsert_predicted(alert)
        self._conn.execute(
            """
            UPDATE incidents SET
                remediation_id = :remediation_id,
                remediation_category = :category,
                remediation_auto = :auto,
                remediation_status = :status,
                remediation_result = :result,
                remediated_at = :remediated_at,
                updated_at = :now
            WHERE id = :id
            """,
            {
                "id": iid,
                "remediation_id": remediation.get("id"),
                "category": remediation.get("category"),
                "auto": int(bool(remediation.get("auto"))),
                "status": remediation.get("status"),
                "result": remediation.get("result"),
                "remediated_at": remediation.get("resolved_at"),
                "now": time.time(),
            },
        )
        self._conn.commit()
        return iid

    def get(self, incident_id_: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM incidents WHERE id = ?", (incident_id_,)
        ).fetchone()
        return _row_to_dict(row) if row else None

    def latest(self) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM incidents ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        return _row_to_dict(row) if row else None

    def history(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM incidents ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def close(self) -> None:
        self._conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["grounded"] = (
        bool(data["grounded"]) if data.get("grounded") is not None else None
    )
    data["remediation_auto"] = (
        bool(data["remediation_auto"])
        if data.get("remediation_auto") is not None
        else None
    )
    data["stage"] = stage(data)
    return data
