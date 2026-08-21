import pytest

from apps.producer.replay_config import compute_delay, normalize_replay_mode


def test_demo_mode_compresses_time_by_720_with_floor():
    assert compute_delay(720, "demo") == pytest.approx(1.0)
    assert compute_delay(0, "demo") == pytest.approx(0.001)


def test_realtime_caps_long_gaps_at_two_seconds():
    assert compute_delay(1.25, "realtime") == pytest.approx(1.25)
    assert compute_delay(3_600, "realtime") == pytest.approx(2.0)


def test_max_mode_has_no_artificial_delay():
    assert compute_delay(86_400, "max") == 0.0


def test_replay_mode_validation_is_explicit():
    assert normalize_replay_mode(" DEMO ") == "demo"
    with pytest.raises(ValueError, match="unsupported replay mode"):
        normalize_replay_mode("fastish")
