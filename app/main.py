import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import settings
from app.api import orders
from app.kafka.producer import start_producer, stop_producer
from app.kafka.consumer import start_consumer

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start Kafka producer and consumer on startup; stop on shutdown."""
    await start_producer()

    consumer_task = asyncio.create_task(start_consumer())
    logger.info("Kafka consumer background task started")

    yield

    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        logger.info("Kafka consumer task cancelled")

    await stop_producer()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Order Service",
    description="Saga state holder for the DLS-2 food delivery platform",
    version=settings.service_version,
    lifespan=lifespan,
)
Instrumentator().instrument(app).expose(app)

app.include_router(orders.router)


@app.get("/")
def root():
    """Service info endpoint."""
    return {
        "service": settings.service_name,
        "version": settings.service_version,
    }


@app.get("/health")
def health():
    """Health check for monitoring and container orchestration."""
    return {"status": "healthy"}
