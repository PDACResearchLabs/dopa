"""dopa sensor daemon — main loop.

Captures periodic webcam frames, runs local feature extraction on every frame,
deep vision analysis on a slower cadence, stores observations, and pushes
notifications when patterns deviate from baseline.

Usage:
    GEMINI_API_KEY=... python -m sensors.daemon
    GEMINI_API_KEY=... python -m sensors.daemon --interval 120 --deep-every 2 --verbose
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .camera import capture_frame, extract_local_features, CameraError
from .analyzer import deep_analysis, VisionAnalysisError
from .git_sensor import get_git_snapshot
from .store import (
    get_db,
    insert_observation,
    insert_event,
    last_notification_time,
    observation_count,
    deep_observation_count,
)
from .baseline import compute_baselines, check_deviations, generate_alert_message
from .notifier import send_notification

logger = logging.getLogger(__name__)
running = True


class _FlushHandler(logging.StreamHandler):
    """StreamHandler that flushes after every emit — prevents log buffering in nohup."""

    def emit(self, record):
        super().emit(record)
        self.flush()


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    handler = _FlushHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    logging.basicConfig(level=level, handlers=[handler], force=True)


def handle_signal(signum, frame):
    global running
    logger.info(f"Received signal {signum}, shutting down...")
    running = False


def main_loop(config: Config):
    global running

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    conn = get_db(config)
    capture_count = 0
    total_obs = observation_count(conn)
    total_deep = deep_observation_count(conn)
    camera_ok = True

    if config.cloud_vision_enabled:
        logger.info(
            f"dopa daemon started. Capture every {config.capture_interval_seconds}s, "
            f"cloud vision every {config.deep_analysis_every_n} captures "
            f"(~{config.deep_analysis_interval_seconds}s). Model: {config.gemini_model}"
        )
        logger.warning(
            "CLOUD VISION ENABLED: webcam frames are sent to Google Gemini for "
            "deep analysis. Unset DOPA_CLOUD_VISION to run fully local."
        )
    else:
        logger.info(
            f"dopa daemon started in LOCAL-ONLY mode (no frame leaves this machine). "
            f"Capture every {config.capture_interval_seconds}s. "
            f"Set DOPA_CLOUD_VISION=1 (+ GEMINI_API_KEY) to enable cloud vision."
        )
    logger.info(f"Stored observations: {total_obs} ({total_deep} deep)")
    sys.stdout.flush()

    while running:
        cycle_start = time.monotonic()
        capture_count += 1
        now = datetime.now(timezone.utc)
        do_deep = capture_count % config.deep_analysis_every_n == 0

        logger.info(
            f"Cycle {capture_count} — {now.strftime('%H:%M:%S')} UTC "
            f"(obs: {total_obs}, deep: {total_deep})"
        )
        sys.stdout.flush()

        # ---- Camera capture (optional) ----
        frame_bytes = None
        if camera_ok:
            try:
                frame_bytes = capture_frame(config)
                logger.debug("Camera: frame captured")
            except CameraError as e:
                logger.warning(f"Camera unavailable: {e}")
                camera_ok = False

        # ---- Local features ----
        local_features: dict = {}
        if frame_bytes:
            local_features = extract_local_features(frame_bytes)
            logger.debug(
                f"Local: faces={local_features.get('face_count', 0)}, "
                f"brightness={local_features.get('frame_mean_brightness', '?')}"
            )
        else:
            local_features = {"camera": "unavailable"}

        # ---- Deep analysis (periodic; OPT-IN cloud vision only) ----
        deep_result = None
        if frame_bytes and do_deep and config.cloud_vision_enabled:
            try:
                deep_result = asyncio.run(deep_analysis(frame_bytes, config))
                expr = deep_result.get("expression", {})
                fatigue = deep_result.get("fatigue_signs", {})
                confidence = deep_result.get("confidence", {})
                logger.info(
                    f"Deep: affect={expr.get('primary_affect', '?')}, "
                    f"fatigue={fatigue.get('overall_fatigue_level', '?')}, "
                    f"confidence={confidence.get('overall', '?')}"
                )
                sys.stdout.flush()
            except VisionAnalysisError as e:
                logger.error(f"Vision analysis failed: {e}")
                deep_result = {"error": str(e)}

        # ---- Git activity (every 6th cycle) ----
        git_activity = None
        if capture_count % 6 == 0:
            try:
                git_activity = get_git_snapshot(window_minutes=60)
                logger.info(
                    f"Git: {git_activity.get('total_commits', 0)} commits, "
                    f"{git_activity.get('repos_active', 0)} active repos"
                )
                sys.stdout.flush()
            except Exception as e:
                logger.error(f"Git sensor failed: {e}")

        # ---- Store ----
        insert_observation(conn, now, local_features, deep_result, git_activity)
        total_obs += 1
        if deep_result and "error" not in deep_result:
            total_deep += 1
        logger.debug("Stored.")

        # ---- Baseline & deviations (periodic) ----
        if total_deep >= config.min_observations_for_baseline and do_deep:
            compute_baselines(conn, config)
            alerts = check_deviations(conn, config)

            last_notif = last_notification_time(conn)
            cooldown_ok = (
                last_notif is None
                or (now - last_notif).total_seconds()
                > config.notification_cooldown_minutes * 60
            )

            for alert in alerts[:2]:
                msg = generate_alert_message(alert)
                insert_event(
                    conn,
                    event_type="deviation",
                    severity="warning",
                    marker=alert["marker"],
                    value=str(alert["value"]),
                    baseline=f"{alert['baseline_mean']}±{alert['baseline_std']}",
                    message=msg,
                )
                if cooldown_ok and config.notification_enabled:
                    sent = send_notification("dopa", msg)
                    if sent:
                        logger.info(f"Notification: {msg}")

        # ---- Wait for next cycle ----
        elapsed = time.monotonic() - cycle_start
        sleep_for = max(0, config.capture_interval_seconds - elapsed)
        logger.debug(f"Cycle took {elapsed:.1f}s, sleeping {sleep_for:.0f}s")
        sys.stdout.flush()

        # Sleep in 10s chunks so shutdown is responsive
        while running and sleep_for > 0:
            chunk = min(10, sleep_for)
            time.sleep(chunk)
            sleep_for -= chunk


def main():
    parser = argparse.ArgumentParser(description="dopa sensor daemon")
    parser.add_argument(
        "--interval", type=int, default=None, help="Capture interval in seconds"
    )
    parser.add_argument(
        "--deep-every",
        type=int,
        default=None,
        help="Run deep vision analysis every N captures",
    )
    parser.add_argument(
        "--model", type=str, default=None, help="Gemini vision model"
    )
    parser.add_argument(
        "--once", action="store_true", help="Capture and analyze once, then exit"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Debug logging"
    )
    args = parser.parse_args()

    setup_logging(args.verbose)

    config = Config()
    if args.interval:
        config.capture_interval_seconds = args.interval
    if args.deep_every:
        config.deep_analysis_every_n = args.deep_every
    if args.model:
        config.gemini_model = args.model

    # Cloud vision is opt-in. Local-only mode needs no API key.
    if config.cloud_vision_enabled and not config.gemini_api_key:
        print(
            "DOPA_CLOUD_VISION is enabled but GEMINI_API_KEY is not set.\n"
            "Either unset DOPA_CLOUD_VISION to run fully local (no frames leave your\n"
            "machine), or get a key at https://aistudio.google.com/apikey and:\n"
            "  export GEMINI_API_KEY=..."
        )
        sys.exit(1)

    if args.once:
        setup_logging(verbose=True)
        conn = get_db(config)
        now = datetime.now(timezone.utc)

        # Camera
        local: dict = {"camera": "unavailable"}
        deep_result = None
        try:
            frame = capture_frame(config)
            local = extract_local_features(frame)
            print("Local features:", json.dumps(local, indent=2))
            if config.cloud_vision_enabled:
                deep_result = asyncio.run(deep_analysis(frame, config))
                print("Deep analysis:", json.dumps(deep_result, indent=2))
            else:
                print("Cloud vision disabled (local-only). Set DOPA_CLOUD_VISION=1 to enable.")
        except CameraError as e:
            print(f"Camera unavailable: {e}")
            print("Grant camera permission in System Settings > Privacy > Camera")
            print("Git sensor will still collect data.")

        # Git
        git_activity = get_git_snapshot(window_minutes=60)
        print("Git activity:", json.dumps(git_activity.get("metrics", {}), indent=2))
        insert_observation(conn, now, local, deep_result, git_activity)
        print("Stored.")
        return

    try:
        main_loop(config)
    except KeyboardInterrupt:
        logger.info("Daemon stopped by user.")
    finally:
        logger.info("dopa daemon exited.")


if __name__ == "__main__":
    main()
