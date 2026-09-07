# OpenCode Go MissingSessionID

## Direct call (no session header)
POST https://opencode.ai/zen/go/v1/chat/completions
Authorization: Bearer <key>
model: deepseek-v4-flash

→ HTTP 400
{"type":"error","error":{"type":"MissingSessionID","message":"Error from provider (Console Go): Request is missing x-opencode-session and cannot be routed efficiently. Please see https://opencode.ai/docs/go/#where-can-i-use-it"}}

## With header
x-opencode-session: <uuid>
User-Agent: ming-qa/1.0
→ HTTP 200

## Game config surface
runtime_llm.json / API channel only exposes: channel, base_url, model, api_key, timeout…
No default_headers / x-opencode-session injection in ming_sim.llm_model OpenAIChat construction.
