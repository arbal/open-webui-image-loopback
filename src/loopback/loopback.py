"""Image loopback orchestration for Open WebUI tool results."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from typing import Iterable, List, Mapping, Optional, Sequence


DEFAULT_FOLLOWUP_PROMPT = (
    "Analyze the attached generated image. If it contains text, transcribe it. "
    "If it contains people, describe posture, expressions, and notable details. "
    "Then continue the task."
)


@dataclass(frozen=True)
class LoopbackConfig:
    enabled: bool = False
    allowed_tools: Sequence[str] = ("generate_image",)
    allowed_mime_types: Sequence[str] = (
        "image/png",
        "image/jpeg",
        "image/webp",
    )
    max_bytes: int = 8 * 1024 * 1024
    max_images: int = 2
    auto_followup_prompt: str = DEFAULT_FOLLOWUP_PROMPT
    allow_url_fetch: bool = False

    @staticmethod
    def from_env() -> "LoopbackConfig":
        enabled = os.getenv("IMAGE_LOOPBACK_ENABLE", "false").lower() == "true"
        allowed_tools = tuple(
            tool.strip()
            for tool in os.getenv("IMAGE_LOOPBACK_ALLOWED_TOOLS", "generate_image").split(","
            )
            if tool.strip()
        )
        allowed_mime_types = tuple(
            item.strip()
            for item in os.getenv(
                "IMAGE_LOOPBACK_ALLOWED_MIME_TYPES", "image/png,image/jpeg,image/webp"
            ).split(",")
            if item.strip()
        )
        max_bytes = int(os.getenv("IMAGE_LOOPBACK_MAX_BYTES", str(8 * 1024 * 1024)))
        max_images = int(os.getenv("IMAGE_LOOPBACK_MAX_IMAGES", "2"))
        auto_prompt = os.getenv("IMAGE_LOOPBACK_AUTO_PROMPT", DEFAULT_FOLLOWUP_PROMPT)
        allow_url_fetch = os.getenv("IMAGE_LOOPBACK_ALLOW_URL_FETCH", "false").lower() == "true"
        return LoopbackConfig(
            enabled=enabled,
            allowed_tools=allowed_tools,
            allowed_mime_types=allowed_mime_types,
            max_bytes=max_bytes,
            max_images=max_images,
            auto_followup_prompt=auto_prompt,
            allow_url_fetch=allow_url_fetch,
        )


@dataclass
class ToolImage:
    mime_type: str
    data: bytes
    source: str = "tool"


@dataclass
class ToolResult:
    tool_name: str
    images: List[ToolImage] = field(default_factory=list)
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass
class UploadedFile:
    file_id: str
    mime_type: str
    size: int


@dataclass
class LoopbackDecision:
    should_loopback: bool
    reason: str
    followup_prompt: Optional[str] = None
    uploaded_files: Sequence[UploadedFile] = ()


class LoopbackError(RuntimeError):
    """Raised for loopback processing issues."""


def should_loopback(
    config: LoopbackConfig,
    tool_result: ToolResult,
    already_looped: bool,
    model_supports_vision: bool,
) -> LoopbackDecision:
    if not config.enabled:
        return LoopbackDecision(False, "loopback disabled")
    if already_looped:
        return LoopbackDecision(False, "loopback already performed")
    if tool_result.tool_name not in config.allowed_tools:
        return LoopbackDecision(False, "tool not allowlisted")
    if not model_supports_vision:
        return LoopbackDecision(False, "model lacks vision support")
    if not tool_result.images:
        return LoopbackDecision(False, "no images in tool result")
    return LoopbackDecision(True, "eligible", followup_prompt=config.auto_followup_prompt)


def filter_images(config: LoopbackConfig, images: Iterable[ToolImage]) -> List[ToolImage]:
    filtered: List[ToolImage] = []
    for image in images:
        if image.mime_type not in config.allowed_mime_types:
            continue
        if len(image.data) > config.max_bytes:
            continue
        filtered.append(image)
        if len(filtered) >= config.max_images:
            break
    return filtered


def encode_base64_images(images: Sequence[ToolImage]) -> List[str]:
    return [base64.b64encode(image.data).decode("utf-8") for image in images]


class FileUploader:
    """Interface for registering files in Open WebUI."""

    def upload(self, image: ToolImage) -> UploadedFile:
        raise NotImplementedError


class VisionProvider:
    """Interface for sending follow-up vision requests."""

    def send_followup(
        self,
        prompt: str,
        uploaded_files: Sequence[UploadedFile],
        images_base64: Sequence[str],
    ) -> Mapping[str, str]:
        raise NotImplementedError


LOOPBACK_MARKER_KEY = "loopback_done"


def apply_loopback(
    config: LoopbackConfig,
    tool_result: ToolResult,
    already_looped: bool,
    model_supports_vision: bool,
    uploader: FileUploader,
    provider: VisionProvider,
) -> LoopbackDecision:
    decision = should_loopback(config, tool_result, already_looped, model_supports_vision)
    if not decision.should_loopback:
        return decision

    filtered = filter_images(config, tool_result.images)
    if not filtered:
        return LoopbackDecision(False, "no images after filtering")

    uploaded_files: List[UploadedFile] = []
    for image in filtered:
        uploaded_files.append(uploader.upload(image))

    images_base64 = encode_base64_images(filtered)
    provider.send_followup(decision.followup_prompt or config.auto_followup_prompt, uploaded_files, images_base64)

    return LoopbackDecision(
        True,
        "loopback applied",
        followup_prompt=decision.followup_prompt,
        uploaded_files=uploaded_files,
    )
