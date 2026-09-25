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
    slack_bot_token: str = os.environ.get("SLACK_BOT_TOKEN", "")
    slack_signing_secret: str = os.environ.get("SLACK_SIGNING_SECRET", "")
    slack_channel: str = os.environ.get("SLACK_CHANNEL", "")
    scale_step: int = int(os.environ.get("SCALE_STEP", "1"))
    max_replicas: int = int(os.environ.get("MAX_REPLICAS", "5"))
    max_remediations: int = int(os.environ.get("MAX_REMEDIATIONS", "200"))


settings = Settings()
