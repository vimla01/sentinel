---
id: cpu-saturation-gc-thrashing
title: CPU Saturation - Garbage-Collection Thrashing Under Memory Pressure
metrics: [cpu_percent, memory_bytes]
tags: [cpu, memory, gc, thrashing]
signals:
  - cpu_percent and memory_bytes breach together, rising in lockstep
  - latency_seconds degrades gradually rather than spiking sharply
  - no traffic surge and no recent deploy
safe_actions:
  - restart the affected pod
approval_required: true
rollback: Restarting only buys time; if memory_bytes climbs back to the same level, the leak causing GC pressure is still there and needs a code fix.
---

## Detection Signals

`cpu_percent` and `memory_bytes` breach at nearly the same time and both
keep climbing together, distinguishing this from a pure busy-loop (CPU only)
or a pure leak (memory only, CPU flat). Latency degrades smoothly rather
than in a step, consistent with the runtime spending more and more time in
garbage collection instead of request handling.

## Likely Root Cause

Memory pressure - often from the early stage of a leak (see
`memory-leak-unbounded-growth`) or from retaining large objects longer than
necessary - is forcing the garbage collector to run more frequently and do
more work per cycle, which shows up as CPU. This is a downstream symptom of
a memory problem, not an independent CPU issue.

## Diagnosis Evidence to Check

- Whether `memory_bytes` alone crossed its own threshold shortly before this
  alert - if so, treat this as the same incident, not two.
- Any recent change to caching, buffering, or batch size that would increase
  per-request memory retention.
- Process uptime: thrashing usually gets worse the longer the process has
  been running without a restart.

## Recommended Action

Restart the pod to reclaim heap and give the collector a fresh baseline -
this buys time. It does not fix the underlying condition, so this is not a
one-and-done: flag the memory trend for follow-up regardless of whether the
restart resolves the immediate alert.

## Approval

Required. Restarting here treats a symptom, not the cause - a human should
confirm this is the same incident as any recent `memory_bytes` alert before
acting, rather than auto-looping restarts on a real leak.

## Rollback

N/A for the restart itself. If a recent deploy is implicated, the rollback
path is the same as `error-rate-bad-deploy`.
