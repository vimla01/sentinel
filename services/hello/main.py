from fastapi import FastAPI

app = FastAPI(title="SENTINEL hello service", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def hello() -> dict[str, str]:
    return {"service": "sentinel-hello", "message": "hello from SENTINEL"}
