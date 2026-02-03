"""
title: Automatic Image Loopback Pipeline
author: OpenAI Codex
date: 2026-02-03
version: 0.2.0
license: MIT
description: Upload tool-generated images and trigger a follow-up vision turn automatically.
requirements: pydantic, requests
"""

from __future__ import annotations

import os
import base64
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

from pydantic import BaseModel

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


class Pipeline:
    class Valves(BaseModel):
        pipelines: List[str] = []
        priority: int = 0
        enable: bool = False
        allowed_tools: str = "generate_image"
        allowed_mime_types: str = "image/png,image/jpeg,image/webp"
        max_bytes: int = 8 * 1024 * 1024
        max_images: int = 2
        auto_prompt: str = (
            "Analyze the attached generated image. If it contains text, transcribe it. "
            "If it contains people, describe posture, expressions, and notable details. "
            "Then continue the task."
        )
        allow_url_fetch: bool = False
        openwebui_base_url: str = "http://localhost:8080"
        openwebui_api_key: str = ""

    def __init__(self):
        self.type = "filter"
        self.name = "Automatic Image Loopback"
        self.valves = self.Valves(
            **{
                "pipelines": ["*"],
            }
        )

    async def inlet(self, body: dict, user: Optional[dict] = None) -> dict:
        return body

    async def outlet(self, body: dict, user: Optional[dict] = None) -> dict:
        if not self.valves.enable:
            return body

        metadata = body.get("metadata") or {}
        if metadata.get("loopback_done"):
            return body

        allowed_tools = [item.strip() for item in self.valves.allowed_tools.split(",") if item.strip()]
        allowed_mime_types = [
            item.strip() for item in self.valves.allowed_mime_types.split(",") if item.strip()
        ]
        images = extract_tool_images(
            body=body,
            allowed_tools=allowed_tools,
            allow_url_fetch=self.valves.allow_url_fetch,
            max_images=self.valves.max_images,
            allowed_mime_types=allowed_mime_types,
        )
        if not images:
            return body

        filtered = [image for image in images if len(image.data) <= self.valves.max_bytes]
        if not filtered:
            return body

        api_key = self.valves.openwebui_api_key or os.getenv("OPENWEBUI_API_KEY", "")
        if not api_key:
            return body

        uploaded_file_ids = []
        for image in filtered:
            files = {"file": ("image", image.data, image.mime_type)}
            import requests

            response = requests.post(
                f"{self.valves.openwebui_base_url}/api/v1/files/?process=false&process_in_background=false",
                headers={"Authorization": f"Bearer {api_key}"},
                files=files,
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            file_id = payload.get("id") or payload.get("file_id")
            if file_id:
                uploaded_file_ids.append(file_id)

        if not uploaded_file_ids:
            return body

        chat_id = body.get("chat_id") or body.get("conversation_id")
        messages = body.get("messages", [])
        followup_message = {
            "role": "user",
            "content": self.valves.auto_prompt,
            "metadata": {"loopback_done": True},
        }
        new_messages = [*messages, followup_message]
        followup_payload = {
            "model": body.get("model"),
            "messages": new_messages,
            "files": [{"id": file_id} for file_id in uploaded_file_ids],
            "metadata": {"loopback_done": True},
        }
        if chat_id:
            followup_payload["chat_id"] = chat_id

        import requests

        requests.post(
            f"{self.valves.openwebui_base_url}/api/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=followup_payload,
            timeout=60,
        )
        return body
