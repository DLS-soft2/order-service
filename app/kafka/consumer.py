import asyncio
import json
import logging
from uuid import UUID

from aiokafka import AIOKafkaConsumer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.db.tables import Order, ProcessedEvent
from app.service.saga import VALID_TRANSITIONS, apply_transition

logger = logging.getLogger(__name__)


# Kafka consumer for the Order Service.
# Subscribes to payments, restaurants, couriers, and deliveries topics.
# Routes incoming events by event_type to apply saga status transitions.
# All consumption is idempotent via the processed_events table.



def is_event_processed(event_id: str, db: Session) -> bool:
    """Check if an event has already been processed (idempotency guard)."""
    return db.query(ProcessedEvent).filter_by(event_id=event_id).first() is not None


def mark_event_processed(event_id: str, topic: str, db: Session) -> None:
    """Record that an event has been processed."""
    db.add(ProcessedEvent(event_id=event_id, topic=topic))
    db.commit()


def handle_event(message_value: dict, topic: str, db: Session) -> None:
    """Handle a single incoming Kafka event.

    1. Check idempotency — skip if already processed.
    2. Look up the order — skip with warning if not found.
    3. Resolve target status from event_type via VALID_TRANSITIONS.
    4. Apply the saga transition (commutative guard inside).
    5. Mark the event as processed.
    """
    event_id = message_value.get("event_id")
    event_type = message_value.get("event_type")
    order_id = message_value.get("order_id")

    if not event_id:
        logger.warning("Missing event_id in message — skipping")
        return

    if not order_id:
        logger.warning("Missing order_id in message (event %s) — skipping", event_id)
        return

    if is_event_processed(str(event_id), db):
        logger.info("Duplicate event %s — skipping", event_id)
        return

    order = db.query(Order).filter_by(id=UUID(order_id)).first()
    if order is None:
        logger.warning("Order %s not found for event %s — skipping", order_id, event_id)
        mark_event_processed(str(event_id), topic, db)
        return

    target_status = VALID_TRANSITIONS.get(event_type)
    if target_status is None:
        logger.warning("Unknown event_type %s — skipping", event_type)
        mark_event_processed(str(event_id), topic, db)
        return

    applied = apply_transition(order, target_status, db)
    if applied:
        logger.info("Order %s transitioned to %s via %s", order_id, target_status, event_type)
    else:
        logger.info("Transition to %s rejected for order %s (current: %s)", target_status, order_id, order.status)

    mark_event_processed(str(event_id), topic, db)


async def start_consumer() -> None:
    """Start the multi-topic Kafka consumer loop.

    Subscribes to payments, restaurants, couriers, and deliveries topics.
    Uses group_id 'order-service-group' for horizontal scaling.
    Retries connection up to 10 times with 3-second intervals.
    """
    topics = [
        settings.kafka_topic_payments,
        settings.kafka_topic_restaurants,
        settings.kafka_topic_couriers,
        settings.kafka_topic_deliveries,
    ]

    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="order-service-group",
        auto_offset_reset="earliest",
    )

    for attempt in range(1, 11):
        try:
            await consumer.start()
            logger.info("Kafka consumer started — listening on %s", topics)
            break
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("Kafka not ready for consumer (attempt %d/10): %s", attempt, exc)
            if attempt == 10:
                raise
            await asyncio.sleep(3)

    try:
        async for message in consumer:
            try:
                value = json.loads(message.value.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.warning("Skipping invalid message at offset %d: %s", message.offset, exc)
                continue

            logger.info(
                "Received message from topic '%s' partition %d offset %d",
                message.topic, message.partition, message.offset,
            )

            db = SessionLocal()
            try:
                handle_event(value, message.topic, db)
            finally:
                db.close()

    except asyncio.CancelledError:
        logger.info("Consumer task was cancelled")
    except Exception as exc:
        logger.error("Consumer crashed with error: %s", exc, exc_info=True)
    finally:
        await consumer.stop()
        logger.info("Kafka consumer stopped")
