# Runbooks

One Markdown file per known incident type, loaded by
`services/diagnosis_agent` at startup. The diagnosis agent only ever cites a
runbook whose `metrics` list covers the alerting metric - if nothing
matches, it withholds diagnosis instead of guessing, so every runbook added
here directly expands what the agent can safely diagnose.

## File format

Each file is YAML frontmatter followed by a Markdown body:

```markdown
---
id: memory-leak-unbounded-growth       # unique, matches the filename stem
title: Memory Leak - Unbounded, Monotonic Growth
metrics: [memory_bytes]                # predictor metric(s) this runbook covers:
                                        # cpu_percent, memory_bytes, latency_seconds, error_rate
tags: [memory, leak, oom]              # extra keywords used to rank between
                                        # multiple runbooks matching the same metric
signals:
  - short bullet detection signals used for the same ranking
safe_actions:
  - actions safe to auto-remediate (restart/scale/rollback) - omit if none
approval_required: false               # defaults to true when omitted, i.e.
                                        # "no safe auto action, a human must decide"
rollback: how to undo the safe action, if one is listed
---

## Detection Signals
## Likely Root Cause
## Diagnosis Evidence to Check
## Recommended Action
## Approval
## Rollback
```

The body sections above are convention, not enforced structure - they're
what gets embedded in the LLM prompt as the grounding context, so keep them
concrete and specific to this platform rather than generic SRE advice.

## Current runbooks

| Metric | Runbooks |
|---|---|
| `cpu_percent` | `cpu-saturation-busy-loop`, `cpu-saturation-traffic-surge`, `cpu-saturation-gc-thrashing` |
| `memory_bytes` | `memory-leak-unbounded-growth`, `memory-large-payload-spike`, `memory-unbounded-cache-growth`, `cpu-saturation-gc-thrashing` |
| `latency_seconds` | `latency-downstream-dependency-slow`, `latency-connection-pool-exhaustion`, `latency-cold-cache-thundering-herd` |
| `error_rate` | `error-rate-bad-deploy`, `error-rate-dependency-outage`, `error-rate-config-misconfiguration` |

Several metrics have more than one runbook on purpose: a z-score breach
alone can't tell a busy-loop bug from a legitimate traffic surge, or a leak
from a cold-cache thundering herd. The diagnosis agent disambiguates using
recent logs and deploy history (see
[docs/API.md](../docs/API.md#diagnosis-agent)); when the disambiguating
evidence is thin, it still returns its best match rather than nothing, since
every candidate already covers the right metric.
