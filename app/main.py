from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import settings
from app import database
from app.database import Base
from app.db import tables  # pylint: disable=unused-import  # registers ORM models with Base.metadata
from app.api import orders


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Create database tables on startup."""
    Base.metadata.create_all(bind=database.engine)
    yield


app = FastAPI(
    title="Order Service",
    description="Saga state holder for the DLS-2 food delivery platform",
    version=settings.service_version,
    lifespan=lifespan,
)

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
