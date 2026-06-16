"""Vision model analysis — sends frames to Gemini for deep feature extraction."""

import json
import logging
from google import genai
from google.genai import types as genai_types
from .config import Config

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """Analyze this webcam frame of a person working at their computer. Return ONLY valid JSON, no other text, no markdown fences, no explanation.

Extract these specific markers. Use "unknown" if a marker cannot be determined from a single still frame.

{
  "presence": "present" | "absent" | "partially_visible" | "unknown",
  "head_pose": {
    "orientation": "screen" | "down_phone" | "down_desk" | "away_window" | "away_other" | "hand_supporting_head" | "unknown",
    "tilt": "upright" | "forward" | "left" | "right" | "unknown"
  },
  "eyes": {
    "openness": "wide" | "normal" | "narrowed" | "drooping" | "closed" | "unknown",
    "gaze_target": "screen" | "phone" | "off_screen_right" | "off_screen_left" | "up" | "down" | "distant_stare" | "unknown",
    "squint": true | false
  },
  "expression": {
    "primary_affect": "neutral" | "focused" | "confused" | "frustrated" | "bored" | "anxious" | "sad" | "flat" | "amused" | "surprised" | "tired" | "unknown",
    "intensity": "subtle" | "moderate" | "strong",
    "expressivity_range": "restricted" | "normal" | "elevated" | "unknown"
  },
  "posture": {
    "position": "upright" | "leaning_forward" | "leaning_back" | "slumped" | "head_in_hands" | "unknown",
    "shoulder_visible": true | false
  },
  "engagement": {
    "appears_engaged_with_screen": "yes" | "no" | "unclear",
    "appears_typing_or_active": "yes" | "no" | "unclear",
    "attention_quality": "sustained" | "fragmented_look" | "dissociated" | "unknown"
  },
  "fatigue_signs": {
    "eye_rubbing": true | false,
    "yawning": true | false,
    "head_propping": true | false,
    "overall_fatigue_level": "none_visible" | "mild" | "moderate" | "significant" | "unknown"
  },
  "confidence": {
    "overall": 0.0_to_1.0,
    "face_visible": true | false,
    "lighting_adequate": true | false
  }
}"""


class VisionAnalysisError(Exception):
    """Vision API call failed."""


async def deep_analysis(frame_bytes: bytes, config: Config) -> dict:
    """Send frame to Gemini for deep behavioral analysis."""
    if not config.gemini_api_key:
        raise VisionAnalysisError("GEMINI_API_KEY not set in environment.")

    client = genai.Client(api_key=config.gemini_api_key)

    try:
        response = await client.aio.models.generate_content(
            model=config.gemini_model,
            contents=[
                genai_types.Part.from_bytes(data=frame_bytes, mime_type="image/jpeg"),
                genai_types.Part.from_text(text=ANALYSIS_PROMPT),
            ],
            config=genai_types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=config.gemini_max_tokens,
                thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
            ),
        )
    except Exception as e:
        raise VisionAnalysisError(f"Gemini API call failed: {e}") from e

    text = response.text
    if not text:
        raise VisionAnalysisError("Gemini returned empty response.")

    return _parse_json_response(text.strip())


def _parse_json_response(text: str) -> dict:
    """Extract JSON from model response, handling markdown fences and noise."""
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove opening fence (may include language tag)
        lines = lines[1:]
        # Remove closing fence if present
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object bounds
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    logger.warning(f"Failed to parse vision response as JSON: {text[:200]}")
    return {"raw_response": text, "parse_error": True}


def merge_observation(local_features: dict, deep_result: dict | None) -> dict:
    """Merge local and deep features into a single observation record."""
    obs = dict(local_features)
    if deep_result:
        obs["deep"] = deep_result
    return obs
