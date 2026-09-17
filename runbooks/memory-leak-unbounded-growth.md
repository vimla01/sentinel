---
id: memory-leak-unbounded-growth
title: Memory Leak - Unbounded, Monotonic Growth
metrics: [memory_bytes]
tags: [memory, leak, oom]
signals:
  - memory_bytes climbs steadily over many polling intervals, never dropping
  - growth rate is roughly constant regardless of request rate
  - matches the pattern produced by scripts/chaos/inject_memory_leak.py
safe_actions:
  - restart the affected pod
approval_required: false
rollback: Restarting clears the leaked memory immediately with no side effects; if growth resumes at the same rate post-restart, the leak is still present in code and needs a fix, not more restarts.
---

## Detection Signals

`memory_bytes` trends monotonically upward across the rolling window with
no plateaus and no correlation to request volume - it grows about as fast
under low traffic as under high traffic. This is the signature the
predictor is tuned to catch minutes before the pod is OOMKilled.

## Likely Root Cause

Something is being allocated and never released: a cache with no eviction,
a list or dict appended to on every request without bound, an unclosed
connection or file handle accumulating buffers, or a reference cycle the
collector can't reach. `scripts/chaos/inject_memory_leak.py` simulates
exactly this pattern for testing.

## Diagnosis Evidence to Check

- Growth rate: does memory increase by roughly the same amount per request,
  suggesting a per-request allocation that's never freed?
- Any recent deploy that introduced new caching, batching, or buffering
  logic.
- Whether the growth started immediately at process start (structural leak)
  or only after some trigger (leak on a specific code path).

## Recommended Action

Restart the pod before it hits its memory limit and gets OOMKilled
mid-request. This is safe and buys time without masking evidence - the leak
rate is still visible in the next window if it resumes. Flag for a code fix
regardless; a restart is mitigation, not resolution.

## Approval

None required - pod restarts are on the auto-remediation safe list.

## Rollback

N/A. A restart carries no state to roll back.
