from __future__ import annotations

import base64
import io
import json
import os
import re
from dataclasses import dataclass

import httpx

MIN_IMAGE_WIDTH = 320
MIN_IMAGE_HEIGHT = 240
MIN_LAPLACIAN_VARIANCE = 35.0
MAX_RETRIES = 3


@dataclass
class EvidenceVerificationResult:
    passed: bool
    issue: str | None
    customer_message: str
    detected_objects: list[str]
    width: int
    height: int
    blur_score: float
    retries_remaining: int


def _decode_image(data_base64: str) -> bytes:
    payload = data_base64.split(",", 1)[-1]
    return base64.b64decode(payload)


def _image_data_url(data_base64: str) -> str:
    if data_base64.startswith("data:"):
        return data_base64
    return f"data:image/jpeg;base64,{data_base64.split(',', 1)[-1]}"


def _load_image(image_bytes: bytes):
    import numpy as np
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return image, np.array(image), image.size


def _blur_score(gray) -> float:
    import cv2

    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


async def _classify_image_with_openai(
    data_base64: str,
    product_name: str,
) -> tuple[list[str], str | None]:
    """Classify image contents and check whether they match the expected product."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return [], None

    model = os.getenv("OPENAI_VISION_MODEL", os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"))
    prompt = (
        f"You are verifying return evidence photos for an e-commerce support agent.\n"
        f"The customer claims they are returning: {product_name}\n\n"
        "Analyze the image and respond with JSON only:\n"
        "{\n"
        '  "detected_objects": ["list", "of", "visible", "items"],\n'
        '  "matches_product": true or false,\n'
        '  "mismatch_label": "short label for what the image actually shows, or null if it matches"\n'
        "}\n\n"
        "Set matches_product to true if the image plausibly shows the claimed product, "
        "its packaging, or relevant damage.\n"
        "Set matches_product to false only when the image clearly shows a different unrelated item."
    )
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 200,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": _image_data_url(data_base64), "detail": "low"},
                    },
                ],
            }
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            content = str(response.json()["choices"][0]["message"]["content"]).strip()
            parsed = json.loads(content)
    except (httpx.HTTPError, KeyError, IndexError, ValueError, json.JSONDecodeError):
        return [], None

    detected_objects = [str(item) for item in parsed.get("detected_objects", []) if item]
    if parsed.get("matches_product", True):
        return detected_objects, None

    conflict = parsed.get("mismatch_label")
    if conflict:
        return detected_objects, str(conflict)
    if detected_objects:
        return detected_objects, detected_objects[0]
    return detected_objects, "unrelated item"


async def verify_evidence_image(
    *,
    product_name: str,
    data_base64: str,
    attempt_number: int,
) -> EvidenceVerificationResult:
    retries_remaining = max(0, MAX_RETRIES - attempt_number)
    try:
        image_bytes = _decode_image(data_base64)
        _image, image_array, (width, height) = _load_image(image_bytes)
    except Exception:
        return EvidenceVerificationResult(
            passed=False,
            issue="invalid_image",
            customer_message=(
                "I couldn't read that image. Please upload a clear JPG or PNG of the product."
            ),
            detected_objects=[],
            width=0,
            height=0,
            blur_score=0.0,
            retries_remaining=retries_remaining,
        )

    import cv2

    gray = cv2.cvtColor(image_array, cv2.COLOR_RGB2GRAY)
    blur = _blur_score(gray)
    classified_labels, conflict = await _classify_image_with_openai(data_base64, product_name)

    if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
        return EvidenceVerificationResult(
            passed=False,
            issue="low_resolution",
            customer_message=(
                f"The image resolution is too low ({width}x{height}). "
                "Please upload a clearer, higher-resolution photo."
                + (
                    f" You have {retries_remaining} attempt(s) left."
                    if retries_remaining
                    else " This will be escalated for manual review."
                )
            ),
            detected_objects=classified_labels,
            width=width,
            height=height,
            blur_score=blur,
            retries_remaining=retries_remaining,
        )

    if blur < MIN_LAPLACIAN_VARIANCE:
        return EvidenceVerificationResult(
            passed=False,
            issue="blurry_image",
            customer_message=(
                "The image looks blurry. Please upload a sharper photo of the product."
                + (
                    f" You have {retries_remaining} attempt(s) left."
                    if retries_remaining
                    else " This will be escalated for manual review."
                )
            ),
            detected_objects=classified_labels,
            width=width,
            height=height,
            blur_score=blur,
            retries_remaining=retries_remaining,
        )

    if conflict:
        return EvidenceVerificationResult(
            passed=False,
            issue="product_mismatch",
            customer_message=(
                f"The uploaded image doesn't appear to match {product_name} "
                f"(classified as: {conflict}). Please upload a photo of the correct item."
                + (
                    f" You have {retries_remaining} attempt(s) left."
                    if retries_remaining
                    else " This will be escalated for manual review."
                )
            ),
            detected_objects=classified_labels,
            width=width,
            height=height,
            blur_score=blur,
            retries_remaining=retries_remaining,
        )

    return EvidenceVerificationResult(
        passed=True,
        issue=None,
        customer_message="Image verification passed.",
        detected_objects=classified_labels,
        width=width,
        height=height,
        blur_score=blur,
        retries_remaining=retries_remaining,
    )


def normalize_product_names(product_names: str) -> str:
    return re.sub(r"\s+", " ", product_names or "Order items").strip()
