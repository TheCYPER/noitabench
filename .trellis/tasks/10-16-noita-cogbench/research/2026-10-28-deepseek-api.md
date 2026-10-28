# Research: DeepSeek official API (OpenAI-compatible Chat Completions)

- **Query**: Facts needed to run the NoitaBench harness against DeepSeek's official API through `python/noitabench/harness/adapters/openai_adapter.py` (base URL, model ids, prices, tool calling, thinking mode, usage fields, rejected params, images, errors).
- **Scope**: external (DeepSeek docs), plus a short factual cross-reference to the adapter
- **Date**: 2026-10-28 (all pages below were read on 2026-10-28 with ego-browser)

Sources (all `https://api-docs.deepseek.com/...`, read 2026-10-28):
`/` (Your First API Call), `/quick_start/pricing`, `/quick_start/error_codes`, `/quick_start/rate_limit`,
`/quick_start/token_usage`, `/guides/thinking_mode`, `/guides/tool_calls`, `/guides/kv_cache`,
`/guides/vision`, `/guides/json_mode`, `/guides/multi_round_chat`, `/guides/responses_api`,
`/api/create-chat-completion`, `/updates` (latest entry dated 2026-10-17), `/news/news261017`.
Note: `/guides/function_calling` is a 404; the guide is `/guides/tool_calls`.

## 1. Base URL and model ids

| Item | Value |
|---|---|
| OpenAI-format base_url | `https://api.deepseek.com` (endpoint `POST /chat/completions`) |
| Beta base_url (strict tools, prefix completion, FIM) | `https://api.deepseek.com/beta` |
| Anthropic-format base_url | `https://api.deepseek.com/anthropic` |
| Current model ids | `deepseek-flash`, `deepseek-v4-pro` (the API reference enumerates only these two) |
| `deepseek-flash` serves | DeepSeek-V4.1-Flash-1017 (multimodal, thinking + non-thinking) |
| `deepseek-v4-pro` serves | DeepSeek-V4-Pro-0813 (text only) |

- No separate "chat" vs "reasoner" model ids any more. Thinking is a request switch (section 4); both models do both modes.
- `deepseek-flash` is a floating alias: the 2026-10-17 update moved it to V4.1-Flash-1017 with the name and prices unchanged. No dated or pinned API id is documented. The version appears only in the pricing table.
- Legacy names: `deepseek-chat` / `deepseek-reasoner` pointed to V4-Flash non-thinking / thinking from 2026-04-24, with discontinuation announced for 2026-07-24 (change log). They are not mentioned on the current home, pricing or API-reference pages, so treat them as gone. Not verified by a live call.
- Still accepted per home/pricing footnote: `deepseek-v4-flash` and `deepseek-v4-flash-vision-exp`. Models retired; requests are served by V4.1-Flash-1017 and billed at the Flash price.
- V4 Pro: the 2026-09-10 change log says service continues past 2026-09-14, "billing method remaining unchanged", with further notice if that changes. It had an announced end date once; it was extended.
- History: V3.2 (2025-12-01) -> V4 Pro/Flash (2026-04-24) -> V4-Flash 0731 -> V4-Pro GA 0813 (2026-08-13) -> V4.1-Flash (2026-09-10) -> V4.1-Flash-1017 (2026-10-17).
- Open weights: DeepSeek-V4.1-Flash-1017 is on Hugging Face and ModelScope (news 2026-10-17).

## 2. Pricing, context, output limits

Prices are USD per 1M tokens, from `/quick_start/pricing`.

| | deepseek-flash peak | deepseek-flash off-peak | deepseek-v4-pro peak | deepseek-v4-pro off-peak |
|---|---|---|---|---|
| Input, cache hit | $0.006 | $0.003 | $0.044 | $0.022 |
| Input, cache miss | $0.30 | $0.15 | $1.32 | $0.66 |
| Output | $1.20 | $0.60 | $3.96 | $1.98 |

- Peak/off-peak is in force (effective 2026-08-16 16:00 UTC per the 2026-08-13 change log). Off-peak is half of peak.
- Peak window: 01:00-04:00 and 06:00-10:00 UTC, Monday to Friday, excluding Chinese public holidays. Every other hour is off-peak, including weekends and Chinese public holidays in full. (2026-10-28 is a Wednesday.)
- Context length: 1M tokens for both. Max output: 384K (393216) for both.
- `max_tokens` default when unset: 8K non-thinking, 64K thinking, 128K when `reasoning_effort` is `max`. Valid range 1..393216. Reasoning tokens count toward the output.
- Concurrency limit per account: 2500 (flash), 500 (pro).
- Billing: granted balance is used before topped-up balance. DeepSeek reserves the right to change prices.
- Search/Fetch are separate APIs at $0.75 per 1,000 calls. Server-side Search/Fetch via DeepSeek Harness, Claude Code or Codex is free until billing starts 2026-10-31 16:00 UTC. Not used by Chat Completions.

## 3. Tool calling

- Supported on both models, in thinking and non-thinking mode (pricing "Tool Calls" row; tool_calls guide).
- Format is the standard Chat Completions one: `tools=[{type:"function", function:{name, description, parameters}}]`, assistant `tool_calls`, then `{"role":"tool","tool_call_id":...,"content":...}`. Tool names: `a-z A-Z 0-9 _ -`, max 128 characters, unique. Only `function` tools exist.
- `tool_choice`: `none | auto | required | {"type":"function","function":{"name":...}}`. Default is `none` without tools and `auto` with tools. The API reference says `required` and named tool choices are "not supported in thinking mode" and the API returns a 400 error. Disable thinking to use them. `auto` and `none` are fine in thinking mode.
- `strict` mode: Beta. Needs `base_url="https://api.deepseek.com/beta"`, and every function in `tools` must set `"strict": true`. Works in thinking and non-thinking mode. The server validates the schema and returns an error for unsupported JSON-schema types.
  - Strict rules: all object properties must be `required` and `additionalProperties: false`. Supported types: object, string, number, integer, boolean, array, enum, anyOf, `$ref` / `$def`.
  - Unsupported: string `minLength`/`maxLength`, array `minItems`/`maxItems`.
- Parallel tool calls: the Chat Completions docs have no `parallel_tool_calls` parameter and do not discuss parallel calls. `tool_choice: auto` is described as "calling one or more tools". The Responses API guide says `parallel_tool_calls` is "Ignored (parallel tool calling is always enabled)". Not confirmed for Chat Completions.
- `arguments` is a JSON string and may be invalid JSON or contain hallucinated parameters (API reference warning).
- The Chat Completions API "does not support inserting tool calls mid-conversation" (tool_calls guide). That means tool calls the client invents rather than the model generating. System messages can be inserted mid-conversation. The Anthropic and Responses endpoints support inserting tool calls.
- Tool messages: the API reference types a `tool` message's `content` as string or array of content parts (text / image_url / file parts). See section 6 on images.
- Stream: tool-call deltas carry `index`; the first chunk of each call carries id/type/name, later chunks carry only argument fragments.

## 4. Thinking mode

- Enabled by default, default effort `high`. It is a request parameter, not a separate model id.
- Switch: `{"thinking": {"type": "enabled" | "disabled"}}`. With the OpenAI Python SDK it must go in `extra_body={"thinking": {...}}`.
- Effort: top-level `reasoning_effort` in `none | low | high | max` (OpenAI SDK accepts it as a normal kwarg). `none` disables thinking; `low/high/max` enable it. Compatibility mapping: `minimal`->low, `low`->low, `medium`->high, `high`->high, `xhigh`->high, `max`->max, `ultra`->max.
- Output: `reasoning_content` is returned in the message (non-stream) or delta (stream), at the same level as `content`.
- Passing it back, depends on whether the request carries `tools`:
  - With `tools`: "the reasoning_content of all previous turns should be passed back" and is concatenated into the context. It must be passed back "even for turns where the model did not perform a tool call"; otherwise "the API will return a 400 error". This covers sub-requests inside one turn (assistant tool_calls -> tool result -> next request) and later user turns. The docs' sample appends the whole SDK message, which holds content, reasoning_content and tool_calls.
  - Without `tools`: reasoning_content from earlier turns need not be sent; if sent it is ignored and not added to the context.
- An assistant message with `tool_calls` in thinking mode (with tools in the request) therefore has to carry its own `reasoning_content`. The docs' sample shows turns where `content` is `''` and `reasoning_content` plus `tool_calls` are present.
- Request schema oddity: the API reference lists assistant `reasoning_content` only as "(Beta)" for Chat Prefix Completion input. The thinking guide (and its sample) is what requires it for tool flows.
- Sampling: in thinking mode `temperature`, `presence_penalty`, `frequency_penalty` are accepted but have no effect, with no error. `top_p`:
  - flash: takes effect only in thinking mode (range 0.95-1.0; lower values treated as 0.95). Fixed at 1.0 in non-thinking mode.
  - v4-pro: ignored in thinking mode (fixed 0.95 with tools, else 1.0). Takes effect in non-thinking mode.
- FIM completion is non-thinking only. JSON output is supported on both models; the prompt must itself mention JSON and contain an example.

## 5. Usage fields and context caching

Response `usage` (non-stream example and schema in `/api/create-chat-completion`):

| Field | Meaning |
|---|---|
| `prompt_tokens` | equals `prompt_cache_hit_tokens + prompt_cache_miss_tokens` |
| `prompt_cache_hit_tokens` | prompt tokens that hit the cache |
| `prompt_cache_miss_tokens` | prompt tokens that missed |
| `prompt_tokens_details.cached_tokens` | same as `prompt_cache_hit_tokens` (OpenAI-style alias) |
| `completion_tokens` | generated tokens |
| `completion_tokens_details.reasoning_tokens` | reasoning tokens (documented in the schema) |
| `total_tokens` | prompt + completion |

- Streaming: with `stream_options: {"include_usage": true}` every chunk has a `usage` field (null except last). The last chunk before `data: [DONE]` always carries the full usage. No separate usage-only chunk is sent. `stream_options` without `stream: true` returns 400.
- There is no cache-write token field, and no separate cache-write price. Hit and miss are the only input prices.
- Context caching: on by default for everyone, on disk, no code change.
  - Prefix match only. A hit needs a previously persisted prefix unit that the new request fully matches.
  - Units are persisted at the end of user input and end of model output of each request, at detected common prefixes (after two requests share a prefix, the third hits), and at fixed token intervals for long inputs/outputs.
  - "Best-effort", no guaranteed hit rate. Building a cache takes "seconds". Unused caches are cleared in "a few hours to a few days".
  - No minimum prefix length is stated on the current page (older docs may have stated one; not checked).
  - `user_id` isolates the KV cache per user. Requests with different `user_id` values do not share cache.
  - Sampling randomness is unaffected; only the input prefix is cached.
- Multi-turn append-only histories (as the adapter builds) match the "Example 1" pattern of the caching guide.

## 6. Rejected or ignored parameters, images, errors, limits

Parameters:

| Param | Behaviour on the official API |
|---|---|
| `max_tokens` | The documented limit parameter (1..393216). |
| `max_completion_tokens` | Not in the Chat Completions reference or anywhere else I read. Accepted, ignored or rejected is unknown. |
| `reasoning_effort` | Documented, see section 4. Extra values (`minimal/medium/xhigh/ultra`) are mapped, not rejected. |
| `thinking` | Documented, non-standard, so OpenAI SDK users need `extra_body`. |
| `temperature` | Range <=2, default 1. No effect in thinking mode (silently ignored). |
| `top_p` | See section 4. |
| `presence_penalty`, `frequency_penalty` | "DEPRECATED ... will not take effect", no error. |
| `logprobs`, `top_logprobs` (<=20) | Documented, including a `reasoning_content` logprobs array in the response. Whether they work in thinking mode is not stated. |
| `stop` | Up to 16 sequences. |
| `response_format` | `text` or `json_object`. |
| `user_id` | Extra body field; `[a-zA-Z0-9\-_]`, max 512 chars. |
| `tool_choice` required/named | 400 in thinking mode. |
| `stream_options` | 400 unless `stream: true`. |
| `parallel_tool_calls` | Not in the Chat Completions reference. |

Images:
- `deepseek-flash` accepts images (native multimodal since V4.1 Flash). `deepseek-v4-pro` is "Not supported" for vision.
- The format is the standard `{"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}` inside a `user` message content array. Also accepted: external http(s) URL (<=8192 chars, <=32 MiB, 60 s download) and Files API `file` parts (`file_id`, or `file_data` data URL).
- Formats: JPEG, PNG, GIF, WebP (detected from file content, not MIME). Optional `detail`: `low` (downscaled to 512x512), `high`/`original`/`auto` (original).
- Limits: request body 48 MiB; single image 32 MiB (64 MiB via Files API); up to 600 images per request; max 8192 px per side (4096 when the request has 15+ images).
- Token cost: images are resized to roughly 1300x1300 total pixels at most; hard cap 1024 tokens per image. Billed with text tokens at the normal input price. The Token & Token Usage page has an image calculator.
- Restriction line in the vision guide: "Images are supported in user messages only". Images in system or assistant messages give 400. The API reference also lists image_url parts as valid for `tool` message content, and the Responses API accepts images in tool outputs. The vision guide does not list `tool` among the rejected roles. Whether images inside a Chat Completions `tool` message really work was not tested.

Errors (`/quick_start/error_codes`):

| Code | Meaning | Handling note from docs |
|---|---|---|
| 400 | Invalid format (also the reasoning_content-missing and tool_choice-in-thinking cases) | Fix the request body |
| 401 | Wrong API key | Check key |
| 402 | Insufficient balance | Top up |
| 422 | Invalid parameters | Fix the parameters |
| 429 | Too fast, or over the concurrency or QPS limit | Pace requests |
| 500 | Server error | Retry after a brief wait |
| 503 | Server overloaded | Retry after a brief wait |

- Rate limit: only a concurrency limit is documented (2500 flash / 500 pro per account, regardless of API key). A request counts from send until the response completes. Going over gives HTTP 429. Accounts with raised quotas also get a per-`user_id` limit with the same numbers. No RPM/TPM figures are published.
- Keep-alive: while a request waits, non-stream responses emit empty lines and streams emit `: keep-alive` SSE comments. If inference has not started after 10 minutes, the server closes the connection.
- `finish_reason` values: `stop`, `length`, `content_filter`, `tool_calls`, `insufficient_system_resource` (inference interrupted by resource shortage), `aborted`.
- JSON output can occasionally return empty content (json_mode guide).

## Cross-reference: what the adapter currently does (facts only)

File: `python/noitabench/harness/adapters/openai_adapter.py` (304 lines, read 2026-10-28).

- Limit key: `max_tokens` when `base_url` is not OpenAI's (line 124), which is the documented DeepSeek key.
- `request()` (lines 122-135) builds only `model`, `messages`, the limit key, `tools` and `tool_choice: "auto"` when tools exist, and `reasoning_effort` from `EFFORT_MAP` when `cfg.effort` is set. It has no `extra_body` / `thinking` key.
- `EFFORT_MAP` (line 51) sends `low/medium/high` and maps `xhigh` and `max` to `"high"`, so `reasoning_effort: "max"` is never sent.
- The stored assistant message (lines 230-236) holds `role`, `content` and `tool_calls` only. `reasoning_content` is read into `ModelTurn.thinking` (line 218) but not written into the history.
- Images (lines 139-163, 250-255): tool results go out as `tool` messages with text only, and screenshots follow as a separate `user` message with `image_url` data URLs (`data:image/png;base64,...`).
- `usage_of` (lines 258-274) reads `prompt_tokens_details.cached_tokens` and `completion_tokens_details.reasoning_tokens`, both of which DeepSeek returns. `cache_write_tokens` is not present in DeepSeek usage.
- `FINISH_MAP` (lines 44-50) has no entry for `insufficient_system_resource` or `aborted`; unmapped values fall to `END_TURN` (line 196).
- `map_error` (lines 277-304): 429 -> retryable `rate_limit`; >=500 -> retryable `server`; 402 and 422 go to the generic `APIStatusError` branch as non-retryable `api` (400 -> `bad_request`, 401 -> `auth`).
- The SDK is built with `max_retries=config.max_retries` and `timeout=config.request_timeout` (lines 86-88). DeepSeek can hold a request open up to 10 minutes before inference starts.

## Not confirmed

- No live API call was made (no DeepSeek key was used). Everything above is from the documentation pages.
- Whether `deepseek-chat` / `deepseek-reasoner` still resolve today (announced end 2026-07-24).
- Whether `max_completion_tokens` is accepted, ignored or rejected on the DeepSeek endpoint.
- Parallel tool calls on Chat Completions (only the Responses API says it is always enabled).
- Whether `logprobs` works in thinking mode.
- Whether image parts inside a Chat Completions `tool` message are accepted (the API reference and the vision guide read differently).
- Minimum cache-prefix length (not stated on the current page).
- The exact trigger for a 422 versus a 400 (docs give no mapping).
- Whether a context-length overflow returns 400 or a `finish_reason: length` (not stated).
