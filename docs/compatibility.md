# Compatibility and rule scope

`chat-contract` checks a documented, intentionally narrow subset of two request surfaces. It is a preflight diagnostic, not an official compatibility certification.

## Chat Completions profile

Validated today:

* `messages` is a non-empty array of message objects with documented roles.
* Role-specific content shape, multimodal content parts, assistant `tool_calls`, and tool/function result fields.
* Tool-call IDs are unique, arguments are JSON objects, and every tool result is contiguous and matched to the immediately preceding assistant call block.
* Function/custom tool declarations, names, parameters schemas, named `tool_choice`, and strict-schema invariants.
* JSON mode's explicit JSON-instruction requirement, token-limit option conflicts, numeric option ranges, and stream usage options.

## Responses profile

Validated today:

* `input` string or typed input-item arrays, including message, function-call, and function-call-output items.
* `call_id` uniqueness and output matching when both sides appear in one fixture. An output from `previous_response_id` is reported as a warning because its originating call is outside the fixture.
* Responses function/custom tool declarations, JSON Schema shape, strict-schema invariants, named tool choices, and `text.format` structured-output shape.
* `input_text`, `input_image`, and `input_file` message content parts.

Unknown fields are ignored for forward compatibility. Unknown item/content types are warnings rather than silent success. A warning is non-failing by default and becomes a failure with `--strict`.

## Exit codes

* `0`: no errors (warnings may be present without `--strict`).
* `1`: contract errors, or warnings under `--strict`.
* `2`: unreadable input, malformed JSON/JSONL framing, or invalid CLI input options.

Rules are intentionally deterministic and local. A provider can still reject a request for model availability, account policy, context size, or a field outside this scope; those are not claims this tool tries to predict.
