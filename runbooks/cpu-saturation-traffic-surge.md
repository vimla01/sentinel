---
id: cpu-saturation-traffic-surge
title: CPU Saturation - Legitimate Traffic Surge
metrics: [cpu_percent]
tags: [cpu, compute, scaling, traffic]
signals:
  - cpu_percent z-score breach across every replica simultaneously
  - request rate rose proportionally with CPU, ahead of the breach
  - error_rate and latency_seconds trending up together with cpu_percent
safe_actions:
  - scale out replicas
approval_required: false
rollback: Scale back down once cpu_percent returns under threshold for a sustained period; over-provisioning briefly is cheap and safe.
---

## Detection Signals

Unlike a single runaway pod, every replica's CPU rises together, and it
tracks a genuine increase in inbound request rate rather than starting from
nothing. `latency_seconds` and `error_rate` often start climbing shortly
after, since the fleet is running closer to saturation.

## Likely Root Cause

More real traffic is arriving than the current replica count was sized for
- a marketing push, a batch job fan-out from a caller, or simple organic
growth. This is not a bug; it is capacity catching up to demand.

## Diagnosis Evidence to Check

- Request-rate trend over the alert lookback window: is it climbing evenly
  across all pods, or spiking on one?
- Whether the surge correlates with a known external event (cron trigger,
  upstream batch job, traffic replay from a chaos test).
- Current replica count versus configured HPA/min-replica floor, if one
  exists.

## Recommended Action

Scale out the deployment to add headroom. This is a safe, reversible,
auto-approved action - adding replicas cannot make correctness worse, only
cost. Pair it with a note on whether autoscaling should be enabled going
forward so this doesn't require a human to catch it each time.

## Approval

None required - scaling is on the auto-remediation safe list.

## Rollback

Scale back down once `cpu_percent` has stayed under `THRESHOLD_SIGMA` for a
sustained window. Do not scale down immediately after scaling up - confirm
the surge has actually passed first.
