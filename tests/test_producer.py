from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from apps.producer import main as producer_main
from tests.test_privacy_and_features import SOURCE_ROW


class Producer:
    def flush(self, _timeout: float) -> int:
        return 0


def test_replay_publishes_timestamp_ordered_validated_events(tmp_path, monkeypatch) -> None:
    first = {**SOURCE_ROW, "trans_num": "first-transaction-id-000000000001"}
    second = {
        **SOURCE_ROW,
        "trans_date_trans_time": "2020-06-21 12:14:26",
        "trans_num": "second-transaction-id-00000000002",
    }
    source = tmp_path / "fraud.csv"
    pd.DataFrame([first, second]).to_csv(source, index=False)
    settings = SimpleNamespace(
        replay_mode="max",
        dataset_path=str(source),
        replay_limit=2,
        pii_hash_salt="test-salt",
        kafka_bootstrap_servers="unused:9092",
    )
    published = []
    monkeypatch.setattr(producer_main, "RUNNING", True)
    monkeypatch.setattr(producer_main, "get_settings", lambda: settings)
    monkeypatch.setattr(producer_main, "wait_for_kafka", lambda _factory: Producer())
    monkeypatch.setattr(
        producer_main,
        "publish_json",
        lambda _producer, topic, key, payload: published.append((topic, key, payload)),
    )

    count = producer_main.replay("max")

    assert count == 2
    assert [item[1] for item in published] == [first["trans_num"], second["trans_num"]]
    assert published[0][2]["customer_id"] != SOURCE_ROW["cc_num"]
