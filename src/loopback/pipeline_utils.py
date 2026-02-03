"""Utilities for Open WebUI pipeline image loopback."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence


@dataclass
class ExtractedImage:
    mime_type: str
    data: bytes
    source: str


def _safe_json_loads(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _maybe_decode_base64(data: str) -> Optional[bytes]:
    try:
        return base64.b64decode(data)
    except (ValueError, TypeError):
        return None


def _iter_dicts(obj: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_dicts(item)


def extract_tool_images(
    body: Dict[str, Any],
    allowed_tools: Sequence[str],
    allow_url_fetch: bool,
    max_images: int,
    allowed_mime_types: Sequence[str],
) -> List[ExtractedImage]:
    images: List[ExtractedImage] = []
    for obj in _iter_dicts(body):
        tool_name = obj.get("tool_name") or obj.get("tool") or obj.get("name")
        if tool_name not in allowed_tools:
            continue
        raw_images = obj.get("images") or obj.get("image") or obj.get("output", {}).get("images")
        if not raw_images:
            continue
        if isinstance(raw_images, str):
            raw_images = _safe_json_loads(raw_images) or []
        if isinstance(raw_images, dict):
            raw_images = [raw_images]
        for image in raw_images:
            if not isinstance(image, dict):
                continue
            mime_type = image.get("mime_type") or image.get("content_type") or "image/png"
            if mime_type not in allowed_mime_types:
                continue
            data = None
            if "b64_json" in image:
                data = _maybe_decode_base64(image["b64_json"])
            elif "data" in image:
                data = _maybe_decode_base64(image["data"])
            elif "base64" in image:
                data = _maybe_decode_base64(image["base64"])
            elif "url" in image and allow_url_fetch:
                import requests

                response = requests.get(image["url"], timeout=10)
                response.raise_for_status()
                data = response.content
            if data:
                images.append(ExtractedImage(mime_type=mime_type, data=data, source=tool_name))
            if len(images) >= max_images:
                return images
    return images
