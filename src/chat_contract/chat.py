"""Checks for the Chat Completions request shape and message state machine."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .common import (
    MISSING,
    parse_json_arguments,
    require_list,
    require_object,
    require_string,
    type_label,
    unique_ids,
    validate_content,
    validate_json_schema,
    validate_tool_name,
)
from .models import LintReport, Severity

_ROLES = {"system", "developer", "user", "assistant", "tool", "function"}
_CHOICES = {"none", "auto", "required"}


def lint_chat(request: Any, *, strict: bool = False) -> LintReport:
    report = LintReport(profile="chat-completions")
    if not require_object(report, request):
        return report

    messages = request.get("messages", MISSING)
    if messages is MISSING:
        report.add(
            "MESSAGES_MISSING",
            Severity.ERROR,
            "$.messages",
            "Chat Completions requests require a messages array",
            'Add messages such as [{"role": "user", "content": "..."}].',
        )
        return report
    if not require_list(report, messages, "$.messages", nonempty=True):
        return report

    declared_tools = _lint_tools(report, request.get("tools", MISSING), strict=strict)
    _lint_request_options(report, request, messages, declared_tools)
    _lint_messages(report, messages, declared_tools)
    return report


def _lint_request_options(
    report: LintReport,
    request: Mapping[str, Any],
    messages: list[Any],
    declared_tools: set[str],
) -> None:
    if "model" in request:
        require_string(report, request["model"], "$.model", nonempty=True)

    if "max_tokens" in request and "max_completion_tokens" in request:
        report.add(
            "TOKEN_LIMITS_MUTUALLY_EXCLUSIVE",
            Severity.ERROR,
            "$",
            "max_tokens and max_completion_tokens cannot be sent together",
            "Choose max_completion_tokens for newer models, or max_tokens for legacy models.",
        )

    _number_range(report, request, "temperature", low=0, high=2)
    _number_range(report, request, "top_p", low=0, high=1)
    _positive_integer(report, request, "n")
    _positive_integer(report, request, "max_tokens")
    _positive_integer(report, request, "max_completion_tokens")

    stream = request.get("stream", False)
    if "stream" in request and not isinstance(stream, bool):
        report.add(
            "STREAM_NOT_BOOLEAN",
            Severity.ERROR,
            "$.stream",
            f"stream must be boolean, got {type_label(stream)}",
            "Use true or false.",
        )
        stream = False
    stream_options = request.get("stream_options", MISSING)
    if stream_options is not MISSING:
        if not isinstance(stream_options, Mapping):
            report.add(
                "STREAM_OPTIONS_NOT_OBJECT",
                Severity.ERROR,
                "$.stream_options",
                f"stream_options must be an object, got {type_label(stream_options)}",
                'Use {"include_usage": true} only with stream=true.',
            )
        else:
            include_usage = stream_options.get("include_usage", MISSING)
            if include_usage is not MISSING and not isinstance(include_usage, bool):
                report.add(
                    "INCLUDE_USAGE_NOT_BOOLEAN",
                    Severity.ERROR,
                    "$.stream_options.include_usage",
                    "include_usage must be boolean",
                    "Use true or false.",
                )
            if include_usage is True and stream is not True:
                report.add(
                    "INCLUDE_USAGE_REQUIRES_STREAM",
                    Severity.WARNING,
                    "$.stream_options.include_usage",
                    "include_usage has no effect unless stream=true",
                    "Set stream=true or remove stream_options.",
                )

    if "parallel_tool_calls" in request and not isinstance(request["parallel_tool_calls"], bool):
        report.add(
            "PARALLEL_TOOL_CALLS_NOT_BOOLEAN",
            Severity.ERROR,
            "$.parallel_tool_calls",
            "parallel_tool_calls must be boolean",
            "Use true or false.",
        )
    if request.get("parallel_tool_calls") is True and not declared_tools:
        report.add(
            "PARALLEL_TOOLS_WITHOUT_TOOLS",
            Severity.WARNING,
            "$.parallel_tool_calls",
            "parallel_tool_calls is set but no function tools are declared",
            "Declare tools or remove the option.",
        )

    _lint_tool_choice(report, request.get("tool_choice", MISSING), declared_tools)
    _lint_response_format(report, request.get("response_format", MISSING), messages)


def _number_range(
    report: LintReport, request: Mapping[str, Any], name: str, *, low: float, high: float
) -> None:
    if name not in request:
        return
    value = request[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        report.add(
            "OPTION_NOT_NUMBER",
            Severity.ERROR,
            f"$.{name}",
            f"{name} must be a number, got {type_label(value)}",
            f"Use a number between {low:g} and {high:g}.",
        )
    elif not low <= value <= high:
        report.add(
            "OPTION_OUT_OF_RANGE",
            Severity.ERROR,
            f"$.{name}",
            f"{name} must be between {low:g} and {high:g}, got {value}",
            f"Choose a value in the inclusive range [{low:g}, {high:g}].",
        )


def _positive_integer(report: LintReport, request: Mapping[str, Any], name: str) -> None:
    if name not in request:
        return
    value = request[name]
    if isinstance(value, bool) or not isinstance(value, int):
        report.add(
            "OPTION_NOT_INTEGER",
            Severity.ERROR,
            f"$.{name}",
            f"{name} must be a positive integer, got {type_label(value)}",
            "Use an integer greater than zero.",
        )
    elif value < 1:
        report.add(
            "OPTION_NOT_POSITIVE",
            Severity.ERROR,
            f"$.{name}",
            f"{name} must be greater than zero, got {value}",
            "Use a positive integer or omit the option.",
        )


def _lint_tool_choice(report: LintReport, choice: Any, declared_tools: set[str]) -> None:
    if choice is MISSING:
        return
    path = "$.tool_choice"
    if isinstance(choice, str):
        if choice not in _CHOICES:
            report.add(
                "TOOL_CHOICE_INVALID",
                Severity.ERROR,
                path,
                f"tool_choice must be one of {sorted(_CHOICES)}, got {choice!r}",
                "Use none, auto, required, or a named function object.",
            )
        return
    if not isinstance(choice, Mapping):
        report.add(
            "TOOL_CHOICE_INVALID",
            Severity.ERROR,
            path,
            f"tool_choice must be a string or object, got {type_label(choice)}",
            'Use {"type": "function", "function": {"name": "..."}}.',
        )
        return
    if choice.get("type") != "function":
        report.add(
            "TOOL_CHOICE_TYPE_INVALID",
            Severity.ERROR,
            f"{path}.type",
            "named Chat Completions tool_choice objects must have type='function'",
            "Set type to function and include function.name.",
        )
        return
    function = choice.get("function", MISSING)
    if not isinstance(function, Mapping):
        report.add(
            "TOOL_CHOICE_FUNCTION_MISSING",
            Severity.ERROR,
            f"{path}.function",
            "named function tool_choice requires a function object",
            'Include {"function": {"name": "..."}}.',
        )
        return
    if not require_string(
        report, function.get("name", MISSING), f"{path}.function.name", nonempty=True
    ):
        return
    if declared_tools and function["name"] not in declared_tools:
        report.add(
            "TOOL_CHOICE_UNDECLARED",
            Severity.ERROR,
            f"{path}.function.name",
            f"tool_choice names {function['name']!r}, but that tool is not declared",
            "Add the function to tools or choose a declared tool.",
        )


def _lint_response_format(report: LintReport, response_format: Any, messages: list[Any]) -> None:
    if response_format is MISSING:
        return
    path = "$.response_format"
    if not isinstance(response_format, Mapping):
        report.add(
            "RESPONSE_FORMAT_NOT_OBJECT",
            Severity.ERROR,
            path,
            f"response_format must be an object, got {type_label(response_format)}",
            'Use {"type": "text"}, json_object, or json_schema.',
        )
        return
    kind = response_format.get("type", MISSING)
    if kind not in {"text", "json_object", "json_schema"}:
        report.add(
            "RESPONSE_FORMAT_TYPE_INVALID",
            Severity.ERROR,
            f"{path}.type",
            "response_format.type must be text, json_object, or json_schema",
            "Choose one of the documented response format modes.",
        )
        return
    if kind == "json_object":
        joined = " ".join(
            _message_text(message) for message in messages if isinstance(message, Mapping)
        )
        if not re.search(r"\bjson\b", joined, flags=re.IGNORECASE):
            report.add(
                "JSON_MODE_MISSING_HINT",
                Severity.ERROR,
                path,
                "json_object mode requires the messages to mention the word 'json'",
                "Add an instruction such as 'Return a JSON object' to the system or user message.",
            )
    if kind == "json_schema":
        schema_spec = response_format.get("json_schema", MISSING)
        if not isinstance(schema_spec, Mapping):
            report.add(
                "RESPONSE_SCHEMA_MISSING",
                Severity.ERROR,
                f"{path}.json_schema",
                "json_schema response format requires a json_schema object",
                "Include name and schema fields.",
            )
            return
        require_string(
            report, schema_spec.get("name", MISSING), f"{path}.json_schema.name", nonempty=True
        )
        validate_json_schema(
            report, schema_spec.get("schema", MISSING), f"{path}.json_schema.schema"
        )
        strict = schema_spec.get("strict", MISSING)
        if strict is not MISSING and not isinstance(strict, bool):
            report.add(
                "RESPONSE_SCHEMA_STRICT_INVALID",
                Severity.ERROR,
                f"{path}.json_schema.strict",
                "json_schema.strict must be boolean",
                "Use true or false.",
            )


def _message_text(message: Mapping[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "")
            for part in content
            if isinstance(part, Mapping) and isinstance(part.get("text"), str)
        )
    return ""


def _lint_tools(report: LintReport, tools: Any, *, strict: bool) -> set[str]:
    if tools is MISSING:
        return set()
    if not require_list(report, tools, "$.tools"):
        return set()
    declared: set[str] = set()
    for index, tool in enumerate(tools):
        path = f"$.tools[{index}]"
        if not isinstance(tool, Mapping):
            report.add(
                "TOOL_NOT_OBJECT",
                Severity.ERROR,
                path,
                f"tool definition must be an object, got {type_label(tool)}",
                "Use a function or custom tool object.",
            )
            continue
        tool_type = tool.get("type", MISSING)
        if tool_type == "function":
            function = tool.get("function", MISSING)
            if not isinstance(function, Mapping):
                report.add(
                    "FUNCTION_TOOL_MISSING",
                    Severity.ERROR,
                    f"{path}.function",
                    "function tools require a function object",
                    "Include name, description, and parameters under function.",
                )
                continue
            name = function.get("name", MISSING)
            if validate_tool_name(report, name, f"{path}.function.name") and name in declared:
                report.add(
                    "DUPLICATE_TOOL_NAME",
                    Severity.ERROR,
                    f"{path}.function.name",
                    f"tool name {name!r} is declared more than once",
                    "Give each function tool a unique name.",
                )
            if isinstance(name, str):
                declared.add(name)
            if "description" in function and not isinstance(function["description"], str):
                report.add(
                    "TOOL_DESCRIPTION_NOT_STRING",
                    Severity.ERROR,
                    f"{path}.function.description",
                    "tool description must be a string",
                    "Use a concise description of when the model should call the tool.",
                )
            parameters = function.get("parameters", MISSING)
            if parameters is MISSING:
                report.add(
                    "TOOL_PARAMETERS_MISSING",
                    Severity.ERROR,
                    f"{path}.function.parameters",
                    "function tools require a parameters JSON Schema",
                    'Use {"type": "object", "properties": {...}} even for no-argument tools.',
                )
            else:
                validate_json_schema(
                    report,
                    parameters,
                    f"{path}.function.parameters",
                    require_object_root=True,
                )
                strict_value = function.get("strict", MISSING)
                if strict_value is True:
                    _lint_strict_schema(report, parameters, f"{path}.function.parameters")
                elif strict_value is not MISSING and not isinstance(strict_value, bool):
                    report.add(
                        "TOOL_STRICT_INVALID",
                        Severity.ERROR,
                        f"{path}.function.strict",
                        "function.strict must be boolean",
                        "Use true or false.",
                    )
        elif tool_type == "custom":
            custom = tool.get("custom", MISSING)
            if not isinstance(custom, Mapping):
                report.add(
                    "CUSTOM_TOOL_MISSING",
                    Severity.ERROR,
                    f"{path}.custom",
                    "custom tools require a custom object",
                    "Include name and description under custom.",
                )
            else:
                validate_tool_name(report, custom.get("name", MISSING), f"{path}.custom.name")
        else:
            report.add(
                "TOOL_TYPE_INVALID",
                Severity.ERROR,
                f"{path}.type",
                "tool.type must be function or custom",
                "Use a documented Chat Completions tool type.",
            )
    return declared


def _lint_strict_schema(report: LintReport, schema: Any, path: str) -> None:
    if not isinstance(schema, Mapping):
        return
    if schema.get("type") == "object":
        properties = schema.get("properties", {})
        if isinstance(properties, Mapping):
            if schema.get("additionalProperties") is not False:
                report.add(
                    "STRICT_SCHEMA_ADDITIONAL_PROPERTIES",
                    Severity.ERROR,
                    f"{path}.additionalProperties",
                    "strict function schemas require additionalProperties=false on every object",
                    "Set additionalProperties to false.",
                )
            required = schema.get("required", [])
            if not isinstance(required, list):
                required = []
            missing = [name for name in properties if name not in required]
            if missing:
                report.add(
                    "STRICT_SCHEMA_REQUIRED",
                    Severity.ERROR,
                    f"{path}.required",
                    f"strict function schemas must require every property; missing {missing!r}",
                    "List every property in required (use a nullable type for optional values).",
                )
            for name, child in properties.items():
                _lint_strict_schema(report, child, f"{path}.properties.{name}")
    for keyword in ("items", "anyOf", "oneOf", "allOf"):
        child = schema.get(keyword)
        if isinstance(child, Mapping):
            _lint_strict_schema(report, child, f"{path}.{keyword}")
        elif isinstance(child, list):
            for index, item in enumerate(child):
                _lint_strict_schema(report, item, f"{path}.{keyword}[{index}]")


def _lint_messages(report: LintReport, messages: list[Any], declared_tools: set[str]) -> None:
    roles_seen: list[str] = []
    all_call_ids: list[Any] = []
    all_call_paths: list[str] = []
    pending: dict[str, str] = {}
    consumed: set[str] = set()
    seen_user = False
    seen_non_instruction = False

    for index, message in enumerate(messages):
        path = f"$.messages[{index}]"
        if not isinstance(message, Mapping):
            report.add(
                "MESSAGE_NOT_OBJECT",
                Severity.ERROR,
                path,
                f"message must be an object, got {type_label(message)}",
                "Use objects with role and content fields.",
            )
            continue

        role = message.get("role", MISSING)
        if not isinstance(role, str) or not role:
            report.add(
                "MESSAGE_ROLE_MISSING",
                Severity.ERROR,
                f"{path}.role",
                "every message requires a non-empty role",
                "Use system, developer, user, assistant, tool, or function.",
            )
            role = ""
        elif role not in _ROLES:
            report.add(
                "MESSAGE_ROLE_INVALID",
                Severity.ERROR,
                f"{path}.role",
                f"unrecognized message role {role!r}",
                f"Use one of {sorted(_ROLES)}.",
            )
        roles_seen.append(role)

        if pending:
            if role != "tool":
                missing = sorted(pending)
                report.add(
                    "TOOL_RESPONSES_NOT_CONTIGUOUS",
                    Severity.ERROR,
                    f"{path}.role",
                    "tool responses must immediately follow the assistant tool-call message",
                    f"Insert tool messages for {missing!r} before the next {role or 'message'} message.",
                )
                for call_id in missing:
                    report.add(
                        "TOOL_RESPONSE_MISSING",
                        Severity.ERROR,
                        f"{path}",
                        f"no tool response was found for tool_call_id {call_id!r}",
                        "Append one role=tool message per tool_call_id.",
                    )
                pending.clear()
                consumed.clear()
            else:
                _consume_tool_response(report, message, path, pending, consumed)
        elif role == "tool":
            report.add(
                "ORPHAN_TOOL_MESSAGE",
                Severity.ERROR,
                path,
                "role=tool must follow an assistant message containing the matching tool call",
                "Preserve the assistant tool-call message immediately before this tool result.",
            )

        if role in {"system", "developer"}:
            if seen_non_instruction:
                report.add(
                    "INSTRUCTION_MESSAGE_LATE",
                    Severity.WARNING,
                    f"{path}.role",
                    f"{role} message appears after a non-instruction message",
                    "Keep system/developer instructions at the start for portable provider behavior.",
                )
        elif role:
            seen_non_instruction = True
            if role == "user":
                seen_user = True

        _lint_message_shape(report, message, path, role)

        calls = message.get("tool_calls", MISSING)
        if calls is not MISSING:
            if role != "assistant":
                report.add(
                    "TOOL_CALLS_WRONG_ROLE",
                    Severity.ERROR,
                    f"{path}.tool_calls",
                    "tool_calls is only valid on assistant messages",
                    "Move tool_calls to the assistant message that requested the tools.",
                )
            elif require_list(report, calls, f"{path}.tool_calls"):
                if len(calls) > 128:
                    report.add(
                        "TOO_MANY_TOOL_CALLS",
                        Severity.ERROR,
                        f"{path}.tool_calls",
                        f"one assistant message contains {len(calls)} tool calls; the documented maximum is 128",
                        "Split work across turns or reduce parallel calls.",
                    )
                block: dict[str, str] = {}
                for call_index, call in enumerate(calls):
                    call_path = f"{path}.tool_calls[{call_index}]"
                    tool_call_id = _lint_tool_call(report, call, call_path, declared_tools)
                    if isinstance(tool_call_id, str):
                        all_call_ids.append(tool_call_id)
                        all_call_paths.append(f"{call_path}.id")
                        block.setdefault(tool_call_id, call_path)
                pending = block
                consumed = set()

    if pending:
        for call_id in sorted(pending):
            report.add(
                "TOOL_RESPONSE_MISSING",
                Severity.ERROR,
                "$.messages",
                f"conversation ends before a tool response for tool_call_id {call_id!r}",
                "Append a role=tool message for every assistant tool call.",
            )

    if roles_seen and roles_seen[0] not in {"system", "developer", "user"}:
        report.add(
            "FIRST_MESSAGE_ROLE_SUSPICIOUS",
            Severity.WARNING,
            "$.messages[0].role",
            f"conversation starts with role={roles_seen[0]!r}; portable chat requests usually start with user",
            "Put system/developer instructions first, followed by a user message.",
        )
    if not seen_user:
        report.add(
            "USER_MESSAGE_MISSING",
            Severity.WARNING,
            "$.messages",
            "conversation contains no user message",
            "Include a user turn unless this is an intentional assistant continuation.",
        )
    unique_ids(
        report,
        all_call_ids,
        all_call_paths,
        code="DUPLICATE_TOOL_CALL_ID",
        label="tool_call_id",
    )


def _lint_message_shape(
    report: LintReport, message: Mapping[str, Any], path: str, role: str
) -> None:
    content = message.get("content", MISSING)
    if role in {"system", "developer", "user"}:
        if content is MISSING:
            report.add(
                "MESSAGE_CONTENT_MISSING",
                Severity.ERROR,
                f"{path}.content",
                f"{role} messages require content",
                "Add a string or content-part array.",
            )
        else:
            validate_content(report, content, f"{path}.content", role=role, allow_empty=False)
    elif role == "assistant":
        has_calls = "tool_calls" in message
        if content is MISSING or content is None:
            if not has_calls and not isinstance(message.get("refusal"), str):
                report.add(
                    "ASSISTANT_CONTENT_MISSING",
                    Severity.ERROR,
                    f"{path}.content",
                    "assistant messages need content unless they contain tool_calls or refusal",
                    "Keep content null only for a tool-call turn; otherwise provide text.",
                )
        else:
            validate_content(report, content, f"{path}.content", role=role, allow_empty=True)
        if (
            "refusal" in message
            and message["refusal"] is not None
            and not isinstance(message["refusal"], str)
        ):
            report.add(
                "ASSISTANT_REFUSAL_INVALID",
                Severity.ERROR,
                f"{path}.refusal",
                "assistant refusal must be a string when present",
                "Use a string refusal or omit the field.",
            )
    elif role == "tool":
        require_string(
            report, message.get("tool_call_id", MISSING), f"{path}.tool_call_id", nonempty=True
        )
        if content is MISSING:
            report.add(
                "TOOL_CONTENT_MISSING",
                Severity.ERROR,
                f"{path}.content",
                "tool messages require content",
                "Serialize the tool result as a string (or documented content parts).",
            )
        else:
            validate_content(report, content, f"{path}.content", role=role, allow_empty=False)
        if "name" in message and not isinstance(message["name"], str):
            report.add(
                "TOOL_NAME_FIELD_INVALID",
                Severity.ERROR,
                f"{path}.name",
                "tool message name must be a string when present",
                "Use the called function name or omit name.",
            )
    elif role == "function":
        require_string(report, message.get("name", MISSING), f"{path}.name", nonempty=True)
        if content is MISSING:
            report.add(
                "FUNCTION_CONTENT_MISSING",
                Severity.ERROR,
                f"{path}.content",
                "legacy function messages require content",
                "Provide the function result as a string.",
            )
        elif not isinstance(content, str):
            report.add(
                "FUNCTION_CONTENT_NOT_STRING",
                Severity.ERROR,
                f"{path}.content",
                "legacy function message content must be a string",
                "Serialize structured results with json.dumps.",
            )


def _lint_tool_call(
    report: LintReport, call: Any, path: str, declared_tools: set[str]
) -> str | None:
    if not isinstance(call, Mapping):
        report.add(
            "TOOL_CALL_NOT_OBJECT",
            Severity.ERROR,
            path,
            f"tool call must be an object, got {type_label(call)}",
            'Use {"id": "call_...", "type": "function", ...}.',
        )
        return None
    call_id = call.get("id", MISSING)
    if not require_string(report, call_id, f"{path}.id", nonempty=True):
        call_id = None
    call_type = call.get("type", MISSING)
    if call_type == "function":
        function = call.get("function", MISSING)
        if not isinstance(function, Mapping):
            report.add(
                "FUNCTION_CALL_MISSING",
                Severity.ERROR,
                f"{path}.function",
                "function tool calls require a function object",
                "Include name and JSON-encoded arguments.",
            )
        else:
            name = function.get("name", MISSING)
            require_string(report, name, f"{path}.function.name", nonempty=True)
            if declared_tools and isinstance(name, str) and name not in declared_tools:
                report.add(
                    "TOOL_CALL_UNDECLARED",
                    Severity.ERROR,
                    f"{path}.function.name",
                    f"assistant called undeclared function {name!r}",
                    "Declare the function in tools or fix the generated call name.",
                )
            parse_json_arguments(
                report, function.get("arguments", MISSING), f"{path}.function.arguments"
            )
    elif call_type == "custom":
        custom = call.get("custom", MISSING)
        if not isinstance(custom, Mapping):
            report.add(
                "CUSTOM_CALL_MISSING",
                Severity.ERROR,
                f"{path}.custom",
                "custom tool calls require a custom object",
                "Include the custom tool input under custom.",
            )
    else:
        report.add(
            "TOOL_CALL_TYPE_INVALID",
            Severity.ERROR,
            f"{path}.type",
            "tool call type must be function or custom",
            "Use a documented tool call type.",
        )
    return call_id if isinstance(call_id, str) else None


def _consume_tool_response(
    report: LintReport,
    message: Mapping[str, Any],
    path: str,
    pending: dict[str, str],
    consumed: set[str],
) -> None:
    call_id = message.get("tool_call_id", MISSING)
    if not isinstance(call_id, str) or not call_id:
        return
    if call_id in consumed:
        report.add(
            "DUPLICATE_TOOL_RESPONSE",
            Severity.ERROR,
            f"{path}.tool_call_id",
            f"tool_call_id {call_id!r} is answered more than once in this turn",
            "Keep exactly one tool result for each assistant tool call.",
        )
        return
    if call_id not in pending:
        report.add(
            "TOOL_RESPONSE_UNKNOWN_ID",
            Severity.ERROR,
            f"{path}.tool_call_id",
            f"tool response references unknown tool_call_id {call_id!r}",
            f"Respond to one of {sorted(pending)!r}.",
        )
        return
    consumed.add(call_id)
    pending.pop(call_id, None)
