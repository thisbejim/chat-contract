"""Checks for the stateless input item form of the OpenAI Responses API."""

from __future__ import annotations

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

_MESSAGE_ROLES = {"system", "developer", "user", "assistant"}
_KNOWN_INPUT_TYPES = {
    "message",
    "function_call",
    "function_call_output",
    "custom_tool_call",
    "custom_tool_call_output",
    "reasoning",
    "computer_call_output",
    "file_search_call",
    "web_search_call",
    "code_interpreter_call",
    "mcp_call",
    "mcp_call_output",
    "item_reference",
}
_BUILTIN_TOOL_TYPES = {
    "web_search_preview",
    "web_search",
    "file_search",
    "computer_use_preview",
    "computer",
    "code_interpreter",
    "image_generation",
    "mcp",
    "local_shell",
    "shell",
    "apply_patch",
}


def lint_responses(request: Any, *, strict: bool = False) -> LintReport:
    report = LintReport(profile="responses")
    if not require_object(report, request):
        return report

    input_value = request.get("input", MISSING)
    if input_value is not MISSING:
        if isinstance(input_value, str):
            if not input_value.strip():
                report.add(
                    "INPUT_EMPTY",
                    Severity.WARNING,
                    "$.input",
                    "input is an empty string",
                    "Provide a user request or omit input when continuing a stored response.",
                )
        elif require_list(report, input_value, "$.input"):
            _lint_input_items(report, input_value)
    elif "instructions" not in request and "previous_response_id" not in request:
        report.add(
            "INPUT_MISSING",
            Severity.WARNING,
            "$.input",
            "request has no input, instructions, or previous_response_id",
            "Provide input text or an explicit continuation reference.",
        )

    if "instructions" in request and not isinstance(request["instructions"], str):
        report.add(
            "INSTRUCTIONS_NOT_STRING",
            Severity.ERROR,
            "$.instructions",
            f"instructions must be a string, got {type_label(request['instructions'])}",
            "Use a string for developer instructions.",
        )
    if "previous_response_id" in request:
        require_string(
            report, request["previous_response_id"], "$.previous_response_id", nonempty=True
        )

    _positive_integer(report, request, "max_output_tokens")
    _positive_integer(report, request, "max_tool_calls")
    if "parallel_tool_calls" in request and not isinstance(request["parallel_tool_calls"], bool):
        report.add(
            "PARALLEL_TOOL_CALLS_NOT_BOOLEAN",
            Severity.ERROR,
            "$.parallel_tool_calls",
            "parallel_tool_calls must be boolean",
            "Use true or false.",
        )
    _lint_tools(report, request.get("tools", MISSING), strict=strict)
    _lint_tool_choice(report, request.get("tool_choice", MISSING))
    _lint_text_format(report, request.get("text", MISSING))
    return report


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


def _lint_input_items(report: LintReport, items: list[Any]) -> None:
    call_ids: list[Any] = []
    call_paths: list[str] = []
    output_ids: list[Any] = []
    output_paths: list[str] = []
    calls_seen: set[str] = set()
    outputs_seen: set[str] = set()

    for index, item in enumerate(items):
        path = f"$.input[{index}]"
        if not isinstance(item, Mapping):
            report.add(
                "INPUT_ITEM_NOT_OBJECT",
                Severity.ERROR,
                path,
                f"Responses input items must be objects, got {type_label(item)}",
                "Use a typed item such as message, function_call, or function_call_output.",
            )
            continue
        item_type = item.get("type", MISSING)
        if item_type is MISSING and "role" in item:
            item_type = "message"
        if not isinstance(item_type, str) or not item_type:
            report.add(
                "INPUT_ITEM_TYPE_MISSING",
                Severity.ERROR,
                f"{path}.type",
                "each Responses input item requires a type",
                "Set type to message, function_call, function_call_output, or another documented item type.",
            )
            continue
        if item_type not in _KNOWN_INPUT_TYPES:
            report.add(
                "UNKNOWN_INPUT_ITEM_TYPE",
                Severity.WARNING,
                f"{path}.type",
                f"unrecognized Responses input item type {item_type!r}",
                "Confirm that the target Responses API version supports this item type.",
            )

        if item_type == "message":
            _lint_message_item(report, item, path)
        elif item_type == "function_call":
            call_id = item.get("call_id", MISSING)
            if require_string(report, call_id, f"{path}.call_id", nonempty=True):
                call_ids.append(call_id)
                call_paths.append(f"{path}.call_id")
                calls_seen.add(call_id)
            require_string(report, item.get("name", MISSING), f"{path}.name", nonempty=True)
            parse_json_arguments(report, item.get("arguments", MISSING), f"{path}.arguments")
        elif item_type == "function_call_output":
            call_id = item.get("call_id", MISSING)
            if require_string(report, call_id, f"{path}.call_id", nonempty=True):
                output_ids.append(call_id)
                output_paths.append(f"{path}.call_id")
                outputs_seen.add(call_id)
            if "output" not in item:
                report.add(
                    "FUNCTION_OUTPUT_MISSING",
                    Severity.ERROR,
                    f"{path}.output",
                    "function_call_output requires output",
                    "Return the tool result under output.",
                )
            elif not isinstance(item["output"], (str, list, Mapping)):
                report.add(
                    "FUNCTION_OUTPUT_INVALID",
                    Severity.ERROR,
                    f"{path}.output",
                    f"function_call_output.output must be a string, content array, or object, got {type_label(item['output'])}",
                    "Serialize scalar results as strings or JSON objects.",
                )
        elif item_type == "custom_tool_call":
            require_string(report, item.get("call_id", MISSING), f"{path}.call_id", nonempty=True)
            validate_tool_name(report, item.get("name", MISSING), f"{path}.name")
            require_string(report, item.get("input", MISSING), f"{path}.input")
        elif item_type == "custom_tool_call_output":
            require_string(report, item.get("call_id", MISSING), f"{path}.call_id", nonempty=True)
            if "output" not in item:
                report.add(
                    "CUSTOM_OUTPUT_MISSING",
                    Severity.ERROR,
                    f"{path}.output",
                    "custom_tool_call_output requires output",
                    "Return the custom tool result under output.",
                )

    unique_ids(report, call_ids, call_paths, code="DUPLICATE_FUNCTION_CALL_ID", label="call_id")
    unique_ids(
        report, output_ids, output_paths, code="DUPLICATE_FUNCTION_OUTPUT_ID", label="call_id"
    )
    for call_id, path in zip(output_ids, output_paths, strict=True):
        if call_id not in calls_seen:
            report.add(
                "FUNCTION_OUTPUT_UNMATCHED",
                Severity.WARNING,
                path,
                f"function output references call_id {call_id!r} not present in this input",
                "This is valid when the call came from previous_response_id; otherwise include the function_call item.",
            )
    for call_id in sorted(calls_seen - outputs_seen):
        report.add(
            "FUNCTION_OUTPUT_NOT_IN_INPUT",
            Severity.WARNING,
            "$.input",
            f"function call {call_id!r} has no output in this input array",
            "Include function_call_output in the continuation request, or omit the call item from replay fixtures.",
        )


def _lint_message_item(report: LintReport, item: Mapping[str, Any], path: str) -> None:
    role = item.get("role", MISSING)
    if not isinstance(role, str) or role not in _MESSAGE_ROLES:
        report.add(
            "MESSAGE_ROLE_INVALID",
            Severity.ERROR,
            f"{path}.role",
            f"Responses message role must be one of {sorted(_MESSAGE_ROLES)}, got {role!r}",
            "Use user, developer, system, or assistant.",
        )
    content = item.get("content", MISSING)
    if content is MISSING:
        report.add(
            "MESSAGE_CONTENT_MISSING",
            Severity.ERROR,
            f"{path}.content",
            "Responses message items require content",
            "Add a string or typed content-part array.",
        )
    else:
        validate_content(
            report,
            content,
            f"{path}.content",
            role=str(role),
            allow_empty=False,
            text_part_types={"text", "input_text", "output_text"},
            image_part_types={"image_url", "input_image"},
            audio_part_types={"input_audio"},
            file_part_types={"file", "input_file"},
        )


def _lint_tools(report: LintReport, tools: Any, *, strict: bool) -> set[str]:
    if tools is MISSING:
        return set()
    if not require_list(report, tools, "$.tools"):
        return set()
    names: set[str] = set()
    for index, tool in enumerate(tools):
        path = f"$.tools[{index}]"
        if not isinstance(tool, Mapping):
            report.add(
                "TOOL_NOT_OBJECT",
                Severity.ERROR,
                path,
                f"tool definition must be an object, got {type_label(tool)}",
                "Use a Responses function or custom tool object.",
            )
            continue
        kind = tool.get("type", MISSING)
        if kind == "function":
            name = tool.get("name", MISSING)
            if validate_tool_name(report, name, f"{path}.name") and name in names:
                report.add(
                    "DUPLICATE_TOOL_NAME",
                    Severity.ERROR,
                    f"{path}.name",
                    f"tool name {name!r} is declared more than once",
                    "Give each tool a unique name.",
                )
            if isinstance(name, str):
                names.add(name)
            if "description" in tool and not isinstance(tool["description"], str):
                report.add(
                    "TOOL_DESCRIPTION_NOT_STRING",
                    Severity.ERROR,
                    f"{path}.description",
                    "tool description must be a string",
                    "Use a concise description of when the model should call the tool.",
                )
            parameters = tool.get("parameters", MISSING)
            if parameters is MISSING:
                report.add(
                    "TOOL_PARAMETERS_MISSING",
                    Severity.ERROR,
                    f"{path}.parameters",
                    "Responses function tools require a parameters JSON Schema",
                    'Use {"type": "object", "properties": {...}}.',
                )
            else:
                validate_json_schema(
                    report, parameters, f"{path}.parameters", require_object_root=True
                )
                strict_value = tool.get("strict", MISSING)
                if strict_value is True:
                    _lint_strict_schema(report, parameters, f"{path}.parameters")
                elif strict_value is not MISSING and not isinstance(strict_value, bool):
                    report.add(
                        "TOOL_STRICT_INVALID",
                        Severity.ERROR,
                        f"{path}.strict",
                        "tool.strict must be boolean",
                        "Use true or false.",
                    )
        elif kind == "custom":
            validate_tool_name(report, tool.get("name", MISSING), f"{path}.name")
        elif kind in _BUILTIN_TOOL_TYPES:
            # Built-in tools are owned by the provider and their fields evolve
            # independently of the function-tool contract.
            continue
        else:
            report.add(
                "TOOL_TYPE_INVALID",
                Severity.ERROR,
                f"{path}.type",
                "Responses tool.type must be function, custom, or a documented built-in tool",
                "Use the tool shape supported by your Responses API endpoint.",
            )
    return names


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


def _lint_tool_choice(report: LintReport, choice: Any) -> None:
    if choice is MISSING:
        return
    path = "$.tool_choice"
    if isinstance(choice, str):
        if choice not in {"none", "auto", "required"}:
            report.add(
                "TOOL_CHOICE_INVALID",
                Severity.ERROR,
                path,
                f"tool_choice string {choice!r} is not none, auto, or required",
                "Use a documented tool_choice option.",
            )
        return
    if not isinstance(choice, Mapping):
        report.add(
            "TOOL_CHOICE_INVALID",
            Severity.ERROR,
            path,
            f"tool_choice must be a string or object, got {type_label(choice)}",
            "Use auto, required, none, or a named tool object.",
        )
        return
    kind = choice.get("type")
    if kind == "function":
        require_string(report, choice.get("name", MISSING), f"{path}.name", nonempty=True)
    elif kind == "mcp":
        require_string(
            report, choice.get("server_label", MISSING), f"{path}.server_label", nonempty=True
        )
    elif kind in _BUILTIN_TOOL_TYPES:
        return
    else:
        report.add(
            "TOOL_CHOICE_TYPE_INVALID",
            Severity.ERROR,
            f"{path}.type",
            "named Responses tool_choice objects must have type=function or type=mcp",
            "Use a documented named-tool object.",
        )


def _lint_text_format(report: LintReport, text: Any) -> None:
    if text is MISSING:
        return
    if not isinstance(text, Mapping):
        report.add(
            "TEXT_NOT_OBJECT",
            Severity.ERROR,
            "$.text",
            f"text must be an object, got {type_label(text)}",
            'Use {"format": {"type": "text"}} or json_schema format.',
        )
        return
    format_spec = text.get("format", MISSING)
    if format_spec is MISSING:
        return
    if not isinstance(format_spec, Mapping):
        report.add(
            "TEXT_FORMAT_NOT_OBJECT",
            Severity.ERROR,
            "$.text.format",
            f"text.format must be an object, got {type_label(format_spec)}",
            "Use text, json_object, or json_schema format.",
        )
        return
    kind = format_spec.get("type", MISSING)
    if kind not in {"text", "json_object", "json_schema"}:
        report.add(
            "TEXT_FORMAT_TYPE_INVALID",
            Severity.ERROR,
            "$.text.format.type",
            "text.format.type must be text, json_object, or json_schema",
            "Choose one of the documented response formats.",
        )
        return
    if kind == "json_schema":
        require_string(
            report, format_spec.get("name", MISSING), "$.text.format.name", nonempty=True
        )
        validate_json_schema(report, format_spec.get("schema", MISSING), "$.text.format.schema")
        strict = format_spec.get("strict", MISSING)
        if strict is not MISSING and not isinstance(strict, bool):
            report.add(
                "TEXT_FORMAT_STRICT_INVALID",
                Severity.ERROR,
                "$.text.format.strict",
                "text.format.strict must be boolean",
                "Use true or false.",
            )
    if kind == "json_object":
        # Responses JSON mode has the same practical prompt-hint failure mode as Chat.
        report.add(
            "JSON_MODE_REVIEW_HINT",
            Severity.INFO,
            "$.text.format.type",
            "json_object mode is selected; ensure input instructions explicitly request JSON",
            "An explicit JSON instruction prevents provider-specific validation failures.",
        )
