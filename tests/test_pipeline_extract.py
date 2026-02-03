from loopback.pipeline_utils import extract_tool_images


def test_extract_tool_images_from_tool_output():
    body = {
        "tool_results": [
            {
                "tool_name": "generate_image",
                "images": [
                    {
                        "mime_type": "image/png",
                        "b64_json": "aW1hZ2UtYnl0ZXM=",
                    }
                ],
            }
        ]
    }

    images = extract_tool_images(
        body=body,
        allowed_tools=["generate_image"],
        allow_url_fetch=False,
        max_images=2,
        allowed_mime_types=["image/png"],
    )

    assert len(images) == 1
    assert images[0].data == b"image-bytes"
    assert images[0].mime_type == "image/png"
