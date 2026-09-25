import os
from dataclasses import dataclass


@dataclass
class Settings:
    predictor_url: str = os.environ.get("PREDICTOR_URL", "http://predictor:8080")
    diagnosis_agent_url: str = os.environ.get(
        "DIAGNOSIS_AGENT_URL", "http://diagnosis-agent:8080"
    )
    remediator_url: str = os.environ.get("REMEDIATOR_URL", "http://remediator:8080")
    poll_interval_seconds: float = float(os.environ.get("POLL_INTERVAL_SECONDS", "15"))
    db_path: str = os.environ.get("DB_PATH", "/data/incidents.db")
    max_history: int = int(os.environ.get("MAX_HISTORY", "50"))


settings = Settings()
