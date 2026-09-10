"""Public result types used by the linter and CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    """How actionable a finding is."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


_SEVERITY_ORDER = {
    Severity.ERROR: 0,
    Severity.WARNING: 1,
    Severity.INFO: 2,
}


@dataclass(frozen=True)
class Finding:
    """A deterministic, machine-readable contract violation or advisory."""

    code: str
    severity: Severity
    path: str
    message: str
    hint: str | None = None
    record: int | None = None
    line: int | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity.value,
            "path": self.path,
            "message": self.message,
        }
        if self.hint is not None:
            result["hint"] = self.hint
        if self.record is not None:
            result["record"] = self.record
        if self.line is not None:
            result["line"] = self.line
        return result


@dataclass
class LintReport:
    """Findings for one request document."""

    profile: str
    findings: list[Finding] = field(default_factory=list)
    source: str | None = None

    @property
    def errors(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity is Severity.WARNING]

    @property
    def infos(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity is Severity.INFO]

    @property
    def valid(self) -> bool:
        return not self.errors

    def add(
        self,
        code: str,
        severity: Severity,
        path: str,
        message: str,
        hint: str | None = None,
        *,
        record: int | None = None,
        line: int | None = None,
    ) -> None:
        self.findings.append(
            Finding(
                code=code,
                severity=severity,
                path=path,
                message=message,
                hint=hint,
                record=record,
                line=line,
            )
        )

    def ordered_findings(self) -> list[Finding]:
        """Return findings in a stable order independent of traversal details."""

        return sorted(
            self.findings,
            key=lambda finding: (
                finding.record if finding.record is not None else -1,
                finding.line if finding.line is not None else -1,
                finding.path,
                _SEVERITY_ORDER[finding.severity],
                finding.code,
                finding.message,
            ),
        )

    def summary(self) -> dict[str, int]:
        return {
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "infos": len(self.infos),
            "total": len(self.findings),
        }

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "profile": self.profile,
            "valid": self.valid,
            "summary": self.summary(),
            "findings": [finding.as_dict() for finding in self.ordered_findings()],
        }
        if self.source is not None:
            result["source"] = self.source
        return result


@dataclass
class BatchReport:
    """Aggregate report for a JSONL input containing multiple requests."""

    profile: str
    records: list[LintReport] = field(default_factory=list)
    parse_findings: list[Finding] = field(default_factory=list)
    source: str | None = None

    @property
    def findings(self) -> list[Finding]:
        return [
            *self.parse_findings,
            *(finding for report in self.records for finding in report.findings),
        ]

    @property
    def errors(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity is Severity.WARNING]

    @property
    def infos(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity is Severity.INFO]

    @property
    def valid(self) -> bool:
        return not self.errors

    def summary(self) -> dict[str, int]:
        return {
            "records": len(self.records),
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "infos": len(self.infos),
            "total": len(self.findings),
        }

    def ordered_findings(self) -> list[Finding]:
        return sorted(
            self.findings,
            key=lambda finding: (
                finding.record if finding.record is not None else -1,
                finding.line if finding.line is not None else -1,
                finding.path,
                _SEVERITY_ORDER[finding.severity],
                finding.code,
                finding.message,
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "profile": self.profile,
            "valid": self.valid,
            "summary": self.summary(),
            "records": [report.as_dict() for report in self.records],
            "findings": [finding.as_dict() for finding in self.ordered_findings()],
        }
        if self.source is not None:
            result["source"] = self.source
        return result
