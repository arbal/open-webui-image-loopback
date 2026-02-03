# Operator Guide: Automatic Image Loopback

## Enable / Disable
### Pipeline install (deployable)
1) Open **Admin → Pipelines**.
2) Upload `pipelines/image_loopback_pipeline.py`.
3) Configure valves:
   - `enable=true`
   - `openwebui_base_url=http://localhost:8080` (or your base URL)
   - `openwebui_api_key=<admin token>`

### Pipeline valves (runtime settings)
- `enable=false` (default)
- `allowed_tools=generate_image`
- `allowed_mime_types=image/png,image/jpeg,image/webp`
- `max_bytes=8388608`
- `max_images=2`
- `auto_prompt=...`
- `allow_url_fetch=false`
- `openwebui_base_url=http://localhost:8080`
- `openwebui_api_key=` (can fall back to `OPENWEBUI_API_KEY` env var)

### Per-model (advanced)
If your Open WebUI deployment supports per-model advanced parameters for pipeline valves, apply overrides there so loopback can be enabled only for specific models.

## Recommended Defaults
- Enable only for `generate_image`
- Limit to 1-2 images
- Keep max size <= 8MB
- Do not allow URL fetching

## Troubleshooting Checklist
1) **No follow-up turn**
   - Check `enable=true` and `openwebui_api_key`
   - Verify the model supports vision
2) **Image not shown in history**
   - File upload failed (inspect server logs)
   - MIME type not allowlisted
3) **Follow-up missing image input**
   - Ensure provider adapter inserts base64 image data into the request
   - Confirm the model is a vision-capable Ollama model
4) **Infinite tool loops**
   - Confirm loopback marker is written (`loopback_done`)
   - Verify the follow-up message does not auto-trigger tool usage

## Disable for Specific Models
If a model is not vision-capable, disable loopback via model-level config or use a separate model profile without loopback enabled.
