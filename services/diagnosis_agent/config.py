import os
from dataclasses import dataclass


@dataclass
class Settings:
    predictor_url: str = os.environ.get("PREDICTOR_URL", "http://predictor:8080")
    ollama_url: str = os.environ.get("OLLAMA_URL", "http://ollama:11434")
    ollama_model: str = "tinyllama"
    loki_url: str = os.environ.get("LOKI_URL", "http://loki:3100")
    argocd_url: str = os.environ.get("ARGOCD_URL", "https://argocd-server.argocd:443")
    argocd_app: str = os.environ.get("ARGOCD_APP", "sentinel")
    target_job: str = os.environ.get("TARGET_JOB", "demo-api")
    runbooks_dir: str = os.environ.get("RUNBOOKS_DIR", "runbooks")
    poll_interval_seconds: float = float(os.environ.get("POLL_INTERVAL_SECONDS", "15"))
    log_lookback_seconds: float = float(os.environ.get("LOG_LOOKBACK_SECONDS", "300"))
    deploy_lookback_seconds: float = float(
        os.environ.get("DEPLOY_LOOKBACK_SECONDS", "3600")
    )
    log_line_limit: int = int(os.environ.get("LOG_LINE_LIMIT", "50"))
    max_diagnoses: int = int(os.environ.get("MAX_DIAGNOSES", "200"))


settings = Settings()
