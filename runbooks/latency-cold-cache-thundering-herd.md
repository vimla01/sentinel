---
id: latency-cold-cache-thundering-herd
title: Latency Degradation - Cold Cache / Thundering Herd After Restart
metrics: [latency_seconds]
tags: [latency, cache, thundering-herd, restart]
signals:
  - latency_seconds spikes immediately following a pod restart or deploy
  - the spike decays on its own over a few minutes without intervention
  - error_rate may tick up briefly if the backing store is overwhelmed
---

## Detection Signals

The latency breach starts right after a deploy or restart event in the
deploy history, and - left alone - trends back down over a few minutes
rather than staying flat or worsening. This self-healing shape is the key
signal distinguishing it from every other latency runbook here.

## Likely Root Cause

A cache (in-process or shared) was cleared by the restart, and the fleet is
now serving a wave of cache misses that all fall through to the backing
store at once, slowing every request until the cache warms back up.

## Diagnosis Evidence to Check

- Deploy history: did a deploy or restart happen shortly before the alert
  fired?
- Whether latency is trending down already by the time this diagnosis runs
  - if so, the situation may already be resolving on its own.
- Load on the backing store (database, upstream cache) during the window,
  if visible - a spike there confirms the thundering-herd read.

## Recommended Action

Do not restart or scale in response to this alert - either would clear more
cache state or add more cold instances, making the herd worse, not better.
The safe response is to monitor: if latency hasn't recovered within a few
minutes on its own, escalate rather than take a compute action that fights
the actual cause.

## Approval

Required. No auto action applies - the intervention that "sounds safe"
(restart/scale) is actively counterproductive here, so a human must confirm
before doing anything.

## Rollback

N/A - no remediation is auto-applied for this runbook.
