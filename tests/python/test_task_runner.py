import sys

import pytest
from pydantic import ValidationError

from julius.evaluation_runner import FrozenFixture
from julius.task_runner import TaskSnapshot, run_paired_fixture_tasks


def fixture(task_id: str, snapshot: dict) -> FrozenFixture:
    return FrozenFixture(
        task_id=task_id, fixture_id=FrozenFixture.digest(task_id, snapshot), snapshot=snapshot,
    )


def test_executes_checks_and_records_failed_retries_and_unknown_usage() -> None:
    snapshot = {
        "files": {
            "check.py": (
                "from pathlib import Path\n"
                "import sys\n"
                "actual = Path('answer.txt').read_text()\n"
                "sys.exit(0 if actual == 'right' else 1)\n"
            ),
        },
        "arm_files": {
            "base": {"answer.txt": "wrong"},
            "new": {"answer.txt": "right"},
        },
        "checks": [{"argv": ["{python}", "-I", "check.py"], "timeout_seconds": 2.0}],
    }
    result = run_paired_fixture_tasks(
        [fixture("task", snapshot)], baseline_arm="base", candidate_arm="new",
        max_attempts=2,
    )
    assert result["scope"] == "local_fixture_execution"
    assert [item["success"] for item in result["attempts"]] == [False, False, True]
    assert all(item["latency_ms"] > 0 for item in result["attempts"])
    assert all(item["input_tokens"] is None and item["cost_usd"] is None
               for item in result["attempts"])
    assert result["analysis"]["baseline"]["retries"] == 1
    assert result["analysis"]["candidate"]["retries"] == 0
    assert result["analysis"]["savings"]["cost_usd"] is None
    assert [entry["observations"][0]["exit_code"] for entry in result["checks"]] == [1, 1, 0]


def test_each_retry_starts_from_frozen_files() -> None:
    snapshot = {
        "arm_files": {"base": {}, "new": {}},
        "checks": [{
            "argv": ["{python}", "-I", "-c",
                     "from pathlib import Path; p=Path('marker'); "
                     "existed=p.exists(); p.write_text('x'); raise SystemExit(0 if existed else 1)"],
            "timeout_seconds": 2.0,
        }],
    }
    result = run_paired_fixture_tasks(
        [fixture("task", snapshot)], baseline_arm="base", candidate_arm="new",
        max_attempts=2,
    )
    assert [item["success"] for item in result["attempts"]] == [False] * 4
    assert [entry["observations"][0]["exit_code"] for entry in result["checks"]] == [1] * 4


def test_timeout_is_recorded_as_failure() -> None:
    snapshot = {
        "arm_files": {"base": {}, "new": {}},
        "checks": [{
            "argv": ["{python}", "-I", "-c", "import time; time.sleep(1)"],
            "timeout_seconds": 0.01,
        }],
    }
    result = run_paired_fixture_tasks(
        [fixture("slow", snapshot)], baseline_arm="base", candidate_arm="new",
    )
    assert all(not item["success"] for item in result["attempts"])
    assert all(entry["observations"][0]["timed_out"] for entry in result["checks"])


def test_checks_do_not_inherit_secret_environment_and_output_is_bounded(monkeypatch) -> None:
    monkeypatch.setenv("JULIUS_TEST_SECRET", "private-token")
    snapshot = {
        "arm_files": {"base": {}, "new": {}},
        "checks": [{"argv": ["{python}", "-I", "-c",
                             "import os; print(os.getenv('JULIUS_TEST_SECRET', 'missing')); "
                             "print('x' * 5000)"]}],
    }
    result = run_paired_fixture_tasks(
        [fixture("bounded", snapshot)], baseline_arm="base", candidate_arm="new",
    )
    for entry in result["checks"]:
        output = entry["observations"][0]
        assert output["stdout"].startswith("missing\n")
        assert "private-token" not in output["stdout"]
        assert len(output["stdout"]) == 2048
        assert output["stdout_truncated"] is True


def test_invalid_snapshots_are_rejected_before_execution(tmp_path) -> None:
    marker = tmp_path / "should-not-exist"
    valid = fixture("valid", {
        "arm_files": {"base": {}, "new": {}},
        "checks": [{"argv": [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"]}],
    })
    invalid = fixture("invalid", {
        "arm_files": {"base": {"../escape": "x"}, "new": {}},
        "checks": [{"argv": ["{python}", "-c", "pass"]}],
    })
    with pytest.raises(ValidationError, match="Unsafe fixture file path"):
        run_paired_fixture_tasks([valid, invalid], baseline_arm="base", candidate_arm="new")
    assert not marker.exists()


def test_snapshot_digest_and_arm_set_are_checked() -> None:
    item = fixture("task", {
        "arm_files": {"base": {}, "new": {}},
        "checks": [{"argv": ["{python}", "-c", "pass"]}],
    })
    item.snapshot["checks"][0]["argv"][-1] = "raise SystemExit(1)"
    with pytest.raises(ValidationError, match="Fixture ID"):
        run_paired_fixture_tasks([item], baseline_arm="base", candidate_arm="new")
    other = fixture("task", {
        "arm_files": {"base": {}},
        "checks": [{"argv": ["{python}", "-c", "pass"]}],
    })
    with pytest.raises(ValueError, match="exactly"):
        run_paired_fixture_tasks([other], baseline_arm="base", candidate_arm="new")


def test_rejects_unsafe_paths_and_invalid_retry_count() -> None:
    with pytest.raises(ValidationError, match="Unsafe fixture file path"):
        TaskSnapshot.model_validate({
            "files": {"/absolute": "x"}, "arm_files": {"base": {}, "new": {}},
            "checks": [{"argv": ["{python}", "-c", "pass"]}],
        })
    with pytest.raises(ValidationError, match="conflicts with a directory"):
        TaskSnapshot.model_validate({
            "files": {"answer": "x"}, "arm_files": {"base": {"answer/part": "x"}, "new": {}},
            "checks": [{"argv": ["{python}", "-c", "pass"]}],
        })
    item = fixture("task", {
        "arm_files": {"base": {}, "new": {}},
        "checks": [{"argv": ["{python}", "-c", "pass"]}],
    })
    with pytest.raises(ValueError, match="max_attempts"):
        run_paired_fixture_tasks([item], baseline_arm="base", candidate_arm="new",
                                 max_attempts=True)
