from __future__ import annotations

import pytest
from confluent_kafka import KafkaException

from lossguard.kafka import publish_json


class FakeProducer:
    def __init__(self, delivery_error=None, never_deliver: bool = False) -> None:
        self.delivery_error = delivery_error
        self.never_deliver = never_deliver
        self.callback = None
        self.produced = None

    def produce(self, topic, *, key, value, on_delivery) -> None:
        self.produced = (topic, key, value)
        self.callback = on_delivery

    def poll(self, _timeout) -> None:
        if self.callback is not None and not self.never_deliver:
            callback, self.callback = self.callback, None
            callback(self.delivery_error, object())


def test_publish_json_waits_for_delivery_confirmation() -> None:
    producer = FakeProducer()

    publish_json(producer, "txns.scored", "txn-1", {"decision": "approve"})

    assert producer.produced == (
        "txns.scored",
        b"txn-1",
        b'{"decision":"approve"}',
    )


def test_publish_json_raises_delivery_error() -> None:
    producer = FakeProducer(delivery_error=RuntimeError("broker rejected record"))

    with pytest.raises(KafkaException):
        publish_json(producer, "txns.scored", "txn-1", {}, timeout_seconds=0.1)


def test_publish_json_times_out_without_confirmation() -> None:
    producer = FakeProducer(never_deliver=True)

    with pytest.raises(TimeoutError, match="delivery confirmation"):
        publish_json(producer, "txns.scored", "txn-1", {}, timeout_seconds=0.001)
