from importlib.metadata import PackageNotFoundError, version
from pydantic_settings import BaseSettings, SettingsConfigDict


def _get_default_service_version() -> str:
    """Derive the default service version from installed package metadata."""
    try:
        return version("order-service")
    except PackageNotFoundError:
        return "0.1.0"


class Settings(BaseSettings):
    """Central configuration for the Order Service."""

    model_config = SettingsConfigDict(env_file=".env")

    # Service metadata
    service_name: str = "order-service"
    service_version: str = _get_default_service_version()

    # PostgreSQL connection
    database_url: str = "postgresql://order:order@localhost:5432/order_db"

    # Kafka connection
    kafka_bootstrap_servers: str = "localhost:9092"

    # Kafka topics this service interacts with
    kafka_topic_orders: str = "orders"
    kafka_topic_payments: str = "payments"
    kafka_topic_restaurants: str = "restaurants"
    kafka_topic_couriers: str = "couriers"
    kafka_topic_deliveries: str = "deliveries"


# Single instance used throughout the app
settings = Settings()
