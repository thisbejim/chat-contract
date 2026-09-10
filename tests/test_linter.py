from __future__ import annotations

import json
from pathlib import Path

from chat_contract import Severity, lint_request
from chat_contract.models import BatchReport
from chat_contract.parser import lint_text

ROOT = Path(__file__).parents[1]


def codes(report) -> set[str]:
    return {finding.code for finding in report.findings}


def valid_function_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
                "additionalProperties": False,
            },
        },
    }


def test_valid_chat_tool_turn_is_clean() -> None:
    request = {
        "model": "gpt-5.5",
        "messages": [
            {"role": "user", "content": "weather?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city":"Melbourne"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "sunny"},
            {"role": "assistant", "content": "It is sunny."},
        ],
        "tools": [valid_function_tool()],
    }
    report = lint_request(request, profile="chat-completions")
    assert report.valid
    assert report.summary() == {"errors": 0, "warnings": 0, "infos": 0, "total": 0}


def test_interleaved_tool_response_is_reported() -> None:
    request = {
        "messages": [
            {"role": "user", "content": "do it"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "do", "arguments": "{}"},
                    },
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {"name": "do", "arguments": "{}"},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
            {"role": "user", "content": "interrupt"},
        ]
    }
    report = lint_request(request, profile="chat-completions")
    assert {"TOOL_RESPONSES_NOT_CONTIGUOUS", "TOOL_RESPONSE_MISSING"} <= codes(report)
    assert report.valid is False


def test_orphan_tool_message_is_reported() -> None:
    report = lint_request(
        {"messages": [{"role": "tool", "tool_call_id": "call_1", "content": "no parent"}]},
        profile="chat-completions",
    )
    assert "ORPHAN_TOOL_MESSAGE" in codes(report)


def test_invalid_tool_arguments_and_duplicate_ids_are_reported() -> None:
    request = {
        "messages": [
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "x", "arguments": "{"},
                    },
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "x", "arguments": "{}"},
                    },
                ],
            },
        ]
    }
    report = lint_request(request, profile="chat-completions")
    assert {
        "TOOL_ARGUMENTS_INVALID_JSON",
        "DUPLICATE_TOOL_CALL_ID",
        "TOOL_RESPONSE_MISSING",
    } <= codes(report)


def test_json_mode_requires_explicit_json_instruction() -> None:
    report = lint_request(
        {
            "messages": [{"role": "user", "content": "Give me the answer"}],
            "response_format": {"type": "json_object"},
        },
        profile="chat-completions",
    )
    assert "JSON_MODE_MISSING_HINT" in codes(report)


def test_strict_schema_checks_nested_objects() -> None:
    request = {
        "messages": [{"role": "user", "content": "go"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "go",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "nested": {"type": "object", "properties": {"x": {"type": "string"}}}
                        },
                        "required": ["nested"],
                    },
                    "strict": True,
                },
            }
        ],
    }
    report = lint_request(request, profile="chat-completions")
    assert "STRICT_SCHEMA_ADDITIONAL_PROPERTIES" in codes(report)


def test_valid_responses_input_and_tool_output() -> None:
    request = {
        "model": "gpt-5.5",
        "input": [
            {"type": "message", "role": "user", "content": "weather?"},
            {"type": "function_call", "call_id": "call_1", "name": "weather", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "call_1", "output": "sunny"},
        ],
        "tools": [
            {
                "type": "function",
                "name": "weather",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            }
        ],
    }
    report = lint_request(request, profile="responses")
    assert report.valid


def test_responses_input_content_parts_use_responses_types() -> None:
    report = lint_request(
        {
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "What is here?"},
                        {"type": "input_image", "image_url": "https://example.test/image.png"},
                    ],
                }
            ]
        },
        profile="responses",
    )
    assert report.valid
    assert not report.warnings


def test_responses_builtin_tool_is_left_to_provider_schema() -> None:
    report = lint_request(
        {
            "input": "Find the latest release notes.",
            "tools": [{"type": "web_search_preview"}],
            "tool_choice": {"type": "web_search_preview"},
        },
        profile="responses",
    )
    assert report.valid
    assert not report.errors


def test_responses_output_from_previous_response_is_warning_not_error() -> None:
    report = lint_request(
        {
            "previous_response_id": "resp_1",
            "input": [
                {"type": "function_call_output", "call_id": "call_external", "output": "done"}
            ],
        },
        profile="responses",
    )
    assert report.valid
    assert "FUNCTION_OUTPUT_UNMATCHED" in codes(report)
    assert all(finding.severity is Severity.WARNING for finding in report.findings)


def test_auto_detection_and_ambiguous_request() -> None:
    assert (
        lint_request({"messages": [{"role": "user", "content": "hi"}]}).profile
        == "chat-completions"
    )
    assert lint_request({"input": "hi"}).profile == "responses"
    ambiguous = lint_request({"messages": [], "input": "hi"})
    assert "PROFILE_AMBIGUOUS" in codes(ambiguous)


def test_jsonl_batch_tracks_record_and_line() -> None:
    result = lint_text(
        '{"messages":[{"role":"user","content":"ok"}]}\n{"messages":[{"role":"tool","content":"bad"}]}\n',
        input_format="jsonl",
        profile="chat-completions",
    )
    assert isinstance(result, BatchReport)
    assert result.summary()["records"] == 2
    assert any(finding.record == 2 and finding.line == 2 for finding in result.findings)


def test_jsonl_blank_and_malformed_lines_fail() -> None:
    result = lint_text('{"messages":[]}\n\nnot-json\n', input_format="jsonl")
    assert isinstance(result, BatchReport)
    assert {"JSONL_BLANK_LINE", "JSONL_INVALID_RECORD"} <= codes(result)
    assert result.valid is False


def test_examples_are_parseable() -> None:
    for filename in (
        "valid-chat.json",
        "broken-chat.json",
        "valid-responses.json",
        "broken-responses.json",
    ):
        payload = json.loads((ROOT / "examples" / filename).read_text())
        report = lint_request(payload, profile="auto")
        assert report.profile in {"chat-completions", "responses"}
