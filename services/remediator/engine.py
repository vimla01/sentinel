import logging
import time
import uuid
from dataclasses import dataclass, field

import httpx

from .argocd_client import ArgocdClient
from .k8s_client import K8sClient
from .policy import classify, should_auto_execute
from .slack_client import SlackClient

logger = logging.getLogger("remediator.engine")


@dataclass
class Remediation:
    id: str
    alert: dict
    runbook_id: str | None
    action_text: str
    category: str
    auto: bool
    status: str
    result: str = ""
    slack_channel: str = ""
    slack_ts: str = ""
    created_at: float = field(default_factory=time.time)
    resolved_at: float | None = None


class RemediationEngine:
    """Turns a grounded diagnosis into either an immediate, hardcoded-safe
    K8s/ArgoCD action, or a Slack approval request that blocks until a human
    clicks Approve/Deny. Nothing outside restart/scale/rollback ever
    executes without a human decision - see policy.should_auto_execute."""

    def __init__(
        self,
        k8s: K8sClient,
        argocd: ArgocdClient,
        slack: SlackClient,
        target_deployment: str,
        argocd_app: str,
        slack_channel: str,
        scale_step: int,
        max_replicas: int,
        max_remediations: int = 200,
    ) -> None:
        self._k8s = k8s
        self._argocd = argocd
        self._slack = slack
        self._target_deployment = target_deployment
        self._argocd_app = argocd_app
        self._slack_channel = slack_channel
        self._scale_step = scale_step
        self._max_replicas = max_replicas
        self._max_remediations = max_remediations
        self._remediations: dict[str, Remediation] = {}

    @property
    def remediations(self) -> list[Remediation]:
        return list(self._remediations.values())

    async def process_diagnosis(self, diagnosis: dict) -> Remediation | None:
        if not diagnosis.get("grounded"):
            return None
        action_text = diagnosis.get("recommended_action") or ""
        if not action_text:
            return None

        remediation = Remediation(
            id=str(uuid.uuid4()),
            alert=diagnosis.get("alert", {}),
            runbook_id=diagnosis.get("runbook_id"),
            action_text=action_text,
            category=classify(action_text),
            auto=should_auto_execute(diagnosis),
            status="pending",
        )
        self._record(remediation)

        if remediation.auto:
            await self._execute(remediation)
        else:
            await self._request_approval(remediation)
        return remediation

    async def resolve(
        self, remediation_id: str, approved: bool, actor: str
    ) -> Remediation:
        remediation = self._remediations[remediation_id]
        if remediation.status != "awaiting_approval":
            return remediation

        if approved:
            await self._execute(remediation)
            outcome = (
                f"Approved by {actor} — {remediation.status}: {remediation.result}"
            )
        else:
            remediation.status = "denied"
            remediation.result = f"denied by {actor}"
            remediation.resolved_at = time.time()
            outcome = f"Denied by {actor}"
            logger.info("REMEDIATION denied id=%s actor=%s", remediation.id, actor)

        if remediation.slack_channel and remediation.slack_ts:
            try:
                await self._slack.update_message(
                    remediation.slack_channel, remediation.slack_ts, outcome
                )
            except (httpx.HTTPError, RuntimeError):
                logger.exception("failed to update slack message id=%s", remediation.id)
        return remediation

    async def _execute(self, remediation: Remediation) -> None:
        try:
            if remediation.category == "restart":
                await self._k8s.restart_deployment(self._target_deployment)

                remediation.result = f"restarted deployment/{self._target_deployment}"
            elif remediation.category == "scale":
                await self._k8s.scale_deployment(
                    self._target_deployment, self._scale_step, self._max_replicas
                )
                remediation.result = f"scaled deployment/{self._target_deployment}"
            elif remediation.category == "rollback":
                await self._argocd.rollback(self._argocd_app)
                remediation.result = f"rolled back application/{self._argocd_app}"
            else:
                raise ValueError(f"unsupported action category: {remediation.category}")
            remediation.status = "executed"
        except (httpx.HTTPError, ValueError) as exc:
            remediation.status = "failed"
            remediation.result = str(exc)
            logger.exception("remediation execution failed id=%s", remediation.id)
        finally:
            remediation.resolved_at = time.time()
            logger.info(
                "REMEDIATION id=%s category=%s auto=%s status=%s result=%s alert=%s",
                remediation.id,
                remediation.category,
                remediation.auto,
                remediation.status,
                remediation.result,
                remediation.alert,
            )

    async def _request_approval(self, remediation: Remediation) -> None:
        remediation.status = "awaiting_approval"
        text = (
            "*Remediation needs approval*\n"
            f"metric: `{remediation.alert.get('metric')}`  runbook: `{remediation.runbook_id}`\n"
            f"recommended action: {remediation.action_text}"
        )
        try:
            response = await self._slack.post_approval(
                self._slack_channel, remediation.id, text
            )
            remediation.slack_channel = response.get("channel", self._slack_channel)
            remediation.slack_ts = response.get("ts", "")
        except (httpx.HTTPError, RuntimeError):
            logger.exception(
                "failed to post slack approval request id=%s", remediation.id
            )
        logger.info(
            "REMEDIATION id=%s category=%s auto=False status=awaiting_approval alert=%s",
            remediation.id,
            remediation.category,
            remediation.alert,
        )

    def _record(self, remediation: Remediation) -> None:
        self._remediations[remediation.id] = remediation
        while len(self._remediations) > self._max_remediations:
            oldest_id = next(iter(self._remediations))
            del self._remediations[oldest_id]
