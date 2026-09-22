from types import SimpleNamespace

import pytest

from apps.outbox_publisher.main import publish_once, stop


class Repository:
    def __init__(self):
        self.published = []
        self.released = []

    def claim_outbox(self, _batch_size):
        return "token", [
            {"outbox_id": 1, "topic": "txns.scored", "message_key": "one", "payload": {"x": 1}}
        ]

    def mark_outbox_published(self, outbox_id, token):
        self.published.append((outbox_id, token))

    def release_outbox(self, outbox_id, token, error):
        self.released.append((outbox_id, token, error))


def test_publish_once_marks_broker_confirmed_message(monkeypatch):
    repository = Repository()
    calls = []
    monkeypatch.setattr(
        "apps.outbox_publisher.main.publish_json",
        lambda producer, topic, key, payload: calls.append((producer, topic, key, payload)),
    )
    assert publish_once(repository, "producer", 10) == 1
    assert repository.published == [(1, "token")]
    assert calls[0][1:3] == ("txns.scored", "one")


def test_publish_once_releases_failed_claim(monkeypatch):
    repository = Repository()
    monkeypatch.setattr(
        "apps.outbox_publisher.main.publish_json",
        lambda *_args: (_ for _ in ()).throw(TimeoutError("broker unavailable")),
    )
    with pytest.raises(TimeoutError):
        publish_once(repository, "producer", 10)
    assert repository.released == [(1, "token", "TimeoutError")]


def test_stop_changes_run_flag(monkeypatch):
    monkeypatch.setattr("apps.outbox_publisher.main.RUNNING", True)
    stop()
    from apps.outbox_publisher import main

    assert main.RUNNING is False


def test_run_polls_and_closes_dependencies(monkeypatch):
    from apps.outbox_publisher import main

    class RuntimeRepository:
        def __init__(self, *_args, **_kwargs):
            self.ready = self.closed = False

        def wait_until_ready(self):
            self.ready = True

        def close(self):
            self.closed = True

    repository = RuntimeRepository()
    producer = SimpleNamespace(flush=lambda _timeout: 0)
    monkeypatch.setattr(main, "RUNNING", True)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(
            database_url="postgresql://test",
            postgres_pool_min_size=1,
            postgres_pool_max_size=2,
            kafka_bootstrap_servers="redpanda:9092",
        ),
    )
    monkeypatch.setattr(main, "TransactionRepository", lambda *_args, **_kwargs: repository)
    monkeypatch.setattr(main, "wait_for_kafka", lambda factory: producer)

    def publish_then_stop(*_args):
        main.RUNNING = False
        return 1

    monkeypatch.setattr(main, "publish_once", publish_then_stop)
    main.run()
    assert repository.ready and repository.closed
