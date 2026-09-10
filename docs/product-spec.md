# Product specification

## Target developer

AI platform, agent, and SDK engineers who assemble request histories by hand or through an adapter, especially teams moving between OpenAI Chat Completions, the Responses API, and OpenAI-compatible local servers.

## Problem

When an agent continues a tool-using conversation, a request can be valid JSON and still be rejected with a provider-specific 400. The common failures are semantic: a `tool` result is missing or interleaved, a `tool_call_id` is duplicated, function arguments are malformed JSON, or an adapter emits a message shape another endpoint rejects. These failures are usually found only after a network round trip.

## Public evidence

The demand is demonstrated by recurring, independently reported failures:

* [OpenAI Agents issue #873](https://github.com/openai/openai-agents-python/issues/873) reports the exact “tool must be a response to a preceding message with tool_calls” error and the requirement that responses directly follow the initiating assistant message.
* [GitHub Copilot SDK issue #1922](https://github.com/github/copilot-sdk/issues/1922) documents a 400 caused by interleaving image-bearing user messages between parallel tool responses.
* [Rancher AI issue #172](https://github.com/rancher/rancher-ai-agent/issues/172) describes production failures from missing tool messages in persisted history.
* [Agentgateway issue #2403](https://github.com/agentgateway/agentgateway/issues/2403) shows an OpenAI-compatible proxy rejecting a correctly shaped tool result during multi-agent orchestration.
* The [OpenAI Chat API reference](https://developers.openai.com/api/reference/cli/resources/chat) exposes separate message variants for assistant tool calls and tool results, while the [Responses API reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create) uses a different input-item and `call_id` vocabulary. Type-checking one SDK model does not validate a reconstructed history across these surfaces.

## Existing workflow and alternatives

Developers currently discover these errors by sending the request, reading a 400, and inspecting a large serialized history. SDK models catch field types but generally do not walk the conversation state machine. The official [MCP Inspector](https://github.com/modelcontextprotocol/inspector) is useful for interactive MCP servers, not offline Chat/Responses request fixtures. Rust's [tower-llm validation module](https://docs.rs/tower-llm/latest/src/tower_llm/validation/mod.rs.html) demonstrates the value of pure conversation checks, but it is a library inside one Rust project rather than a provider-profiled, language-agnostic CLI. Browser validators are convenient for one pasted message array but are not CI artifacts.

## Product thesis

For AI infrastructure engineers, `chat-contract` catches semantic request-history failures before an API call better than an SDK or ad-hoc print statement because it is deterministic, offline, profile-aware, and emits line-addressable JSON/JUnit diagnostics that can run in CI.

## Core workflow

```text
JSON/JSONL request fixture or stdin
        ↓
chat-contract (profile + semantic state-machine checks)
        ↓
human diagnostics, stable JSON/JUnit, and a CI exit code
```

## Non-goals

* It does not call a provider, execute tools, or certify an endpoint as officially compatible.
* It does not attempt to implement every provider-specific field or a complete JSON Schema validator.
* It does not infer whether a model will choose a tool correctly or judge answer quality.
* It does not mutate request files; diagnostics include safe remediation hints instead.

## Interface and independence

The primary interface is a zero-dependency CLI. The Python library exposes the same deterministic checks. JSON and JSONL work offline; no account, API key, network, hosted database, or telemetry is required. Optional live-provider use is deliberately out of scope for the core tool: capture a request in the application and lint the captured file.

## Why a frontier-AI engineer would clone it

The useful moment is immediately before retrying a failed agent turn or switching an adapter: pipe the exact request fixture through the linter and get the first broken message, matching call IDs, and a CI-friendly failure without reproducing the model call. It complements a stream/response checker by validating the request side of the boundary, where history serializers and provider adapters actually introduce these 400s.

## Quality-bar review

The skeptical case is that a framework may already maintain valid history, or that a provider changes its rules. The project stays useful because it accepts recorded fixtures from any framework, separates hard protocol invariants from portability warnings, and keeps profiles small and documented. Its improvement is not another dashboard: it turns opaque remote validation errors into a fast local test that can be checked into a repository.
