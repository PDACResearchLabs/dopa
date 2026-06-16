"""macOS notification delivery."""

import subprocess
import logging

logger = logging.getLogger(__name__)


def send_notification(title: str, message: str, sound: bool = True) -> bool:
    """Fire a macOS notification via osascript."""
    script = f'display notification "{message}" with title "{title}"'
    if sound:
        script += ' sound name "default"'
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5,
        )
        return True
    except Exception as e:
        logger.error(f"Notification failed: {e}")
        return False


def notify_if_alert(title: str, message: str, cooldown_seconds: int = 1800) -> bool:
    """Send notification with a simple time-based throttle. Best-effort."""
    return send_notification(title, message)
