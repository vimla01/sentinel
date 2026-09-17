---
id: latency-connection-pool-exhaustion
title: Latency Degradation - Connection/Thread Pool Exhaustion
metrics: [latency_seconds]
tags: [latency, pool, concurrency]
signals:
  - latency_seconds rises sharply once concurrent request count crosses a threshold
  - requests appear to queue rather than fail outright
  - cpu_percent and memory_bytes are normal or only mildly elevated
safe_actions:
  - restart the affected pod
  - scale out replicas
approval_required: false
rollback: Restarting or scaling is safe and reversible; if latency returns once concurrency crosses the same threshold again, the pool size itself needs to be raised in config, which is a follow-up beyond this runbook's auto action.
---

## Detection Signals

Latency has a knee-shaped curve: normal up to a concurrency threshold, then
a sharp rise once requests start queuing for a limited resource (a database
connection pool, a thread pool, a semaphore-guarded client). CPU and memory
stay close to baseline because the process is waiting, not working.

## Likely Root Cause

The number of concurrent in-flight requests has exceeded the configured
size of some shared, limited resource pool, so additional requests queue for
a free slot instead of being served immediately.

## Diagnosis Evidence to Check

- Request concurrency/queue depth around the alert window, if exposed.
- Whether the pool size is a fixed config value that hasn't been revisited
  since traffic grew.
- Whether this correlates with a traffic surge - see
  `cpu-saturation-traffic-surge` for the sibling pattern on the compute side.

## Recommended Action

Restarting resets the pool's internal state and can clear a stuck
connection; scaling out replicas spreads concurrent load across more pool
instances. Both are safe, reversible, auto-approved actions. If exhaustion
recurs regularly, raising the configured pool size is the durable fix and
needs a config change beyond this runbook.

## Approval

None required for restart/scale - both are on the auto-remediation safe
list.

## Rollback

Scale back down once `latency_seconds` has stayed under threshold for a
sustained window.
