from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="SENTINEL Demo API", version="0.1.0")

Instrumentator().instrument(app).expose(app)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def hello() -> dict[str, str]:
    return {
        "service": "demo-api",
        "message": "hello from SENTINEL",
    }