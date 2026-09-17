---
id: latency-downstream-dependency-slow
title: Latency Degradation - Slow Downstream Dependency
metrics: [latency_seconds]
tags: [latency, dependency, upstream]
signals:
  - latency_seconds breaches while cpu_percent and memory_bytes stay flat
  - the added delay is roughly constant across requests, not proportional to load
  - matches the pattern produced by scripts/chaos/inject_latency.py
---

## Detection Signals

`latency_seconds` climbs while compute and memory metrics stay within
baseline - the pod itself isn't struggling, it's waiting. The added delay
tends to be roughly uniform per request rather than scaling with concurrent
load, consistent with a fixed round-trip cost to something external.

## Likely Root Cause

A downstream call - a database query, a third-party API, another internal
service - has gotten slower, and the caller is blocked waiting on it for
every request that touches that path.

## Diagnosis Evidence to Check

- Recent logs for timeout warnings or slow-query log lines naming the
  downstream target.
- Whether the slowdown affects every request (dependency used on the hot
  path for all traffic) or only a subset (used on one feature/endpoint).
- Status of the dependency itself, if it has its own health endpoint or
  dashboard.

## Recommended Action

No safe auto-remediation applies here - the affected service isn't the one
that's broken, so restarting or scaling it does nothing for the actual
bottleneck. Escalate to the owner of the downstream dependency, and consider
whether a timeout/circuit-breaker should be added on this call so one slow
dependency can't degrade the whole request path.

## Approval

Required. There is no safe local action; any fix (adding a timeout, failing
over, escalating externally) needs a human decision.

## Rollback

N/A - no remediation is auto-applied for this runbook.
