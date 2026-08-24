from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="SENTINEL hello service", version="0.1.0")

Instrumentator().instrument(app).expose(app)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def hello() -> dict[str, str]:
    return {"service": "sentinel-hello", "message": "hello from SENTINEL"}