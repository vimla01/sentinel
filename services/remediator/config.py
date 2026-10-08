import os
from dataclasses import dataclass


@dataclass
class Settings:
    diagnosis_agent_url: str = os.environ.get(
        "DIAGNOSIS_AGENT_URL", "http://diagnosis-agent:8080"
    )
    poll_interval_seconds: float = float(os.environ.get("POLL_INTERVAL_SECONDS", "15"))
    k8s_namespace: str = os.environ.get("K8S_NAMESPACE", "sentinel")
    target_deployment: str = os.environ.get("TARGET_DEPLOYMENT", "demo-api")
    argocd_url: str = os.environ.get("ARGOCD_URL", "http://argocd-server.argocd:80")
    argocd_app: str = os.environ.get("ARGOCD_APP", "sentinel")
    git_repo_path: str = os.environ.get("GIT_REPO_PATH", "")
    slack_bot_token: str = os.environ.get("SLACK_BOT_TOKEN", "")
    slack_signing_secret: str = os.environ.get("SLACK_SIGNING_SECRET", "")
    slack_channel: str = os.environ.get("SLACK_CHANNEL", "")
    scale_step: int = int(os.environ.get("SCALE_STEP", "1"))
    max_replicas: int = int(os.environ.get("MAX_REPLICAS", "5"))
    max_remediations: int = int(os.environ.get("MAX_REMEDIATIONS", "200"))
    verification_delay_seconds: float = float(
        os.environ.get(
            "VERIFICATION_DELAY",
            os.environ.get("VERIFICATION_DELAY_SECONDS", "5.0"),
        )
    )
    verification_interval_seconds: float = float(
        os.environ.get(
            "VERIFICATION_INTERVAL",
            os.environ.get("VERIFICATION_INTERVAL_SECONDS", "3.0"),
        )
    )
    verification_max_attempts: int = int(
        os.environ.get("VERIFICATION_MAX_ATTEMPTS", "3")
    )
    prometheus_url: str = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")
    target_workload_url: str = os.environ.get(
        "TARGET_WORKLOAD_URL", "http://demo-api:8080"
    )
    verification_enabled: bool = os.environ.get(
        "VERIFICATION_ENABLED", "true"
    ).lower() in ("true", "1")
    wait_for_verification: bool = os.environ.get(
        "WAIT_FOR_VERIFICATION", "true"
    ).lower() in ("true", "1")


settings = Settings()
