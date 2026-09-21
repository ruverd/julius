import sys

import pytest

from julius.claude_probe import probe_local_protocol


def test_local_probe_exercises_real_hook_and_mcp_subprocesses():
    result = probe_local_protocol(python_executable=sys.executable)
    assert result == {
        "scope": "local_protocol", "available": True,
        "evidence": {
            "hook_candidate": True, "mcp_initialize": True,
            "mcp_tools_list": True, "artifact_restore": True,
        },
        "error": None,
    }


def test_local_probe_reports_missing_python_without_claiming_availability():
    result = probe_local_protocol(python_executable="/missing/julius-probe-python")
    assert result["scope"] == "local_protocol"
    assert result["available"] is False
    assert result["evidence"]["artifact_restore"] is False
    assert result["error"] == "FileNotFoundError"


def test_local_probe_requires_positive_timeout():
    with pytest.raises(ValueError, match="Timeout"):
        probe_local_protocol(timeout_seconds=0)
