# Demo Recipe: Automatic Image Loopback

> Assumes Open WebUI is running at `http://localhost:8080` and the pipeline is enabled.

## 0) Install the pipeline
1) Open **Admin → Pipelines**.
2) Upload `pipelines/image_loopback_pipeline.py`.
3) Set valves:
   - `enable=true`
   - `openwebui_base_url=http://localhost:8080`
   - `openwebui_api_key=$OPENWEBUI_TOKEN`

## 1) Trigger generate_image tool
```bash
curl -X POST "http://localhost:8080/api/chat/completions" \
  -H "Authorization: Bearer $OPENWEBUI_TOKEN" \
  -H "Content-Type: application/json" \
  -d '/* payload that triggers generate_image */'
```

## 2) Observe automatic follow-up
- The chat history should show the generated image as an attachment.
- The assistant should immediately continue with a vision-aware response.

## 3) Ollama vision payload expectation
The follow-up request sent to Ollama should contain:
```json
{
  "model": "qwen3-vl",
  "messages": [
    {"role": "user", "content": "Analyze the attached generated image..."}
  ],
  "images": ["<base64-image-data>"]
}
```
