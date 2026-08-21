from __future__ import annotations

from typing import Literal, cast

ReplayMode = Literal["realtime", "demo", "max"]

SPEED_MULTIPLIERS: dict[ReplayMode, float | None] = {
    "realtime": 1.0,
    "demo": 720.0,
    "max": None,
}
MIN_DELAY_SECONDS = 0.001
REALTIME_GAP_CAP_SECONDS = 2.0


def normalize_replay_mode(mode: str) -> ReplayMode:
    normalized = mode.strip().lower()
    if normalized not in SPEED_MULTIPLIERS:
        choices = ", ".join(SPEED_MULTIPLIERS)
        raise ValueError(f"unsupported replay mode {mode!r}; choose one of: {choices}")
    return cast(ReplayMode, normalized)


def compute_delay(actual_delta_seconds: float, mode: str) -> float:
    """Return the artificial delay before publishing the next source event."""
    replay_mode = normalize_replay_mode(mode)
    multiplier = SPEED_MULTIPLIERS[replay_mode]
    if multiplier is None:
        return 0.0

    non_negative_delta = max(float(actual_delta_seconds), 0.0)
    if replay_mode == "realtime":
        non_negative_delta = min(non_negative_delta, REALTIME_GAP_CAP_SECONDS)
    return max(non_negative_delta / multiplier, MIN_DELAY_SECONDS)
