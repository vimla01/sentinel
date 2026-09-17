---
id: error-rate-dependency-outage
title: Error Rate Spike - Upstream or Downstream Dependency Outage
metrics: [error_rate]
tags: [errors, dependency, outage]
signals:
  - error_rate breach with no corresponding deploy in the lookback window
  - errors cluster around calls to one specific external dependency
  - the same errors appear across every replica simultaneously
---

## Detection Signals

Every replica starts erroring at roughly the same time with no deploy to
explain it, and the errors trace back to calls made against one external
system rather than being spread evenly across the codebase.

## Likely Root Cause

A dependency the service relies on - a database, a third-party API, another
internal service - is down, rate-limiting, or returning errors of its own,
and those failures are propagating into this service's `error_rate`.

## Diagnosis Evidence to Check

- Recent logs for connection refused, timeout, or non-2xx responses naming
  the specific dependency.
- The dependency's own status page or health endpoint, if available.
- Whether errors are total (dependency fully down) or partial (rate limiting
  or degraded capacity).

## Recommended Action

No safe auto-remediation applies - this service isn't the broken component,
so restarting, scaling, or rolling it back won't help and may waste time
that should go to the actual outage. Escalate to the dependency owner or
their status page, and consider whether a circuit breaker or fallback should
be added so this dependency can't take the whole service down next time.

## Approval

Required. There is no local safe action; escalation and any code-level
resilience change need a human.

## Rollback

N/A - no remediation is auto-applied for this runbook.
