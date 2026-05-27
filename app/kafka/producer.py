import asyncio
import json
import logging
from aiokafka import AIOKafkaProducer
from app.config import settings

logger = logging.getLogger(__name__)

# Kafka producer for the Order Service.

# Sends order lifecycle events to the 'orders' topic.
# Other services (Payment, Restaurant, Notification) consume
# these events to react to order state changes.

# The producer is started once during app startup (in main.py's
# lifespan) and reused for all messages.


# Module-level reference — set during app startup, used everywhere
producer: AIOKafkaProducer | None = None  # pylint: disable=invalid-name


async def start_producer() -> None:
    """Start the Kafka producer with retry logic.

    Kafka might not be ready when the service starts, so we
    retry up to 10 times with 3 seconds between attempts.
    """
    global producer  # pylint: disable=global-statement
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
    )

    for attempt in range(1, 11):
        try:
            await producer.start()
            logger.info("Kafka producer started")
            return
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Kafka not ready (attempt %d/10): %s", attempt, exc
            )
            if attempt == 10:
                raise
            await asyncio.sleep(3)


async def stop_producer() -> None:
    """Stop the Kafka producer gracefully. Called during app shutdown."""
    global producer  # pylint: disable=global-statement
    if producer:
        await producer.stop()
        logger.info("Kafka producer stopped")
        producer = None


async def publish_event(topic: str, event_data: dict, key: str) -> None:
    """Publish an event to a Kafka topic.

    Args:
        topic: The Kafka topic name (e.g. "orders")
        event_data: Dictionary that will be serialized to JSON
        key: Partition key (e.g. order_id as string). Ensures all
             events for the same order go to the same partition.
    """
    if not producer:
        logger.warning("Producer not started — cannot publish event")
        return

    await producer.send_and_wait(
        topic=topic,
        value=event_data,
        key=key.encode("utf-8"),
    )
    logger.info("Published %s to topic '%s'", event_data.get("event_type"), topic)
