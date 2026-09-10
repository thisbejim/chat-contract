from __future__ import annotations

import json
from pathlib import Path

from chat_contract.cli import main

ROOT = Path(__file__).parents[1]


def test_cli_clean_request_exits_zero(capsys) -> None:
    code = main([str(ROOT / "examples" / "valid-chat.json")])
    captured = capsys.readouterr()
    assert code == 0
    assert "PASS chat-contract" in captured.out


def test_cli_broken_request_exits_one(capsys) -> None:
    code = main([str(ROOT / "examples" / "broken-chat.json")])
    captured = capsys.readouterr()
    assert code == 1
    assert "FAIL chat-contract" in captured.out
    assert "TOOL_ARGUMENTS_INVALID_JSON" in captured.out


def test_cli_json_output_is_machine_readable(capsys) -> None:
    code = main([str(ROOT / "examples" / "valid-responses.json"), "--format", "json"])
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["profile"] == "responses"
    assert payload["valid"] is True


def test_cli_junit_output(capsys) -> None:
    code = main([str(ROOT / "examples" / "broken-responses.json"), "--format", "junit"])
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out.startswith("<testsuite")
    assert "failure" in captured.out


def test_cli_strict_turns_warning_into_failure(tmp_path, capsys) -> None:
    request_path = tmp_path / "continuation.json"
    request_path.write_text(
        json.dumps(
            {
                "previous_response_id": "resp_1",
                "input": [
                    {"type": "function_call_output", "call_id": "call_external", "output": "done"}
                ],
            }
        )
    )
    code = main([str(request_path), "--profile", "responses", "--strict"])
    captured = capsys.readouterr()
    assert code == 1
    assert "FAIL chat-contract" in captured.out
