---
id: cpu-saturation-busy-loop
title: CPU Saturation - Busy-Loop / Runaway Compute
metrics: [cpu_percent]
tags: [cpu, compute, hot-loop, thread]
signals:
  - cpu_percent z-score breach with no corresponding rise in request rate
  - a single pod pegged near 100% CPU while sibling replicas stay idle
  - no recent deploy correlated with the spike
safe_actions:
  - restart the affected pod
approval_required: false
rollback: Restarting is non-destructive. If CPU returns to the same level within a minute of the restart, stop retrying and escalate - it is not a transient hang.
---

## Detection Signals

The predictor's `cpu_percent` metric breaches its rolling z-score threshold
while `error_rate` and `latency_seconds` stay flat, and request throughput
(from demo-api's own request counters) is unchanged from baseline. This
pattern - CPU up, everything else normal - points at compute stuck in a
tight loop rather than at load.

## Likely Root Cause

A code path entered an unbounded or pathological loop (bad retry logic,
an infinite `while` without a terminating condition, a regex catastrophic
backtrack, or a stuck thread from `scripts/chaos/inject_cpu_spike.py`-style
busy-wait). The process is spending cycles without doing useful work.

## Diagnosis Evidence to Check

- Recent logs for the affected pod around the alert's `fired_at` timestamp -
  look for a request that started but never logged completion.
- Deploy history: was there a deploy in the last hour? If not, this is a
  runtime condition (e.g. malformed input triggering the loop), not a bad
  release.
- Whether the spike is isolated to one pod (runaway thread) or spread across
  all replicas (systemic bug hit by every instance).

## Recommended Action

Restart the affected pod. This is safe and reversible - it clears the
runaway thread immediately and Kubernetes will reschedule it with a clean
process. If the condition is systemic (all replicas affected, or CPU returns
immediately post-restart), do not keep restarting; escalate with the
triggering request payload so the loop can be reproduced and fixed in code.

## Approval

None required - pod restarts are on the auto-remediation safe list.

## Rollback

N/A. A restart carries no state to roll back.
