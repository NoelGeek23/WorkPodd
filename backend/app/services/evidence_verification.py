from __future__ import annotations

import base64
import io
import re
from dataclasses import dataclass

MIN_IMAGE_WIDTH = 320
MIN_IMAGE_HEIGHT = 240
MIN_LAPLACIAN_VARIANCE = 35.0
MAX_RETRIES = 3
MIN_VIT_CONFIDENCE = 0.08
VIT_MODEL_ID = "google/vit-base-patch16-224"
VIT_TOP_K = 5

_vit_model = None
_vit_processor = None

# ImageNet-oriented keyword hints for ViT top-label sanity checks.
PRODUCT_CLASSIFICATION_HINTS: dict[str, dict[str, set[str]]] = {
    "yoga mat": {
        "expected": {"mat", "yoga", "gym", "exercise", "sleeping", "towel", "blanket", "rug", "carpet"},
        "forbidden": {"baseball", "bat", "racket", "knife", "scissor", "tennis", "glove", "ballplayer"},
    },
    "hoodie": {
        "expected": {"sweater", "jersey", "coat", "jacket", "shirt", "pullover", "cardigan", "sweatshirt"},
        "forbidden": {"baseball", "bat", "racket", "laptop", "notebook", "phone", "cellular"},
    },
    "headphones": {
        "expected": {
            "headphone",
            "earphone",
            "headset",
            "ipod",
            "microphone",
            "radio",
            "speaker",
            "earpiece",
        },
        "forbidden": {"baseball", "bat", "racket", "ball", "skateboard", "surfboard", "ballplayer"},
    },
    "lamp": {
        "expected": {"lamp", "light", "chandelier", "candle", "vase", "table", "desk", "clock"},
        "forbidden": {"baseball", "bat", "racket", "ball", "ballplayer"},
    },
    "mask": {
        "expected": {"mask", "face", "bandage", "sleep", "pillow", "towel"},
        "forbidden": {"baseball", "bat", "laptop", "notebook", "phone", "ball"},
    },
    "default": {
        "expected": set(),
        "forbidden": {"baseball", "bat", "racket", "knife", "scissor", "ballplayer"},
    },
}


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


def _load_image(image_bytes: bytes):
    import numpy as np
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return image, np.array(image), image.size


def _blur_score(gray) -> float:
    import cv2

    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _get_vit_classifier():
    global _vit_model, _vit_processor
    if _vit_model is None or _vit_processor is None:
        from transformers import ViTForImageClassification, ViTImageProcessor

        _vit_processor = ViTImageProcessor.from_pretrained(VIT_MODEL_ID)
        _vit_model = ViTForImageClassification.from_pretrained(VIT_MODEL_ID)
        _vit_model.eval()
    return _vit_processor, _vit_model


def _classify_image(image) -> list[tuple[str, float]]:
    """Classify an image with a Vision Transformer (ImageNet labels)."""
    try:
        import torch
    except ImportError:
        return []

    try:
        processor, model = _get_vit_classifier()
    except Exception:
        return []

    inputs = processor(images=image, return_tensors="pt")
    with torch.no_grad():
        logits = model(**inputs).logits
    probabilities = torch.nn.functional.softmax(logits, dim=-1)[0]
    scores, indices = torch.topk(probabilities, min(VIT_TOP_K, probabilities.shape[-1]))
    id2label = model.config.id2label
    return [
        (str(id2label[int(index)]), float(score))
        for score, index in zip(scores, indices)
        if float(score) >= MIN_VIT_CONFIDENCE
    ]


def _product_hints(product_name: str) -> dict[str, set[str]]:
    lowered = product_name.lower()
    for key, hints in PRODUCT_CLASSIFICATION_HINTS.items():
        if key != "default" and key in lowered:
            return hints
    return PRODUCT_CLASSIFICATION_HINTS["default"]


def _label_matches_keywords(label: str, keywords: set[str]) -> bool:
    lowered = label.lower()
    return any(keyword in lowered for keyword in keywords)


def _classification_conflict(product_name: str, predictions: list[tuple[str, float]]) -> str | None:
    if not predictions:
        return None

    hints = _product_hints(product_name)
    for label, score in predictions:
        if score < MIN_VIT_CONFIDENCE:
            continue
        if _label_matches_keywords(label, hints["forbidden"]):
            return label

    expected = hints.get("expected", set())
    if not expected:
        return None

    top_predictions = predictions[:3]
    if any(_label_matches_keywords(label, expected) for label, _ in top_predictions):
        return None

    strongest_label, strongest_score = max(top_predictions, key=lambda item: item[1])
    if strongest_score >= 0.15:
        return strongest_label
    return None


def verify_evidence_image(
    *,
    product_name: str,
    data_base64: str,
    attempt_number: int,
) -> EvidenceVerificationResult:
    retries_remaining = max(0, MAX_RETRIES - attempt_number)
    try:
        image_bytes = _decode_image(data_base64)
        image, image_array, (width, height) = _load_image(image_bytes)
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
    classified = _classify_image(image)
    classified_labels = [label for label, _ in classified]

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

    conflict = _classification_conflict(product_name, classified)
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
