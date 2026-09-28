"""Entrypoint: live side-view posture monitoring + periodic summary notifications.

    python main.py                 # monitor (starts the 6-hourly check too)
    python main.py --calibrate     # calibrate first, then monitor
    python main.py --summary       # print the trailing-window summary and exit
    python main.py --test-notification
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading

from src.calibration import run_calibration
from src.camera_stream import CameraStream
from src.config import CALIBRATION_PATH, load_config
from src.notifier import format_summary_message, send_notification
from src.posture_logger import PostureLogger
from src.scheduler import PostureScheduler

logger = logging.getLogger("posture")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Side-view sitting posture monitor with periodic push summaries."
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Run the guided calibration flow before monitoring.",
    )
    parser.add_argument(
        "--calibrate-seconds",
        type=int,
        default=5,
        help="Seconds of good posture to average during calibration (default: 5).",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print the trailing-window summary as JSON and exit.",
    )
    parser.add_argument(
        "--test-notification",
        action="store_true",
        help="Send one notification through the configured channel and exit.",
    )
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="Run headless: log samples without the live preview window.",
    )
    parser.add_argument(
        "--no-scheduler",
        action="store_true",
        help="Monitor without the periodic summary job.",
    )
    parser.add_argument("--verbose", action="store_true", help="Debug logging.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    config = load_config()
    posture_logger = PostureLogger(config.db_path, config.sample_interval_seconds)

    if args.summary:
        summary = posture_logger.get_bad_posture_summary(config.check_interval_hours)
        print(json.dumps(summary, indent=2))
        print("\n" + format_summary_message(summary, config.check_interval_hours))
        return 0

    if args.test_notification:
        summary = posture_logger.get_bad_posture_summary(config.check_interval_hours)
        ok = send_notification(
            title="Posture monitor test",
            message=format_summary_message(summary, config.check_interval_hours),
            config=config,
        )
        print("Notification sent." if ok else "Notification failed - see the log above.")
        return 0 if ok else 1

    # Calibrate either on request or automatically on the very first run.
    if args.calibrate or not CALIBRATION_PATH.exists():
        if not args.calibrate:
            print("No calibration.json found - running first-time calibration.")
        run_calibration(config, capture_seconds=args.calibrate_seconds)
        config = load_config()  # pick up freshly saved thresholds

    logger.info(
        "Thresholds -> CVA good >= %.1f, bad < %.1f | torso good <= %.1f, bad > %.1f (%s)",
        config.thresholds.cva_good,
        config.thresholds.cva_bad,
        config.thresholds.torso_good,
        config.thresholds.torso_bad,
        "calibrated" if config.calibrated else "defaults",
    )

    scheduler = None
    if not args.no_scheduler:
        scheduler = PostureScheduler(config, posture_logger)
        scheduler.start()

    stop_event = threading.Event()
    stream = CameraStream(
        config,
        posture_logger,
        show_window=not args.no_window,
        stop_event=stop_event,
    )

    def handle_signal(_signum, _frame):
        logger.info("Shutdown signal received.")
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    try:
        signal.signal(signal.SIGTERM, handle_signal)
    except (AttributeError, ValueError):  # not available on some platforms
        pass

    exit_code = 0
    try:
        stream.run()
    except RuntimeError as exc:
        logger.error("%s", exc)
        exit_code = 1
    except KeyboardInterrupt:
        logger.info("Interrupted.")
    finally:
        stream.stop()
        if scheduler:
            scheduler.shutdown()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
