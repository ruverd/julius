"""Execute trusted, frozen local task checks and analyze paired outcomes."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from .evaluation_runner import Attempt, FrozenFixture, replay_paired_fixtures


class TaskCheck(BaseModel):
    """A predeclared argv check; zero exit status means success."""

    model_config = ConfigDict(extra="forbid", strict=True)
    argv: list[StrictStr] = Field(min_length=1)
    timeout_seconds: float = Field(default=10.0, gt=0, le=300, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_argv(self) -> TaskCheck:
        if any(not part or "\x00" in part for part in self.argv):
            raise ValueError("Check argv entries must be nonempty and contain no NUL bytes")
        return self


class TaskSnapshot(BaseModel):
    """Text files and checks hashed within a FrozenFixture snapshot."""

    model_config = ConfigDict(extra="forbid", strict=True)
    files: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    arm_files: dict[StrictStr, dict[StrictStr, StrictStr]]
    checks: list[TaskCheck] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_paths(self) -> TaskSnapshot:
        for files in (self.files, *self.arm_files.values()):
            for name in files:
                path = PurePosixPath(name)
                if (not name or "\\" in name or "\x00" in name or path.is_absolute()
                        or any(part in ("", ".", "..") for part in name.split("/"))):
                    raise ValueError(f"Unsafe fixture file path: {name!r}")
        for arm_files in self.arm_files.values():
            names = set(self.files) | set(arm_files)
            for name in names:
                parts = name.split("/")
                if any("/".join(parts[:index]) in names for index in range(1, len(parts))):
                    raise ValueError(f"Fixture file conflicts with a directory: {name!r}")
        return self


def _write_files(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        target = root.joinpath(*name.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _run_attempt(
    fixture: FrozenFixture, snapshot: TaskSnapshot, arm: str, index: int,
) -> tuple[Attempt, list[dict[str, Any]]]:
    observations: list[dict[str, Any]] = []
    attempt_start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="julius-task-") as directory:
        root = Path(directory)
        _write_files(root, snapshot.files)
        _write_files(root, snapshot.arm_files[arm])
        environment = {
            "HOME": directory,
            "TMPDIR": directory,
            "PATH": os.defpath,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        for name in ("LANG", "LC_ALL", "TZ"):
            if name in os.environ:
                environment[name] = os.environ[name]
        for check_index, check in enumerate(snapshot.checks):
            argv = [sys.executable if part == "{python}" else part for part in check.argv]
            started = time.perf_counter()
            try:
                with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stdout_file, \
                     tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr_file:
                    completed = subprocess.run(
                        argv, cwd=root, env=environment,
                        stdout=stdout_file, stderr=stderr_file, text=True,
                        timeout=check.timeout_seconds, check=False,
                    )
                    stdout_file.seek(0)
                    stderr_file.seek(0)
                    stdout = stdout_file.read(2049)
                    stderr = stderr_file.read(2049)
                observation = {
                    "check_index": check_index,
                    "argv": list(check.argv),
                    "exit_code": completed.returncode,
                    "timed_out": False,
                    "error": None,
                    "stdout": stdout[:2048],
                    "stderr": stderr[:2048],
                    "stdout_truncated": len(stdout) > 2048,
                    "stderr_truncated": len(stderr) > 2048,
                    "latency_ms": (time.perf_counter() - started) * 1000,
                }
            except subprocess.TimeoutExpired as exc:
                observation = {
                    "check_index": check_index,
                    "argv": list(check.argv),
                    "exit_code": None,
                    "timed_out": True,
                    "error": str(exc),
                    "stdout": None,
                    "stderr": None,
                    "stdout_truncated": None,
                    "stderr_truncated": None,
                    "latency_ms": (time.perf_counter() - started) * 1000,
                }
            except OSError as exc:
                observation = {
                    "check_index": check_index,
                    "argv": list(check.argv),
                    "exit_code": None,
                    "timed_out": False,
                    "error": str(exc),
                    "stdout": None,
                    "stderr": None,
                    "stdout_truncated": None,
                    "stderr_truncated": None,
                    "latency_ms": (time.perf_counter() - started) * 1000,
                }
            observations.append(observation)
            if observation["exit_code"] != 0:
                break
    attempt = Attempt(
        fixture_id=fixture.fixture_id, arm_id=arm, attempt_index=index,
        success=len(observations) == len(snapshot.checks)
        and all(item["exit_code"] == 0 for item in observations),
        input_tokens=None, output_tokens=None, cache_read_tokens=None,
        cache_write_tokens=None, auxiliary_tokens=None, cost_usd=None,
        latency_ms=(time.perf_counter() - attempt_start) * 1000,
    )
    return attempt, observations


def run_paired_fixture_tasks(
    fixtures: list[FrozenFixture], *, baseline_arm: str, candidate_arm: str,
    max_attempts: int = 1, seed: int = 0,
) -> dict[str, Any]:
    """Run declared checks in fresh temporary copies, then aggregate observed attempts.

    Commands are trusted caller input. Temporary directories isolate fixture files,
    but subprocesses have the caller's OS permissions and network access.
    """
    if not fixtures:
        raise ValueError("At least one frozen fixture is required")
    if not baseline_arm or not candidate_arm or baseline_arm == candidate_arm:
        raise ValueError("Distinct arms are required")
    if type(max_attempts) is not int or not 1 <= max_attempts <= 100:
        raise ValueError("max_attempts must be an integer from 1 to 100")
    if len({item.fixture_id for item in fixtures}) != len(fixtures):
        raise ValueError("Duplicate fixture ID")
    if len({item.task_id for item in fixtures}) != len(fixtures):
        raise ValueError("Duplicate task ID")
    prepared: list[tuple[FrozenFixture, TaskSnapshot]] = []
    for fixture in fixtures:
        verified = FrozenFixture.model_validate(fixture.model_dump())
        snapshot = TaskSnapshot.model_validate(verified.snapshot)
        if set(snapshot.arm_files) != {baseline_arm, candidate_arm}:
            raise ValueError("Each snapshot needs exactly the declared baseline and candidate arms")
        prepared.append((verified, snapshot))
    attempts: list[Attempt] = []
    checks: list[dict[str, Any]] = []
    for fixture, snapshot in prepared:
        for arm in (baseline_arm, candidate_arm):
            for index in range(max_attempts):
                attempt, observations = _run_attempt(fixture, snapshot, arm, index)
                attempts.append(attempt)
                checks.append({
                    "fixture_id": fixture.fixture_id,
                    "arm_id": arm,
                    "attempt_index": index,
                    "observations": observations,
                })
                if attempt.success:
                    break
    result = replay_paired_fixtures(
        fixtures, attempts, baseline_arm=baseline_arm, candidate_arm=candidate_arm, seed=seed,
    )
    return {**result, "scope": "local_fixture_execution", "checks": checks}
