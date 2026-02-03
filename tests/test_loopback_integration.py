from loopback.loopback import (
    FileUploader,
    LoopbackConfig,
    ToolImage,
    ToolResult,
    UploadedFile,
    VisionProvider,
    apply_loopback,
)


class FakeUploader(FileUploader):
    def __init__(self):
        self.uploaded = []

    def upload(self, image: ToolImage) -> UploadedFile:
        self.uploaded.append(image)
        return UploadedFile(file_id="file-1", mime_type=image.mime_type, size=len(image.data))


class FakeProvider(VisionProvider):
    def __init__(self):
        self.calls = []

    def send_followup(self, prompt, uploaded_files, images_base64):
        self.calls.append(
            {
                "prompt": prompt,
                "uploaded_files": uploaded_files,
                "images_base64": images_base64,
            }
        )
        return {"status": "ok"}


def test_apply_loopback_triggers_followup_with_image_payload():
    config = LoopbackConfig(enabled=True, max_images=1)
    tool_result = ToolResult(
        tool_name="generate_image",
        images=[ToolImage(mime_type="image/png", data=b"image-bytes")],
    )
    uploader = FakeUploader()
    provider = FakeProvider()

    decision = apply_loopback(
        config,
        tool_result,
        already_looped=False,
        model_supports_vision=True,
        uploader=uploader,
        provider=provider,
    )

    assert decision.should_loopback is True
    assert len(uploader.uploaded) == 1
    assert len(provider.calls) == 1
    assert provider.calls[0]["images_base64"][0] != ""
