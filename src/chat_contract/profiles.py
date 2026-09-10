"""Profile dispatch for Chat Completions and Responses requests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .chat import lint_chat
from .models import LintReport, Severity
from .responses import lint_responses


def detect_profile(request: Any) -> str | None:
    """Infer a profile from the distinctive top-level request fields."""

    if not isinstance(request, Mapping):
        return None
    has_messages = "messages" in request
    has_input = "input" in request
    if has_messages and not has_input:
        return "chat-completions"
    if has_input and not has_messages:
        return "responses"
    return None


def lint_request(request: Any, *, profile: str = "auto", strict: bool = False) -> LintReport:
    """Lint one decoded request using an explicit or inferred profile."""

    normalized = profile.strip().lower().replace("_", "-")
    if normalized in {"chat", "chat-completions", "chatcompletion"}:
        return lint_chat(request, strict=strict)
    if normalized in {"responses", "response"}:
        return lint_responses(request, strict=strict)
    if normalized != "auto":
        report = LintReport(profile=normalized)
        report.add(
            "PROFILE_INVALID",
            Severity.ERROR,
            "$",
            f"unknown profile {profile!r}; choose auto, chat-completions, or responses",
            "Pass --profile chat-completions or --profile responses.",
        )
        return report

    detected = detect_profile(request)
    if detected == "chat-completions":
        return lint_chat(request, strict=strict)
    if detected == "responses":
        return lint_responses(request, strict=strict)

    report = LintReport(profile="auto")
    if isinstance(request, Mapping) and "messages" in request and "input" in request:
        report.add(
            "PROFILE_AMBIGUOUS",
            Severity.ERROR,
            "$",
            "request contains both messages and input; auto-detection cannot choose a profile",
            "Pass --profile chat-completions or --profile responses explicitly.",
        )
    else:
        report.add(
            "PROFILE_UNDETECTABLE",
            Severity.ERROR,
            "$",
            "auto-detection needs a messages (Chat Completions) or input (Responses) field",
            "Pass an explicit profile or provide a complete request body.",
        )
    return report
