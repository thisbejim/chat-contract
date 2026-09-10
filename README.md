# chat-contract

Offline semantic preflight checks for OpenAI-style Chat Completions and Responses API requests.

An agent request can be perfectly valid JSON and still fail with a remote 400 because a tool result is missing, a `tool_call_id` was duplicated, or an adapter interleaved messages in a provider-forbidden order. `chat-contract` checks the request history locally, before a network round trip, and produces stable diagnostics suitable for CI.

It is deliberately small: no model, API key, server, account, telemetry, or network access is needed.

## Quick start

Install from a checkout:

```bash
git clone https://github.com/thisbejim/chat-contract.git
cd chat-contract
python -m venv .venv
.venv/bin/python -m pip install -e .
```

Lint the shortest useful fixture:

```bash
.venv/bin/chat-contract examples/valid-chat.json
```

```text
PASS chat-contract (chat-completions)
Summary: 0 error(s), 0 warning(s), 0 info(s)
```

Try the broken fixture:

```bash
.venv/bin/chat-contract examples/broken-chat.json
```

```text
FAIL chat-contract (chat-completions)
ERROR TOOL_ARGUMENTS_INVALID_JSON $.messages[1].tool_calls[0].function.arguments — tool arguments are not valid JSON (...)
ERROR TOOL_RESPONSE_MISSING $.messages — conversation ends before a tool response for tool_call_id 'call_refund_1'
Summary: 3 error(s), 0 warning(s), 0 info(s)
```

The input file is never uploaded or executed.

## What it catches

### Chat Completions

* missing, orphaned, duplicated, unknown, or non-contiguous tool responses;
* duplicate tool-call IDs and malformed JSON arguments;
* role/content mistakes, assistant tool-call turns, and multimodal content parts;
* duplicate or malformed function/custom tool declarations;
* invalid tool names, schemas, strict-schema requirements, and named tool choices;
* JSON mode without an explicit JSON instruction;
* mutually exclusive token limits, option ranges, and streaming usage flags.

### Responses API

* typed `input` messages, function calls, and function-call outputs;
* duplicate and unmatched `call_id` values (with a warning when the call lives in `previous_response_id` state);
* Responses function/custom tool declarations and strict-schema requirements;
* `input_text`, `input_image`, and `input_file` content parts;
* structured `text.format` configuration and named tool choices.

The rules are a documented subset, not a promise of complete provider compatibility. See [compatibility.md](docs/compatibility.md).

## Input and output

Read one JSON request from a file or stdin:

```bash
chat-contract request.json
cat request.json | chat-contract --profile chat-completions
```

Read one request per JSONL line. Findings include record and line numbers:

```bash
chat-contract fixtures/requests.jsonl --input-format jsonl --format json --pretty
```

Auto-detection chooses Chat Completions when the request has `messages` and Responses when it has `input`. Use an explicit profile when a fixture is intentionally incomplete.

Machine-readable reports:

```bash
chat-contract request.json --format json > contract-report.json
chat-contract request.json --format junit > contract-report.xml
chat-contract request.json --strict  # warnings fail CI too
```

Exit status is `0` for a clean contract, `1` for contract findings (or strict-mode warnings), and `2` for unreadable or malformed input.

## Library API

The CLI and library share the same deterministic implementation:

```python
from chat_contract import lint_request

payload = {
    "messages": [{"role": "user", "content": "Hello"}],
}
report = lint_request(payload, profile="chat-completions")

if not report.valid:
    for finding in report.errors:
        print(f"{finding.path}: {finding.message}")
```

`profile="auto"` (the default) infers the profile from `messages` or `input`. `report.as_dict()` returns the same stable shape as `--format json`.

## CI example

```yaml
name: request-contracts
on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install .
      - run: chat-contract fixtures/requests.jsonl --input-format jsonl --strict
```

You can keep request fixtures next to an adapter or regression test. `chat-contract` does not call the model and never interprets tool arguments as commands.

## Why this exists

SDK type models and generic JSON Schema validators can say that a field is an array, but they do not normally know that an assistant tool-call message must be followed immediately by one matching tool result per call. That is the exact class of failure reported in [OpenAI Agents #873](https://github.com/openai/openai-agents-python/issues/873), [GitHub Copilot SDK #1922](https://github.com/github/copilot-sdk/issues/1922), [Rancher AI #172](https://github.com/rancher/rancher-ai-agent/issues/172), and [Agentgateway #2403](https://github.com/agentgateway/agentgateway/issues/2403).

`chat-contract` focuses on that missing local primitive. It complements response/stream validators: those inspect what a provider returned, while this checks what an adapter is about to send.

## Privacy and security

* All parsing and checks happen in-process on local data.
* There is no telemetry, network client, hosted service, or account integration.
* Tool arguments are parsed only as JSON; they are never imported, evaluated, or executed.
* Request contents are not echoed unless you provide them through a diagnostic path; findings contain paths and short remediation messages rather than copied prompts.

## Development

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
python -m compileall -q src
```

The test suite uses only synthetic fixtures and requires no API keys or network access. Contributions that add a provider rule should include a fixture, a deterministic finding code, and a link to the public behavior being checked.

## License

MIT. See [LICENSE](LICENSE).
