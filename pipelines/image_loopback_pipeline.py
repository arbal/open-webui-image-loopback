"""
title: Automatic Image Loopback Pipeline
author: OpenAI Codex
date: 2026-02-03
version: 0.2.0
license: MIT
description: Upload tool-generated images and trigger a follow-up vision turn automatically.
requirements: pydantic, aiohttp
"""

from __future__ import annotations

import os
import base64
import json
import asyncio
from typing import Any, Dict, Iterable, Optional, Sequence

from pydantic import BaseModel, Field

class ExtractedImage:
    def __init__(self, mime_type: str, data: bytes, source: str) -> None:
        self.mime_type = mime_type
        self.data = data
        self.source = source


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


async def extract_tool_images(
    body: Dict[str, Any],
    allowed_tools: Sequence[str],
    allow_url_fetch: bool,
    max_images: int,
    allowed_mime_types: Sequence[str],
) -> list[ExtractedImage]:
    images: list[ExtractedImage] = []

    # Pre-parse any stringified JSON tool calls if possible
    # We will search the whole body but we also specifically look inside tool_calls

    for obj in _iter_dicts(body):
        tool_name = obj.get("tool_name") or obj.get("tool") or obj.get("name")
        if tool_name not in allowed_tools:
            continue

        # Look in the arguments if it's a tool_call
        arguments = obj.get("arguments")
        if isinstance(arguments, str):
            args_obj = _safe_json_loads(arguments) or {}
            obj.update(args_obj)
        elif isinstance(arguments, dict):
            obj.update(arguments)

        raw_images = obj.get("images") or obj.get("image") or obj.get("output", {}).get("images")

        # Sometime the result itself is a stringified JSON containing images
        if not raw_images and "content" in obj and isinstance(obj["content"], str):
            content_obj = _safe_json_loads(obj["content"])
            if content_obj and isinstance(content_obj, dict):
                 raw_images = content_obj.get("images") or content_obj.get("image")

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
                import aiohttp
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(image["url"], timeout=10) as response:
                            response.raise_for_status()
                            data = await response.read()
                except Exception as e:
                    print(f"Error fetching image from URL: {e}")
                    continue

            if data:
                images.append(ExtractedImage(mime_type=mime_type, data=data, source=tool_name))
            if len(images) >= max_images:
                return images
    return images


class Pipeline:
    class Valves(BaseModel):
        pipelines: list[str] = Field(default_factory=list)
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

        images = await extract_tool_images(
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

        import aiohttp

        async with aiohttp.ClientSession() as session:
            for image in filtered:
                form_data = aiohttp.FormData()
                form_data.add_field(
                    'file',
                    image.data,
                    filename='image.png',
                    content_type=image.mime_type
                )

                try:
                    async with session.post(
                        f"{self.valves.openwebui_base_url}/api/v1/files/?process=false&process_in_background=false",
                        headers={"Authorization": f"Bearer {api_key}"},
                        data=form_data,
                        timeout=30,
                    ) as response:
                        response.raise_for_status()
                        payload = await response.json()
                        file_id = payload.get("id") or payload.get("file_id")
                        if file_id:
                            uploaded_file_ids.append(file_id)
                except Exception as e:
                    print(f"Error uploading image: {e}")

            if not uploaded_file_ids:
                return body

            chat_id = body.get("chat_id") or body.get("conversation_id")
            messages = body.get("messages", [])

            # OpenWebUI and OpenAI expect files to be tied to the message content or as a direct property
            # We add it as an array of files in the message, and set loopback_done to True
            followup_message = {
                "role": "user",
                "content": self.valves.auto_prompt,
                "metadata": {"loopback_done": True},
                "files": [{"id": file_id} for file_id in uploaded_file_ids],
            }
            new_messages = [*messages, followup_message]

            followup_payload = {
                "model": body.get("model"),
                "messages": new_messages,
                "metadata": {"loopback_done": True},
            }
            if chat_id:
                followup_payload["chat_id"] = chat_id

            # Fire and forget the follow-up request so we don't block the current response stream
            asyncio.create_task(self._send_followup(api_key, followup_payload))

        return body

    async def _send_followup(self, api_key: str, followup_payload: dict):
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.valves.openwebui_base_url}/api/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=followup_payload,
                    timeout=60,
                ) as response:
                    response.raise_for_status()
        except Exception as e:
            print(f"Error sending follow-up completion: {e}")
