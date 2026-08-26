from fastapi import FastAPI
from prometheus_client import REGISTRY
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="SENTINEL hello service", version="0.1.0")

# metrics.default() re-registers the same collector names on every call, which
# raises if another instrumented FastAPI app already did so in this process
# (e.g. the test suite importing multiple services together).
_instrumentator = Instrumentator()
if "http_requests_total" not in REGISTRY._names_to_collectors:
    _instrumentator.instrument(app)
_instrumentator.expose(app)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def hello() -> dict[str, str]:
    return {"service": "sentinel-hello", "message": "hello from SENTINEL"}