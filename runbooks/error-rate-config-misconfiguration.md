---
id: error-rate-config-misconfiguration
title: Error Rate Spike - Bad Configuration or Secret
metrics: [error_rate]
tags: [errors, config, secret]
signals:
  - error_rate breach correlated with a config/secret change rather than an image deploy
  - errors happen at process/request start (fail-fast) rather than mid-request
  - the error message names a missing or malformed setting
---

## Detection Signals

Errors begin immediately after a ConfigMap, Secret, or environment variable
change, not necessarily an image rollout - the deploy history may show no
new revision if only config was touched outside the tracked image tag. Logs
typically show a clear complaint about a missing, empty, or malformed
setting rather than a stack trace deep in business logic.

## Likely Root Cause

A configuration value or secret the service depends on is missing,
malformed, or pointing at the wrong target (e.g. a URL for the wrong
environment) after a recent change.

## Diagnosis Evidence to Check

- Recent logs for startup or first-request errors naming a specific
  environment variable or config key.
- What changed most recently in the relevant Kustomize overlay or Secret,
  if visible in Git history.
- Whether the error is present on every replica (config is fleet-wide) or
  only new pods (rolling update mid-flight with two versions of config
  live).

## Recommended Action

Identify the specific bad value from the error message and revert that
config change in Git so ArgoCD reconciles it back. This is not a blind
image rollback - the fix is targeted at the specific setting named in the
error, which needs a human to locate and confirm before reverting.

## Approval

Required. Reverting the wrong config value or the wrong commit could mask
the real problem; a human should confirm the diagnosis against the actual
error message before acting.

## Rollback

Reverting the offending config commit is itself the remediation - GitOps
means the fix is a `git revert`, not a manual `kubectl edit`.
