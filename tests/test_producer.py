"""Tests for the Kafka producer module."""

import logging
from unittest.mock import AsyncMock, patch

import pytest

from app.kafka import producer as producer_module
from app.kafka.producer import publish_event


@pytest.fixture(autouse=True)
def _reset_producer():
    """Ensure module-level producer is reset between tests."""
    original = producer_module.producer
    yield
    producer_module.producer = original


async def test_publish_event_sends_to_correct_topic():
    """publish_event calls send_and_wait with the specified topic."""
    mock_producer = AsyncMock()
    producer_module.producer = mock_producer

    await publish_event(topic="orders", event_data={"event_type": "OrderCreated", "order_id": "abc"}, key="abc")

    mock_producer.send_and_wait.assert_called_once()
    call_kwargs = mock_producer.send_and_wait.call_args.kwargs
    assert call_kwargs["topic"] == "orders"


async def test_publish_event_uses_key_as_utf8_partition_key():
    """publish_event encodes the key parameter as UTF-8 bytes for the partition key."""
    mock_producer = AsyncMock()
    producer_module.producer = mock_producer
    order_id = "d290f1ee-6c54-4b01-90e6-d701748f0851"

    await publish_event(topic="orders", event_data={"order_id": order_id}, key=order_id)

    call_kwargs = mock_producer.send_and_wait.call_args.kwargs
    assert call_kwargs["key"] == order_id.encode("utf-8")


async def test_publish_event_logs_warning_when_producer_is_none(caplog):
    """publish_event logs a warning and returns early when producer is not started."""
    producer_module.producer = None

    with caplog.at_level(logging.WARNING):
        await publish_event(topic="orders", event_data={"event_type": "OrderCreated"}, key="abc")

    assert "Producer not started" in caplog.text


async def test_publish_event_passes_event_data_as_value():
    """publish_event forwards event_data as the message value."""
    mock_producer = AsyncMock()
    producer_module.producer = mock_producer
    event_data = {"event_type": "OrderCreated", "order_id": "abc", "amount": 25.0}

    await publish_event(topic="orders", event_data=event_data, key="abc")

    call_kwargs = mock_producer.send_and_wait.call_args.kwargs
    assert call_kwargs["value"] == event_data
