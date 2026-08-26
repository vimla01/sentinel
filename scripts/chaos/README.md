# Chaos scripts

Failure injection scripts for demo-api. Keep experiments opt-in and reversible.

Each script targets demo-api's `/debug/*` endpoints. By default they build the
URL from an in-cluster service name (`--service demo-api`, i.e.
`http://demo-api:8080`); pass `--base-url http://localhost:8080` instead when
using `kubectl -n sentinel port-forward svc/demo-api 8080:8080` for local runs.

- `inject_memory_leak.py` - grow memory usage in steps to simulate a slow leak.
- `inject_cpu_spike.py` - spin busy-loop threads for a fixed duration.
- `inject_latency.py` - add artificial latency to every response.
- `inject_error_rate.py` - randomly return 500s for a fraction of requests.
- `reset.py` - clear all chaos state on demo-api.
- `watch.py` - poll the predictor's `/risk` endpoint and print the live risk
  score/z-scores while a scenario above runs in another terminal.

Example, watching the predictor catch a memory leak before demo-api is
OOMKilled:

```bash
kubectl -n sentinel port-forward svc/demo-api 8080:8080 &
kubectl -n sentinel port-forward svc/predictor 8000:8080 &

python scripts/chaos/watch.py --predictor-url http://localhost:8000 &
python scripts/chaos/inject_memory_leak.py --base-url http://localhost:8080 --chunk-mb 30 --steps 10
```
