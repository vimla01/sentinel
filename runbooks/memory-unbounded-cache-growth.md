---
id: memory-unbounded-cache-growth
title: Memory Growth - In-Process Cache Without Eviction
metrics: [memory_bytes]
tags: [memory, cache, eviction]
signals:
  - memory_bytes grows in a staircase pattern that tracks unique request keys
  - growth slows as traffic diversity saturates (cache fills, then plateaus)
  - correlates with a deploy that added or changed an in-process cache
safe_actions:
  - restart the affected pod
approval_required: false
rollback: Restarting clears the cache and frees memory immediately with no data-loss risk, since it is a rebuildable in-process cache, not a system of record.
---

## Detection Signals

`memory_bytes` grows in steps that correlate with distinct request keys
(new cache entries) rather than growing per-request regardless of content.
Growth often slows and plateaus once the working set of unique keys has been
seen once - which distinguishes it from `memory-leak-unbounded-growth`,
where growth stays constant indefinitely.

## Likely Root Cause

An in-process cache (memoization, a manually maintained dict, a
`functools.lru_cache` without `maxsize`) is caching results keyed by
something with high or unbounded cardinality, so it never evicts and keeps
growing with the input space.

## Diagnosis Evidence to Check

- Whether a recent deploy added or modified caching logic.
- Whether the plateau level roughly matches an expected key cardinality
  (e.g. number of distinct users or resource IDs seen).
- Whether the cache is safe to lose on restart (in-process, rebuildable) or
  is fronting an expensive backing store that would see a thundering herd
  on restart - see `latency-cold-cache-thundering-herd` if so.

## Recommended Action

Restart the pod to reclaim the cache's memory immediately. This is safe
because the cache is rebuildable in-process state, not a system of record.
The durable fix - adding a `maxsize`/TTL/eviction policy to the cache - is a
code change and should be filed regardless of whether the restart clears
the immediate alert.

## Approval

None required - pod restarts are on the auto-remediation safe list.

## Rollback

N/A. A restart carries no state to roll back.
