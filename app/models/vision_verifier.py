"""
Vision verification layer for citizen hazard reports.

Provides a single public helper:
    verify_disaster_image(image_bytes: bytes, category: str) -> dict

Return shape:
    {
        "is_valid": bool,
        "confidence": float,
        "hazard_detected": str,
        "reason": str,
    }

Strict policy:
- Only accepts images that clearly depict natural disasters: flood water,
  rising water, landslide debris, fallen rocks, blocked roads due to natural
  hazards, or storm/cloudburst skies.
- Rejects selfies, people posing, indoor scenes, text screenshots, memes,
  cartoons, cityscapes without hazard, vehicles on normal roads, etc.
- If GROQ_API_KEY is not configured or Groq is unreachable, falls back to a
  strict deterministic heuristic so the prototype still filters most
  non-disaster images.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
from typing import Any

from PIL import Image, ImageStat

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Simple face / skin-tone pre-filter
# ---------------------------------------------------------------------------
def _looks_like_face_or_skin(raw: bytes) -> bool:
    """Reject images that appear to contain human faces or skin-heavy scenes.

    This is a lightweight heuristic, not a full face detector. It is designed
    to catch the most common false-positive case: photos of people that are
    not disaster evidence.
    """
    try:
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        small = im.resize((64, 64))
        pixels = list(small.getdata())

        # Count skin-like pixels using a simple RGB rule.
        # Skin tones usually have R > 95, G > 40, B > 20,
        # and R > G > B with moderate saturation.
        skin_like = 0
        for r, g, b in pixels:
            if (
                r > 95
                and g > 40
                and b > 20
                and r > g
                and g > b
                and (r - g) > 15
                and (r - b) > 15
            ):
                skin_like += 1

        skin_frac = skin_like / len(pixels)

        # Also detect very uniform/bright scenes that look like portraits
        # or selfies: low texture, bright, not much environmental clutter.
        stat = ImageStat.Stat(small)
        contrast = sum(stat.stddev) / 3
        mean = sum(stat.mean) / 3

        # Strong skin presence OR portrait-like appearance
        return skin_frac > 0.45 or (skin_frac > 0.30 and contrast < 25 and mean > 140)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Strict heuristic fallback
# ---------------------------------------------------------------------------
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Rising water": ["water", "flood", "river", "mud", "flow"],
    "Landslide": ["rock", "debris", "mud", "slope", "erosion"],
    "Blocked road": ["road", "asphalt", "vehicle", "tree", "debris"],
    "Cloudburst": ["cloud", "sky", "storm", "rain", "dark"],
}


def _heuristic_verify(raw: bytes, category: str) -> dict[str, Any]:
    """Strict local fallback when no vision API is configured.

    Rejects most non-disaster photos by requiring strong visual evidence:
    - very dark/murky scenes
    - high texture/contrast
    - low mean brightness
    - NOT face/skin-heavy
    """
    try:
        if _looks_like_face_or_skin(raw):
            return {
                "is_valid": False,
                "confidence": 0.0,
                "hazard_detected": "Rejected",
                "reason": "Image appears to contain a human face or skin-heavy scene. Only natural-disaster images are accepted.",
            }

        im = Image.open(io.BytesIO(raw)).convert("RGB")
        small = im.resize((64, 64))
        stat = ImageStat.Stat(small)
        pixels = list(small.getdata())

        mean = sum(stat.mean) / 3
        contrast = sum(stat.stddev) / 3
        dark_frac = sum(1 for p in pixels if sum(p) / 3 < 80) / len(pixels)
        murky_frac = sum(
            1 for p in pixels if abs(p[0] - p[2]) < 14 and p[1] < 130
        ) / len(pixels)
        texture = min(1.0, contrast / 60)

        score = max(
            0.0,
            min(
                100.0,
                18 + dark_frac * 38 + murky_frac * 26 + texture * 20 - mean * 0.14,
            ),
        )

        label = "Likely flood/landslide imagery" if score >= 80 else "Ambiguous" if score >= 58 else "Unlikely flood/landslide imagery"
        is_valid = score >= 80
        confidence = round(score / 100.0, 3)

        return {
            "is_valid": is_valid,
            "confidence": confidence,
            "hazard_detected": label,
            "reason": (
                "Heuristic demo signal — configure GROQ_API_KEY for AI Vision."
                if not os.getenv("GROQ_API_KEY")
                else "AI Vision verification."
            ),
        }
    except Exception as exc:  # pragma: no cover
        return {
            "is_valid": False,
            "confidence": 0.0,
            "hazard_detected": "Unknown",
            "reason": f"Image processing failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Strict Groq Vision integration
# ---------------------------------------------------------------------------
def classify_with_groq_vision(raw: bytes, category: str) -> dict[str, Any]:
    """Send the image to a Groq multimodal vision model and parse the result."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        logger.warning("GROQ_API_KEY is not configured; using heuristic vision fallback.")
        return {}

    try:
        import base64
        import json
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError

        mime = "image/jpeg"
        try:
            im = Image.open(io.BytesIO(raw))
            if im.format == "PNG":
                mime = "image/png"
            elif im.format in ("WEBP", "MPO"):
                mime = "image/webp"
        except Exception:
            pass

        b64 = base64.b64encode(raw).decode("utf-8")

        prompt = (
            "You are an extremely strict natural-disaster image verifier for a "
            "flood/landslide early-warning system. Your ONLY job is to decide if "
            "this image shows CLEAR, UNAMBIGUOUS evidence of a natural disaster. "
            "You must REJECT the image unless you are virtually certain it shows "
            "a genuine disaster scene.\n\n"
            f"Selected hazard category: '{category}'\n\n"
            "ABSOLUTELY REJECT if the image contains ANY of the following:\n"
            "- Human faces, people, selfies, group photos, portraits\n"
            "- Indoor scenes, rooms, offices, homes\n"
            "- Text screenshots, documents, memes, cartoons, drawings\n"
            "- Normal city/village views with no visible hazard\n"
            "- Clear sky, sunny weather, dry roads or fields\n"
            "- Vehicles on normal roads or parked normally\n"
            "- Animals, objects, or scenes unrelated to natural disasters\n\n"
            "ONLY ACCEPT if the image clearly shows one or more of:\n"
            "- Flood water, rising water, submerged roads or fields, water overflow\n"
            "- Landslide debris, fallen rocks, mudslides, eroded slopes\n"
            "- Roads blocked by natural debris, trees, or landslide material\n"
            "- Dark storm clouds, heavy rain, visible water accumulation\n"
            "- Swollen rivers or streams overflowing banks\n"
            "- Structural damage caused by natural hazards\n\n"
            "If there is ANY doubt, REJECT. Default to rejecting. "
            "Reply ONLY with compact JSON: "
            '{"is_valid": true/false, "confidence": 0.0-1.0, '
            '"hazard_detected": "short hazard label", "reason": "brief explanation"}'
        )

        payload = json.dumps({
            "model": "llama-3.2-90b-vision-preview",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                    ],
                }
            ],
            "max_tokens": 200,
        }).encode("utf-8")

        req = Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        content = body["choices"][0]["message"]["content"]
        start = content.find("{")
        end = content.rfind("}") + 1
        if start != -1 and end != -1:
            result = json.loads(content[start:end])
            result.setdefault("is_valid", False)
            result.setdefault("confidence", 0.0)
            result.setdefault("hazard_detected", "Unknown")
            result.setdefault("reason", "")
            return result
    except Exception as exc:
        logger.warning("Groq vision request failed: %s", exc)
    return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def verify_disaster_image(image_bytes: bytes, category: str) -> dict[str, Any]:
    """Verify that an uploaded image depicts a legitimate natural disaster.

    Uses strict criteria: only clearly visible flood, landslide, blocked-road,
    or storm/cloudburst evidence is accepted. Borderline or unrelated images
    are rejected.

    Tries the configured vision API first; falls back to the strict local
    heuristic so the prototype always returns a deterministic result.
    """
    # Pre-filter: reject face/skin-heavy images immediately
    if _looks_like_face_or_skin(image_bytes):
        return {
            "is_valid": False,
            "confidence": 0.0,
            "hazard_detected": "Rejected",
            "reason": "Image appears to contain a human face or selfie. Only natural-disaster images are accepted.",
        }

    vision = classify_with_groq_vision(image_bytes, category)
    if vision:
        logger.info("Groq vision result: %s", vision)
        # Require very high confidence for acceptance
        if vision.get("confidence", 0.0) < 0.85:
            vision["is_valid"] = False
            vision["reason"] = (
                vision.get("reason", "Low confidence.")
                + " Confidence below 85% threshold."
            )
        return vision
    logger.info("Groq vision unavailable; using local heuristic fallback.")
    return _heuristic_verify(image_bytes, category)
