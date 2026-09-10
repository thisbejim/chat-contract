"""Input decoding and JSONL batch handling."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from .models import BatchReport, Finding, LintReport, Severity
from .profiles import lint_request

Result = LintReport | BatchReport


def lint_text(
    text: str,
    *,
    input_format: str = "auto",
    profile: str = "auto",
    strict: bool = False,
    source: str | None = None,
) -> Result:
    """Decode and lint JSON or JSONL text without touching the network or filesystem."""

    normalized = input_format.strip().lower()
    if normalized not in {"auto", "json", "jsonl"}:
        report = LintReport(profile=profile)
        report.add(
            "INPUT_FORMAT_INVALID",
            Severity.ERROR,
            "$",
            f"unknown input format {input_format!r}; choose auto, json, or jsonl",
            "Pass --input-format json or --input-format jsonl.",
        )
        return report

    if normalized == "jsonl":
        return _lint_jsonl(text, profile=profile, strict=strict, source=source)

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        if normalized == "json":
            report = LintReport(profile=profile, source=source)
            report.add(
                "INPUT_INVALID_JSON",
                Severity.ERROR,
                "$",
                "input is not valid JSON",
                "Provide one JSON request object or use --input-format jsonl for newline-delimited records.",
            )
            return report
        return _lint_jsonl(text, profile=profile, strict=strict, source=source)

    report = lint_request(payload, profile=profile, strict=strict)
    report.source = source
    return report


def _lint_jsonl(text: str, *, profile: str, strict: bool, source: str | None) -> BatchReport:
    batch = BatchReport(profile=profile, source=source)
    if not text.strip():
        batch.parse_findings.append(
            Finding(
                code="JSONL_EMPTY_INPUT",
                severity=Severity.ERROR,
                path="$",
                message="input does not contain a JSON or JSONL record",
                hint="Provide a request object or a JSONL file with one request per line.",
            )
        )
        return batch
    for record_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            batch.parse_findings.append(
                Finding(
                    code="JSONL_BLANK_LINE",
                    severity=Severity.ERROR,
                    path="$",
                    message="blank lines are not JSONL records",
                    hint="Remove the blank line or use a separate file for comments.",
                    record=record_number,
                    line=record_number,
                )
            )
            continue
        try:
            payload: Any = json.loads(line)
        except json.JSONDecodeError as exc:
            batch.parse_findings.append(
                Finding(
                    code="JSONL_INVALID_RECORD",
                    severity=Severity.ERROR,
                    path="$",
                    message=f"record is not valid JSON ({exc.msg} at character {exc.pos})",
                    hint="Keep exactly one complete JSON value on each line.",
                    record=record_number,
                    line=record_number,
                )
            )
            continue
        report = lint_request(payload, profile=profile, strict=strict)
        report.source = source
        report.findings = [
            replace(finding, record=record_number, line=record_number)
            for finding in report.findings
        ]
        batch.records.append(report)
    return batch
