---
id: memory-large-payload-spike
title: Memory Spike - Oversized Single Request or Response
metrics: [memory_bytes]
tags: [memory, payload, validation]
signals:
  - memory_bytes jumps in a single sharp step rather than a gradual ramp
  - the jump aligns with one specific request in the access logs
  - memory does not continue climbing afterward, it plateaus at the new level
---

## Detection Signals

Unlike a leak, this is a single step-function jump in `memory_bytes` that
then holds steady (or partially recovers once the response is sent and
garbage-collected). One request, one jump.

## Likely Root Cause

A single request or response carried an unexpectedly large payload -
someone uploaded a huge file, an unbounded query returned an enormous result
set, or a request handler buffered an entire response body in memory
instead of streaming it. Unlike `memory-leak-unbounded-growth`, this is not
compounding over time.

## Diagnosis Evidence to Check

- The access log entry at the timestamp of the jump - look for an unusually
  large `Content-Length` on request or response.
- Whether the endpoint involved has any request-size validation or pagination
  limits.
- Whether this has happened before on the same endpoint (recurring risk) or
  is a one-off.

## Recommended Action

No safe auto-remediation applies here - restarting doesn't prevent the next
oversized request from causing the same spike again. The durable fix is
adding a request-size limit or pagination to the offending endpoint, which
is a code change requiring review.

## Approval

Required. This needs a human to add validation/limits on the specific
endpoint; there is no generic safe action that closes the gap.

## Rollback

N/A - no remediation is auto-applied for this runbook.
