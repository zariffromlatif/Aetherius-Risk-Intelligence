import uuid

from fastapi import FastAPI, Request

from app.api.routers import (
    auth,
    clients,
    delivery,
    observations,
    operator_console,
    ops,
    reporting,
    review,
    signals,
    watchlists,
)
from app.core.config import settings
from app.utils.logging import configure_logging, correlation_id_var

app = FastAPI(title=settings.app_name)


@app.on_event("startup")
def startup() -> None:
    configure_logging()


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    cid = request.headers.get("x-correlation-id", str(uuid.uuid4()))
    token = correlation_id_var.set(cid)
    try:
        response = await call_next(request)
    finally:
        correlation_id_var.reset(token)
    response.headers["x-correlation-id"] = cid
    return response


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "aetherius"}


app.include_router(clients.router, prefix=settings.api_prefix)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(watchlists.router, prefix=settings.api_prefix)
app.include_router(observations.router, prefix=settings.api_prefix)
app.include_router(signals.router, prefix=settings.api_prefix)
app.include_router(review.router, prefix=settings.api_prefix)
app.include_router(delivery.router, prefix=settings.api_prefix)
app.include_router(reporting.router, prefix=settings.api_prefix)
app.include_router(operator_console.router, prefix=settings.api_prefix)
app.include_router(ops.router, prefix=settings.api_prefix)
