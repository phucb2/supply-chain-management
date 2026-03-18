from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.session import engine
from app.routes import orders, shipments, warehouse, webhooks
from app.telemetry import setup_telemetry


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_telemetry()
    yield
    await engine.dispose()


app = FastAPI(
    title="Supply Chain Order Integration API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(orders.router, prefix="/orders", tags=["Orders"])
app.include_router(shipments.router, prefix="/shipments", tags=["Shipments"])
app.include_router(warehouse.router, prefix="/warehouse", tags=["Warehouse"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])


@app.get("/health")
async def health():
    return {"status": "ok"}
