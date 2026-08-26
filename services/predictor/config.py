import os
from dataclasses import dataclass


@dataclass
class Settings:
    prometheus_url: str = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")
    target_job: str = os.environ.get("TARGET_JOB", "demo-api")
    poll_interval_seconds: float = float(os.environ.get("POLL_INTERVAL_SECONDS", "15"))
    window_size: int = int(os.environ.get("WINDOW_SIZE", "20"))
    min_samples: int = int(os.environ.get("MIN_SAMPLES", "8"))
    threshold_sigma: float = float(os.environ.get("THRESHOLD_SIGMA", "3.0"))
    alert_cooldown_seconds: float = float(os.environ.get("ALERT_COOLDOWN_SECONDS", "120"))
    max_alerts: int = int(os.environ.get("MAX_ALERTS", "200"))


settings = Settings()
