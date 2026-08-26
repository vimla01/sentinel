import random
import threading
import time
from dataclasses import dataclass

from fastapi import FastAPI, Request, Response
from prometheus_client import REGISTRY
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field

app = FastAPI(title="SENTINEL demo-api", version="0.1.0")

# metrics.default() re-registers the same collector names on every call, which
# raises if another instrumented FastAPI app already did so in this process
# (e.g. the test suite importing multiple services together).
_instrumentator = Instrumentator()
if "http_requests_total" not in REGISTRY._names_to_collectors:
    _instrumentator.instrument(app)
_instrumentator.expose(app)

_EXEMPT_PATHS = {"/healthz", "/metrics"}
_memory_ballast: list[bytearray] = []


@dataclass
class ChaosState:
    cpu_spike_until: float = 0.0
    cpu_stop_event: threading.Event | None = None
    latency_ms: int = 0
    latency_until: float = 0.0
    error_probability: float = 0.0
    error_until: float = 0.0

    def status(self) -> dict[str, float | int | bool]:
        now = time.monotonic()
        return {
            "memory_leak_mb": sum(len(chunk) for chunk in _memory_ballast) // (1024 * 1024),
            "cpu_spike_active": now < self.cpu_spike_until,
            "cpu_spike_remaining_seconds": round(max(0.0, self.cpu_spike_until - now), 1),
            "latency_ms": self.latency_ms if now < self.latency_until else 0,
            "error_probability": self.error_probability if now < self.error_until else 0.0,
        }


chaos = ChaosState()


def _cpu_burn(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        pass


class LeakMemoryRequest(BaseModel):
    chunk_mb: int = Field(default=20, ge=1, le=512)


class CpuSpikeRequest(BaseModel):
    duration_seconds: float = Field(default=30.0, gt=0, le=600)
    workers: int = Field(default=2, ge=1, le=8)


class LatencyRequest(BaseModel):
    delay_ms: int = Field(default=500, ge=0, le=10_000)
    duration_seconds: float = Field(default=60.0, gt=0, le=3600)


class ErrorRateRequest(BaseModel):
    probability: float = Field(default=0.3, ge=0.0, le=1.0)
    duration_seconds: float = Field(default=60.0, gt=0, le=3600)


@app.middleware("http")
async def chaos_middleware(request: Request, call_next):
    if request.url.path in _EXEMPT_PATHS or request.url.path.startswith("/debug"):
        return await call_next(request)

    now = time.monotonic()
    if chaos.latency_ms > 0 and now < chaos.latency_until:
        time.sleep(chaos.latency_ms / 1000)
    if chaos.error_probability > 0 and now < chaos.error_until:
        if random.random() < chaos.error_probability:
            return Response(content="chaos: injected error", status_code=500)
    return await call_next(request)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def hello() -> dict[str, str]:
    return {"service": "sentinel-demo-api", "message": "hello from SENTINEL demo-api"}


@app.get("/debug/status")
def debug_status() -> dict[str, float | int | bool]:
    return chaos.status()


@app.post("/debug/leak-memory")
def leak_memory(payload: LeakMemoryRequest) -> dict[str, float | int | bool]:
    _memory_ballast.append(bytearray(payload.chunk_mb * 1024 * 1024))
    return chaos.status()


@app.post("/debug/cpu-spike")
def cpu_spike(payload: CpuSpikeRequest) -> dict[str, float | int | bool]:
    if chaos.cpu_stop_event is not None:
        chaos.cpu_stop_event.set()

    stop_event = threading.Event()
    chaos.cpu_stop_event = stop_event
    chaos.cpu_spike_until = time.monotonic() + payload.duration_seconds

    for _ in range(payload.workers):
        threading.Thread(target=_cpu_burn, args=(stop_event,), daemon=True).start()

    def _stop_later() -> None:
        time.sleep(payload.duration_seconds)
        stop_event.set()

    threading.Thread(target=_stop_later, daemon=True).start()
    return chaos.status()


@app.post("/debug/latency")
def latency(payload: LatencyRequest) -> dict[str, float | int | bool]:
    chaos.latency_ms = payload.delay_ms
    chaos.latency_until = time.monotonic() + payload.duration_seconds
    return chaos.status()


@app.post("/debug/error-rate")
def error_rate(payload: ErrorRateRequest) -> dict[str, float | int | bool]:
    chaos.error_probability = payload.probability
    chaos.error_until = time.monotonic() + payload.duration_seconds
    return chaos.status()


@app.post("/debug/reset")
def reset() -> dict[str, float | int | bool]:
    if chaos.cpu_stop_event is not None:
        chaos.cpu_stop_event.set()
    _memory_ballast.clear()
    chaos.cpu_spike_until = 0.0
    chaos.cpu_stop_event = None
    chaos.latency_ms = 0
    chaos.latency_until = 0.0
    chaos.error_probability = 0.0
    chaos.error_until = 0.0
    return chaos.status()
