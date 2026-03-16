import pytest
import asyncio
from pipelines.image_loopback_pipeline import extract_tool_images

@pytest.mark.asyncio
async def test_extract_tool_images_with_arguments():
    body = {
        "tool_results": [
            {
                "tool_name": "generate_image",
                "arguments": '{"images": [{"mime_type": "image/png", "b64_json": "aW1hZ2UtYnl0ZXM="}]}'
            }
        ]
    }
    images = await extract_tool_images(
        body=body,
        allowed_tools=["generate_image"],
        allow_url_fetch=False,
        max_images=2,
        allowed_mime_types=["image/png"],
    )
    assert len(images) == 1
    assert images[0].data == b"image-bytes"
    assert images[0].mime_type == "image/png"

@pytest.mark.asyncio
async def test_extract_tool_images_with_content():
    body = {
        "tool_results": [
            {
                "tool_name": "generate_image",
                "content": '{"images": [{"mime_type": "image/png", "b64_json": "aW1hZ2UtYnl0ZXM="}]}'
            }
        ]
    }
    images = await extract_tool_images(
        body=body,
        allowed_tools=["generate_image"],
        allow_url_fetch=False,
        max_images=2,
        allowed_mime_types=["image/png"],
    )
    assert len(images) == 1
    assert images[0].data == b"image-bytes"
    assert images[0].mime_type == "image/png"
