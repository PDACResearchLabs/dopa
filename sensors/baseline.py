"""Baseline computation and deviation detection."""

import json
import logging
from datetime import datetime, timedelta, timezone
from .store import (
    observations_since,
    update_baseline,
    get_baseline,
    insert_event,
    recent_observations,
)

logger = logging.getLogger(__name__)

TRENDABLE_MARKERS = [
    ("deep.engagement.attention_quality", "ordinal", {"sustained": 0, "fragmented_look": 1, "dissociated": 2}),
    ("deep.expression.primary_affect", "categorical_set", {
        "negative": {"frustrated", "anxious", "sad", "bored", "tired", "flat"},
        "positive": {"focused", "neutral", "amused"},
    }),
    ("deep.expression.expressivity_range", "ordinal", {"restricted": 0, "normal": 1, "elevated": 2}),
    ("deep.fatigue_signs.overall_fatigue_level", "ordinal", {
        "none_visible": 0, "mild": 1, "moderate": 2, "significant": 3,
    }),
    ("deep.posture.position", "categorical_set", {
        "negative": {"slumped", "head_in_hands"},
        "positive": {"upright", "leaning_forward"},
        "neutral": {"leaning_back"},
    }),
    ("deep.head_pose.orientation", "categorical_set", {
        "engaged": {"screen"},
        "disengaged": {"down_phone", "away_window", "away_other", "down_desk"},
        "fatigue": {"hand_supporting_head"},
    }),
    ("deep.eyes.openness", "ordinal", {"wide": 0, "normal": 0, "narrowed": 1, "drooping": 2, "closed": 3}),
    ("deep.presence", "binary_present", {}),
    ("face_brightness", "numeric", {}),
    ("face_ratio", "numeric", {}),
    # Git activity markers
    ("git.ships_in_window", "numeric", {}),
    ("git.active_repo_count", "numeric", {}),
    ("git.burst_detected", "binary_present", {}),
    ("git.hyperfocus_pattern", "binary_present", {}),
    ("git.fragmentation_flag", "binary_present", {}),
    ("git.late_night_ratio", "numeric", {}),
]


def _extract_value(obs: dict, path: str) -> str | float | None:
    """Walk a dotted path into the observation dict."""
    parts = path.split(".")
    val = obs
    for p in parts:
        if isinstance(val, dict):
            val = val.get(p)
        else:
            return None
    return val


def _to_numeric(value, marker_type: str, mapping: dict) -> float | None:
    if value is None or value == "unknown":
        return None
    if marker_type == "numeric":
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    if marker_type == "ordinal":
        return mapping.get(str(value))
    if marker_type == "categorical_set":
        for label, keys in mapping.items():
            if str(value) in keys:
                if label in ("negative", "disengaged", "fatigue"):
                    return 1.0
                elif label in ("positive", "engaged"):
                    return 0.0
                return 0.5
        return None
    if marker_type == "binary_present":
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        return 1.0 if str(value).lower() in ("true", "present") else 0.0
    return None


def _load_observation(row) -> dict:
    """Load all sensor data from an observation row into a flat namespace dict."""
    obs: dict = {}
    if row["local_features"]:
        obs.update(json.loads(row["local_features"]))
    if row["deep_result"]:
        obs["deep"] = json.loads(row["deep_result"])
    if row["git_activity"]:
        ga = json.loads(row["git_activity"])
        metrics = ga.get("metrics", {})
        for k, v in metrics.items():
            obs[f"git.{k}"] = v
        obs["git._total_commits"] = ga.get("total_commits", 0)
    return obs


def compute_baselines(conn, config) -> dict:
    """Recompute baselines from recent observations."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.baseline_window_days)
    rows = observations_since(conn, cutoff)
    if not rows:
        return {}

    results = {}
    for marker_path, marker_type, mapping in TRENDABLE_MARKERS:
        values = []
        for row in rows:
            obs = _load_observation(row)
            raw = _extract_value(obs, marker_path)
            num = _to_numeric(raw, marker_type, mapping)
            if num is not None:
                values.append(num)

        if len(values) >= 3:
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            std = variance ** 0.5
            if std == 0:
                std = 0.01
            update_baseline(conn, marker_path, mean, std, len(values))
            results[marker_path] = {"mean": mean, "std": std, "n": len(values)}

    return results


def check_deviations(conn, config) -> list[dict]:
    """Check latest observation against baselines and return triggered alerts."""
    baselines = {}
    for marker_path, _, _ in TRENDABLE_MARKERS:
        bl = get_baseline(conn, marker_path)
        if bl and bl["n"] >= 3:
            baselines[marker_path] = bl

    if not baselines:
        return []

    rows = recent_observations(conn, limit=3)
    if not rows:
        return []

    alerts = []
    latest = rows[0]
    obs = _load_observation(latest)

    for marker_path, marker_type, mapping in TRENDABLE_MARKERS:
        bl = baselines.get(marker_path)
        if not bl:
            continue

        raw = _extract_value(obs, marker_path)
        num = _to_numeric(raw, marker_type, mapping)
        if num is None:
            continue

        deviation = (num - bl["mean"]) / bl["std"]

        if abs(deviation) >= config.deviation_threshold_std:
            direction = "above" if deviation > 0 else "below"
            alerts.append({
                "marker": marker_path,
                "value": raw,
                "numeric_value": num,
                "baseline_mean": round(bl["mean"], 3),
                "baseline_std": round(bl["std"], 3),
                "deviation_std": round(deviation, 2),
                "direction": direction,
            })

    return alerts


def generate_alert_message(alert: dict) -> str:
    """Turn a deviation alert into a human-readable notification message."""
    marker = alert["marker"]
    direction = alert["direction"]
    messages = {
        "deep.expression.expressivity_range": {
            "below": "Your expressivity has dropped below baseline. You might be running low.",
        },
        "deep.expression.primary_affect": {
            "above": "More negative affect than usual showing up. Something weighing on you?",
        },
        "deep.fatigue_signs.overall_fatigue_level": {
            "above": "Physical fatigue signals are up. When did you last step away?",
        },
        "deep.posture.position": {
            "above": "Posture has collapsed — energy might be crashing.",
        },
        "deep.eyes.openness": {
            "above": "You're showing fatigue in your eyes. Break time?",
        },
        "deep.engagement.attention_quality": {
            "above": "Attention looks fragmented. Stuck on something?",
        },
        "deep.head_pose.orientation": {
            "above": "Screen engagement is down. Avoidance or just need a reset?",
        },
        "deep.presence": {
            "below": "You've been away from the desk a while. Everything ok?",
        },
        "git.ships_in_window": {
            "below": "Ship rate dropped below your baseline. Avoidance or just a slow day?",
        },
        "git.fragmentation_flag": {
            "above": "You're switching between a lot of repos. Scattered or exploring?",
        },
        "git.late_night_ratio": {
            "above": "Late night commits are up. Hyperfocus or delayed sleep phase?",
        },
    }

    defaults = {
        "above": f"{marker} elevated above your baseline.",
        "below": f"{marker} dropped below your baseline.",
    }

    return messages.get(marker, {}).get(direction, defaults[direction])
