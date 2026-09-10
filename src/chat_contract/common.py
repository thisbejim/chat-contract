"""Shared structural checks for the supported request profiles."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from .models import LintReport, Severity

MISSING = object()
TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def type_label(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def require_object(report: LintReport, value: Any, path: str = "$") -> bool:
    if not isinstance(value, Mapping):
        report.add(
            "REQUEST_NOT_OBJECT",
            Severity.ERROR,
            path,
            f"request must be a JSON object, got {type_label(value)}",
            "Pass the complete request body rather than a JSON array or scalar.",
        )
        return False
    return True


def require_list(report: LintReport, value: Any, path: str, *, nonempty: bool = False) -> bool:
    if not isinstance(value, list):
        report.add(
            "EXPECTED_ARRAY",
            Severity.ERROR,
            path,
            f"expected an array, got {type_label(value)}",
            "Use a JSON array for this request field.",
        )
        return False
    if nonempty and not value:
        report.add(
            "EMPTY_ARRAY",
            Severity.ERROR,
            path,
            "array must contain at least one item",
            "Add an item or omit the optional field.",
        )
        return False
    return True


def require_string(
    report: LintReport,
    value: Any,
    path: str,
    *,
    code: str = "EXPECTED_STRING",
    nonempty: bool = False,
) -> bool:
    if not isinstance(value, str):
        report.add(
            code,
            Severity.ERROR,
            path,
            f"expected a string, got {type_label(value)}",
            "Use a JSON string for this field.",
        )
        return False
    if nonempty and not value.strip():
        report.add(
            "EMPTY_STRING",
            Severity.ERROR,
            path,
            "string must not be empty",
            "Provide a non-empty value or omit the optional field.",
        )
        return False
    return True


def validate_content(
    report: LintReport,
    value: Any,
    path: str,
    *,
    role: str,
    allow_empty: bool = True,
    text_part_types: set[str] | None = None,
    image_part_types: set[str] | None = None,
    audio_part_types: set[str] | None = None,
    file_part_types: set[str] | None = None,
) -> bool:
    """Validate OpenAI-style string or content-part-array message content."""

    text_part_types = text_part_types or {"text"}
    image_part_types = image_part_types or {"image_url"}
    audio_part_types = audio_part_types or {"input_audio", "audio"}
    file_part_types = file_part_types or {"file"}

    if isinstance(value, str):
        if not value and not allow_empty:
            report.add(
                "EMPTY_CONTENT",
                Severity.ERROR,
                path,
                f"{role} content must not be empty",
                "Supply text or use a supported non-text content part.",
            )
            return False
        if not value:
            report.add(
                "EMPTY_CONTENT",
                Severity.WARNING,
                path,
                f"{role} content is an empty string",
                "Empty content is accepted by some providers but rejected by others.",
            )
        return True

    if not isinstance(value, list):
        report.add(
            "INVALID_CONTENT",
            Severity.ERROR,
            path,
            f"{role} content must be a string or content-part array, got {type_label(value)}",
            "Use a string or an array of typed content parts.",
        )
        return False

    if not value:
        report.add(
            "EMPTY_CONTENT_PARTS",
            Severity.ERROR if not allow_empty else Severity.WARNING,
            path,
            f"{role} content-part array is empty",
            "Provide at least one content part.",
        )
        return False

    valid = True
    for index, part in enumerate(value):
        part_path = f"{path}[{index}]"
        if not isinstance(part, Mapping):
            report.add(
                "CONTENT_PART_NOT_OBJECT",
                Severity.ERROR,
                part_path,
                f"content part must be an object, got {type_label(part)}",
                'Use objects such as {"type": "text", "text": "..."}.',
            )
            valid = False
            continue
        part_type = part.get("type", MISSING)
        if not isinstance(part_type, str) or not part_type:
            report.add(
                "CONTENT_PART_TYPE_MISSING",
                Severity.ERROR,
                f"{part_path}.type",
                "content part must declare a non-empty type",
                "Set type to text, image_url, input_audio, audio, or file as appropriate.",
            )
            valid = False
            continue

        if part_type in text_part_types:
            if not isinstance(part.get("text"), str):
                report.add(
                    "CONTENT_TEXT_MISSING",
                    Severity.ERROR,
                    f"{part_path}.text",
                    "text content parts require a string text field",
                    "Add a string-valued text field.",
                )
                valid = False
        elif part_type in image_part_types:
            image_url = part.get("image_url", MISSING)
            image_valid = (
                isinstance(image_url, str)
                or (isinstance(image_url, Mapping) and isinstance(image_url.get("url"), str))
                or (part_type == "input_image" and isinstance(part.get("file_id"), str))
            )
            if not image_valid:
                report.add(
                    "CONTENT_IMAGE_URL_INVALID",
                    Severity.ERROR,
                    f"{part_path}.image_url",
                    "image_url parts require an image_url object with a string url",
                    'Use {"type": "image_url", "image_url": {"url": "..."}}.',
                )
                valid = False
        elif part_type in audio_part_types:
            audio = part.get("input_audio", MISSING)
            if part_type == "audio":
                audio = part.get("audio", MISSING)
            if not isinstance(audio, Mapping) or not isinstance(audio.get("data"), str):
                report.add(
                    "CONTENT_AUDIO_INVALID",
                    Severity.ERROR,
                    f"{part_path}.input_audio",
                    "input_audio parts require an input_audio object with string data",
                    "Include base64 audio data and a supported format.",
                )
                valid = False
        elif part_type in file_part_types:
            file_value = part.get("file", MISSING)
            file_valid = isinstance(file_value, Mapping)
            if part_type == "input_file":
                file_valid = any(
                    isinstance(part.get(key), str) for key in ("file_id", "file_data", "filename")
                )
            if not file_valid:
                report.add(
                    "CONTENT_FILE_INVALID",
                    Severity.ERROR,
                    f"{part_path}.file",
                    "file parts require a file object",
                    "Include file_id, file_data, or filename as supported by the provider.",
                )
                valid = False
        elif part_type == "refusal":
            if not isinstance(part.get("refusal"), str):
                report.add(
                    "CONTENT_REFUSAL_INVALID",
                    Severity.ERROR,
                    f"{part_path}.refusal",
                    "refusal parts require a string refusal field",
                    "Use a string-valued refusal field.",
                )
                valid = False
        else:
            report.add(
                "UNKNOWN_CONTENT_PART",
                Severity.WARNING,
                f"{part_path}.type",
                f"unrecognized content part type {part_type!r}",
                "Confirm that the target provider supports this extension.",
            )
    return valid


def validate_tool_name(report: LintReport, value: Any, path: str) -> bool:
    if not require_string(report, value, path, nonempty=True):
        return False
    if len(value) > 64:
        report.add(
            "TOOL_NAME_TOO_LONG",
            Severity.ERROR,
            path,
            "tool name exceeds the 64-character OpenAI function-tool limit",
            "Shorten the name while keeping it unique and descriptive.",
        )
        return False
    if not TOOL_NAME_RE.fullmatch(value):
        report.add(
            "TOOL_NAME_INVALID",
            Severity.ERROR,
            path,
            "tool name may only contain letters, digits, underscores, and hyphens",
            "Rename the tool to match ^[A-Za-z0-9_-]+$.",
        )
        return False
    return True


def validate_json_schema(
    report: LintReport,
    schema: Any,
    path: str,
    *,
    require_object_root: bool = False,
) -> bool:
    """Check the schema shape without pretending to be a full JSON Schema validator."""

    if not isinstance(schema, Mapping):
        report.add(
            "SCHEMA_NOT_OBJECT",
            Severity.ERROR,
            path,
            f"JSON Schema must be an object, got {type_label(schema)}",
            "Pass a JSON Schema object with a type or composition keyword.",
        )
        return False

    valid = True
    schema_type = schema.get("type", MISSING)
    if schema_type is not MISSING and not (
        isinstance(schema_type, str)
        or (isinstance(schema_type, list) and all(isinstance(x, str) for x in schema_type))
    ):
        report.add(
            "SCHEMA_TYPE_INVALID",
            Severity.ERROR,
            f"{path}.type",
            "JSON Schema type must be a string or an array of strings",
            "Use a standard JSON Schema type declaration.",
        )
        valid = False
    if require_object_root and schema_type not in ("object", ["object"]):
        report.add(
            "SCHEMA_ROOT_NOT_OBJECT",
            Severity.ERROR,
            f"{path}.type",
            "tool input schemas must have an object root for this profile",
            "Wrap scalar input in an object with a named property.",
        )
        valid = False

    properties = schema.get("properties", MISSING)
    if properties is not MISSING:
        if not isinstance(properties, Mapping):
            report.add(
                "SCHEMA_PROPERTIES_INVALID",
                Severity.ERROR,
                f"{path}.properties",
                "JSON Schema properties must be an object",
                "Map property names to JSON Schema objects.",
            )
            valid = False
        else:
            for name, child in properties.items():
                if not isinstance(name, str):
                    report.add(
                        "SCHEMA_PROPERTY_NAME_INVALID",
                        Severity.ERROR,
                        f"{path}.properties",
                        "JSON Schema property names must be strings",
                        "Use JSON object keys for property names.",
                    )
                    valid = False
                    continue
                if not validate_json_schema(report, child, f"{path}.properties.{name}"):
                    valid = False

    required = schema.get("required", MISSING)
    if required is not MISSING:
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            report.add(
                "SCHEMA_REQUIRED_INVALID",
                Severity.ERROR,
                f"{path}.required",
                "JSON Schema required must be an array of strings",
                "List property names in the required array.",
            )
            valid = False
        elif isinstance(properties, Mapping):
            for name in required:
                if name not in properties:
                    report.add(
                        "SCHEMA_REQUIRED_UNKNOWN",
                        Severity.ERROR,
                        f"{path}.required",
                        f"required property {name!r} is not declared in properties",
                        "Add the property or remove it from required.",
                    )
                    valid = False

    for keyword in ("items", "additionalProperties", "not", "if", "then", "else"):
        child = schema.get(keyword, MISSING)
        if keyword == "items" and child is not MISSING and not isinstance(child, (Mapping, bool)):
            report.add(
                "SCHEMA_ITEMS_INVALID",
                Severity.ERROR,
                f"{path}.items",
                "JSON Schema items must be an object or boolean",
                "Provide a schema for array items.",
            )
            valid = False
        elif (
            keyword == "additionalProperties"
            and child is not MISSING
            and not isinstance(child, (Mapping, bool))
        ):
            report.add(
                "SCHEMA_ADDITIONAL_PROPERTIES_INVALID",
                Severity.ERROR,
                f"{path}.additionalProperties",
                "additionalProperties must be an object or boolean",
                "Use false, true, or a JSON Schema object.",
            )
            valid = False
        elif keyword in {"not", "if", "then", "else"} and child is not MISSING:
            if not isinstance(child, Mapping):
                report.add(
                    "SCHEMA_COMPOSITION_INVALID",
                    Severity.ERROR,
                    f"{path}.{keyword}",
                    f"{keyword} must contain a JSON Schema object",
                    "Use a JSON Schema object for this composition keyword.",
                )
                valid = False
            elif not validate_json_schema(report, child, f"{path}.{keyword}"):
                valid = False

    for keyword in ("anyOf", "oneOf", "allOf"):
        alternatives = schema.get(keyword, MISSING)
        if alternatives is not MISSING:
            if not isinstance(alternatives, list) or not alternatives:
                report.add(
                    "SCHEMA_COMPOSITION_INVALID",
                    Severity.ERROR,
                    f"{path}.{keyword}",
                    f"{keyword} must be a non-empty array of schemas",
                    "Provide one or more schema objects.",
                )
                valid = False
            else:
                for index, child in enumerate(alternatives):
                    if not validate_json_schema(report, child, f"{path}.{keyword}[{index}]"):
                        valid = False
    return valid


def parse_json_arguments(report: LintReport, value: Any, path: str) -> bool:
    if not require_string(report, value, path, code="TOOL_ARGUMENTS_NOT_STRING"):
        return False
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        report.add(
            "TOOL_ARGUMENTS_INVALID_JSON",
            Severity.ERROR,
            path,
            f"tool arguments are not valid JSON ({exc.msg} at character {exc.pos})",
            "Serialize arguments with json.dumps; do not concatenate JSON by hand.",
        )
        return False
    if not isinstance(parsed, Mapping):
        report.add(
            "TOOL_ARGUMENTS_NOT_OBJECT",
            Severity.ERROR,
            path,
            f"function tool arguments must decode to an object, got {type_label(parsed)}",
            'Encode an object such as {"city": "Melbourne"}.',
        )
        return False
    return True


def unique_ids(
    report: LintReport,
    values: list[Any],
    paths: list[str],
    *,
    code: str,
    label: str,
) -> None:
    seen: dict[str, str] = {}
    for value, path in zip(values, paths, strict=True):
        if not isinstance(value, str) or not value:
            continue
        if value in seen:
            report.add(
                code,
                Severity.ERROR,
                path,
                f"duplicate {label} {value!r}; first seen at {seen[value]}",
                f"Give each {label} a unique stable identifier.",
            )
        else:
            seen[value] = path
