from __future__ import annotations

import logging
import os
import signal
import time

from monitoring.drift_job import DriftConfig, run

LOGGER = logging.getLogger("lossguard.drift_scheduler")
RUNNING = True


def stop(*_) -> None:
    global RUNNING
    RUNNING = False


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    interval = max(int(os.getenv("DRIFT_INTERVAL_SECONDS", "604800")), 60)
    config = DriftConfig.from_env()
    while RUNNING:
        try:
            run(config)
        except Exception:
            LOGGER.exception("Scheduled drift report failed")
        deadline = time.monotonic() + interval
        while RUNNING and time.monotonic() < deadline:
            time.sleep(min(30, deadline - time.monotonic()))


if __name__ == "__main__":
    main()
