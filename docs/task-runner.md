# Local fixture task execution

`julius.task_runner.run_paired_fixture_tasks` executes predeclared subprocess checks for each arm of a `FrozenFixture`, then passes the observed attempts to `replay_paired_fixtures`. The fixture digest binds the task ID, files, arm overlays, check commands, and timeouts. The runner validates every fixture before starting any command.

```python
from julius.evaluation_runner import FrozenFixture
from julius.task_runner import run_paired_fixture_tasks

snapshot = {
    "files": {
        "check.py": "from pathlib import Path\nassert Path('answer.txt').read_text() == 'right'\n",
    },
    "arm_files": {
        "baseline": {"answer.txt": "wrong"},
        "candidate": {"answer.txt": "right"},
    },
    "checks": [{"argv": ["{python}", "-I", "check.py"], "timeout_seconds": 5.0}],
}
fixture = FrozenFixture(
    task_id="answer", fixture_id=FrozenFixture.digest("answer", snapshot), snapshot=snapshot,
)
result = run_paired_fixture_tasks(
    [fixture], baseline_arm="baseline", candidate_arm="candidate", max_attempts=2,
)
```

`files` are shared UTF-8 text files; `arm_files` replace or add files for each arm. Paths must be relative and cannot contain traversal components. Each attempt receives a fresh temporary directory. Checks run in declaration order with no shell; the first nonzero exit, timeout, or launch error ends that attempt. A successful attempt ends retries for that fixture and arm. `{python}` resolves to the current Python interpreter. `max_attempts` includes the initial attempt.

The returned `attempts` contain observed success and elapsed milliseconds for every attempt. `checks` contains each check's exit code, timeout status, elapsed time, and up to 2,048 characters of stdout and stderr with truncation flags. Child output goes to temporary files before bounded reading, so large logs do not accumulate in Julius process memory. Checks receive a small explicit environment without inherited API keys or other arbitrary caller variables. Token counts and USD cost are `null` because local subprocess checks do not measure model usage or provider billing. The paired `analysis` therefore reports only observed success, retry, and latency comparisons; token and cost savings remain `null`.

This is trusted local command execution, not a sandbox or an LLM quality benchmark. Temporary directories limit where fixture files are written by the runner, but child processes retain the caller's filesystem permissions and network access. Use only checks you trust. The runner does not call a model or make a network request itself. A broader quality claim requires representative frozen tasks, independently graded outcomes, and controlled runtime conditions.
