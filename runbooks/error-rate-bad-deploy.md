---
id: error-rate-bad-deploy
title: Error Rate Spike - Regression From a Recent Deploy
metrics: [error_rate]
tags: [errors, deploy, regression, rollback]
signals:
  - error_rate breach starts within minutes of a deploy in the ArgoCD history
  - errors are consistent (same status code/path) rather than random
  - matches the pattern produced by scripts/chaos/inject_error_rate.py
safe_actions:
  - rollback to the previous revision
approval_required: false
rollback: Rolling back returns to a revision that was previously serving traffic successfully - inherently reversible by re-deploying forward again once the regression is fixed.
---

## Detection Signals

`error_rate` crosses threshold and, critically, a deploy shows up in the
lookback window shortly before `fired_at`. Errors tend to be consistent -
the same endpoint or status code repeating - rather than the random
distribution you'd see from an external dependency flaking.

## Likely Root Cause

The most recently deployed revision introduced a regression: a bug in new
code, a missing config value the new code depends on, or an incompatible
schema/API change against a dependency that the previous revision didn't
have a problem with.

## Diagnosis Evidence to Check

- Deploy history: is there a revision deployed within the last
  `DEPLOY_LOOKBACK_SECONDS`? Confirm the timing lines up with `fired_at`,
  not just "a deploy happened recently."
- Recent logs for a stack trace or consistent error message tied to the new
  code path.
- Whether the error is 100% reproducible or only under certain inputs
  (affects confidence in "it's the deploy" versus a coincidence).

## Recommended Action

Roll back to the previous revision via ArgoCD. This is on the auto-approved
safe list specifically because it returns the system to a known-good state
that was already serving production traffic - it is the lowest-risk action
available for a deploy-correlated regression.

## Approval

None required - rollback is on the auto-remediation safe list.

## Rollback

Rolling back the bad revision is itself the remediation. Once the
underlying bug is fixed, re-deploy forward through the normal GitOps flow.
