# Automatic Image Loopback (Option #3: backend/pipeline)

## Priority Table
| Priority | Work Item | Rationale |
| --- | --- | --- |
| P0 | Repo reconnaissance and hook selection | Ensure loopback runs for Default + Native tool calling. |
| P0 | Loopback gating + marker | Prevent infinite recursion and allow secure defaults. |
| P0 | File registration + follow-up vision call | Provide seamless image attachment and next-turn vision input. |
| P1 | Unit + integration tests | Prove gating + payload assembly. |
| P1 | Operator docs + demo | Enable safe rollout and verification. |
| P2 | Optional URL fetch support | Explicitly disabled by default for SSRF safety. |

## Implementation Checklist
- [x] Step 0: Identify tool execution and message attachment flow (documented below).
- [x] Step 1: Choose Path 2 (backend/pipeline hook) to guarantee Native mode coverage.
- [x] Step 2: Implement loopback logic, gating, marker, and follow-up dispatch.
- [x] Step 3: Add unit test + integration-ish harness.
- [x] Step 4: Add operator documentation + demo recipe.

## Strategy (Path 1: Deployable pipeline)
To make this feature deployable without forking Open WebUI, this implementation ships a **filter pipeline** that can be uploaded via Admin → Pipelines. The pipeline watches tool results on the outlet path and then calls Open WebUI APIs to:
1) upload the image
2) attach the file to the chat
3) trigger an automatic follow-up turn with vision input

This keeps deployment low-friction while still covering Default + Native tool calling because the pipeline runs on the backend request/response path, not the UI.

## Data Flow (Sequence)
1) **Tool execution completes** with `generate_image` result, including bytes or base64 images.
2) **Loopback gating** runs:
   - feature flag + allowlists
   - model vision capability check
   - loopback marker not set
3) **Upload/attach**:
   - binary image is registered as a file (same path as user uploads)
   - conversation receives a synthetic attachment entry so the image shows in the UI
4) **Follow-up**:
   - system triggers a second model call
   - follow-up user message uses a prompt template
   - attached file reference is included so provider adds base64 vision inputs
5) **Marker set**:
   - chat metadata marks loopback as completed, preventing recursion

## State Machine
```
[Tool Result Received]
        |
        v
[Eligible?] --no--> [Return tool output only]
        |
       yes
        v
[Register File + Attach] -> [Trigger Follow-up] -> [Mark Loopback Done]
```

## Infinite Loop Prevention
- A **loopback marker** (`loopback_done`) is stored on the chat turn metadata.
- The follow-up request checks this marker and the tool allowlist.
- Loopback is only triggered when a tool explicitly returns an image; the follow-up user message does **not** invoke the tool unless the user asks again.

## Default vs Native Tool Calling
- **Default mode**: tool results appear in the response body; the pipeline detects the tool output and triggers loopback.
- **Native mode**: the backend still returns tool results; the pipeline runs in the outlet path and therefore still sees the tool output.

## Security Notes
- **SSRF**: URL fetching is **off by default**; only tool-provided bytes are accepted unless explicitly allowed.
- **Auth**: file uploads use the same backend flow as user uploads so auth and ACLs remain intact.
- **Storage**: no duplicate uploads when possible; reuse existing file IDs or log and skip loopback if upload fails.

## Provider: Ollama Vision Input
- Uploaded file bytes are read and base64-encoded.
- For Ollama, base64 strings are passed in the `images` array, alongside the follow-up message.
- This ensures the model receives images as **actual vision input**, not URLs.

## Follow-up Prompt Template
Default:
> "Analyze the attached generated image. If it contains text, transcribe it. If it contains people, describe posture, expressions, and notable details. Then continue the task."

Configurable via the pipeline `auto_prompt` valve.

## Deployment (Pipeline)
1) Upload `pipelines/image_loopback_pipeline.py` in **Admin → Pipelines**.
2) Set valves: `enable=true`, `openwebui_base_url`, and `openwebui_api_key`.
3) Ensure the target model is vision-capable (e.g., `qwen3-vl`).
