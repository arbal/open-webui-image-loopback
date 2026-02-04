"""Image loopback orchestration for Open WebUI tool results."""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass, field
from typing import Iterable, List, Mapping, Optional, Sequence


DEFAULT_FOLLOWUP_PROMPT = (
    "Analyze the attached generated image. If it contains text, transcribe it. "
    "If it contains people, describe posture, expressions, and notable details. "
    "Then continue the task."
)

LOGGER_NAME = "loopback"
_logger = logging.getLogger(LOGGER_NAME)
_logger.addHandler(logging.NullHandler())


def _configure_logging(log_level: str) -> None:
    if not log_level:
        return
    normalized = log_level.strip().upper()
    if normalized in {"OFF", "NONE", "DISABLED", "FALSE", "0"}:
        _logger.disabled = True
        return
    _logger.disabled = False
    _logger.setLevel(normalized)


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
    log_level: str = "WARNING"

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
        log_level = os.getenv("IMAGE_LOOPBACK_LOG_LEVEL", "WARNING")
        return LoopbackConfig(
            enabled=enabled,
            allowed_tools=allowed_tools,
            allowed_mime_types=allowed_mime_types,
            max_bytes=max_bytes,
            max_images=max_images,
            auto_followup_prompt=auto_prompt,
            allow_url_fetch=allow_url_fetch,
            log_level=log_level,
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
    _configure_logging(config.log_level)
    _logger.debug(
        "Evaluating loopback: enabled=%s already_looped=%s tool=%s model_supports_vision=%s images=%d",
        config.enabled,
        already_looped,
        tool_result.tool_name,
        model_supports_vision,
        len(tool_result.images),
    )
    if not config.enabled:
        reason = "loopback disabled"
        _logger.info("Loopback skipped: %s", reason)
        return LoopbackDecision(False, reason)
    if already_looped:
        reason = "loopback already performed"
        _logger.info("Loopback skipped: %s", reason)
        return LoopbackDecision(False, reason)
    if tool_result.tool_name not in config.allowed_tools:
        reason = "tool not allowlisted"
        _logger.info("Loopback skipped: %s", reason)
        return LoopbackDecision(False, reason)
    if not model_supports_vision:
        reason = "model lacks vision support"
        _logger.info("Loopback skipped: %s", reason)
        return LoopbackDecision(False, reason)
    if not tool_result.images:
        reason = "no images in tool result"
        _logger.info("Loopback skipped: %s", reason)
        return LoopbackDecision(False, reason)
    _logger.info("Loopback eligible for tool=%s with %d images", tool_result.tool_name, len(tool_result.images))
    return LoopbackDecision(True, "eligible", followup_prompt=config.auto_followup_prompt)


def filter_images(config: LoopbackConfig, images: Iterable[ToolImage]) -> List[ToolImage]:
    _configure_logging(config.log_level)
    image_list = list(images)
    filtered: List[ToolImage] = []
    for image in image_list:
        if image.mime_type not in config.allowed_mime_types:
            _logger.debug("Skipping image due to mime type: %s", image.mime_type)
            continue
        if len(image.data) > config.max_bytes:
            _logger.debug(
                "Skipping image due to size: %d bytes (max %d)",
                len(image.data),
                config.max_bytes,
            )
            continue
        filtered.append(image)
        _logger.debug("Accepted image %d/%d", len(filtered), config.max_images)
        if len(filtered) >= config.max_images:
            break
    _logger.info("Filtered %d images from %d candidates", len(filtered), len(image_list))
    return filtered


def encode_base64_images(images: Sequence[ToolImage]) -> List[str]:
    _logger.debug("Encoding %d images to base64", len(images))
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
    _configure_logging(config.log_level)
    decision = should_loopback(config, tool_result, already_looped, model_supports_vision)
    if not decision.should_loopback:
        return decision

    filtered = filter_images(config, tool_result.images)
    if not filtered:
        reason = "no images after filtering"
        _logger.info("Loopback skipped: %s", reason)
        return LoopbackDecision(False, reason)

    uploaded_files: List[UploadedFile] = []
    for image in filtered:
        _logger.debug("Uploading image from source=%s mime_type=%s bytes=%d", image.source, image.mime_type, len(image.data))
        uploaded_files.append(uploader.upload(image))

    images_base64 = encode_base64_images(filtered)
    prompt = decision.followup_prompt or config.auto_followup_prompt
    _logger.info(
        "Sending followup prompt with %d files and %d base64 images",
        len(uploaded_files),
        len(images_base64),
    )
    provider.send_followup(prompt, uploaded_files, images_base64)

    _logger.info("Loopback applied successfully with %d uploaded files", len(uploaded_files))
    return LoopbackDecision(
        True,
        "loopback applied",
        followup_prompt=decision.followup_prompt,
        uploaded_files=uploaded_files,
    )
