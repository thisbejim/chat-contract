"""Stable text, JSON, and JUnit renderers for lint results."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any

from .models import BatchReport, Finding, LintReport, Severity

Result = LintReport | BatchReport


def result_dict(result: Result) -> dict[str, Any]:
    return result.as_dict()


def render_json(result: Result, *, pretty: bool = False) -> str:
    indent = 2 if pretty else None
    return json.dumps(result_dict(result), ensure_ascii=False, indent=indent, sort_keys=False)


def render_text(result: Result, *, strict: bool = False) -> str:
    findings = result.ordered_findings()
    failing = bool(result.errors) or (strict and bool(result.warnings))
    status = "FAIL" if failing else "PASS"
    lines = [f"{status} chat-contract ({result.profile})"]
    for finding in findings:
        lines.extend(_finding_lines(finding, strict=strict))
    summary = result.summary()
    if isinstance(result, BatchReport):
        lines.append(
            f"Summary: {summary['records']} record(s), {summary['errors']} error(s), "
            f"{summary['warnings']} warning(s), {summary['infos']} info(s)"
        )
    else:
        lines.append(
            f"Summary: {summary['errors']} error(s), {summary['warnings']} warning(s), "
            f"{summary['infos']} info(s)"
        )
    if strict and result.warnings and not result.errors:
        lines.append("Strict mode treats warnings as failures.")
    return "\n".join(lines)


def _finding_lines(finding: Finding, *, strict: bool) -> list[str]:
    severity = finding.severity.value.upper()
    if strict and finding.severity is Severity.WARNING:
        severity = "WARNING*"
    location = finding.path
    if finding.record is not None:
        location = f"record {finding.record} {location}"
    lines = [f"{severity} {finding.code} {location} — {finding.message}"]
    if finding.hint:
        lines.append(f"  hint: {finding.hint}")
    return lines


def render_junit(result: Result, *, strict: bool = False) -> str:
    suite = ET.Element(
        "testsuite",
        {
            "name": f"chat-contract[{result.profile}]",
            "tests": str(len(result.findings)),
            "failures": str(len(result.errors) + (len(result.warnings) if strict else 0)),
            "skipped": str(len(result.infos)),
        },
    )
    for finding in result.ordered_findings():
        testcase = ET.SubElement(
            suite,
            "testcase",
            {
                "classname": finding.path,
                "name": finding.code,
            },
        )
        if finding.severity is Severity.INFO:
            ET.SubElement(testcase, "skipped", {"message": finding.message})
        elif finding.severity is Severity.ERROR or (
            strict and finding.severity is Severity.WARNING
        ):
            failure = ET.SubElement(testcase, "failure", {"message": finding.message})
            failure.text = finding.hint or ""
        else:
            ET.SubElement(testcase, "system-out").text = finding.message
    ET.indent(suite, space="  ")
    return ET.tostring(suite, encoding="unicode")


def exit_code(result: Result, *, strict: bool = False) -> int:
    """Return 0 for a clean contract, 1 for findings, 2 for unreadable input."""

    if any(
        finding.code.startswith(("INPUT_", "JSONL_", "INPUT_FORMAT_"))
        for finding in result.findings
    ):
        return 2
    if result.errors or (strict and result.warnings):
        return 1
    return 0
