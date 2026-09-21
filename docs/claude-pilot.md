# Bounded bilingual Claude Code pilot

`julius.claude_pilot.run_claude_pilot` is an explicit, opt-in evaluation over six frozen synthetic tasks. English and Portuguese prompts cover repetitive and compact Bash output. Every task asks for an exact decimal answer. Each task runs once with the baseline configuration and once with the Julius safe `PostToolUse` hook. The arm order is shuffled from a recorded seed. Each attempt has a fresh project and Julius data directory.

```python
from pathlib import Path
from julius.claude_pilot import run_claude_pilot

report = run_claude_pilot(
    work_dir=Path("./claude-pilot-runs"), project_id="pilot",
    max_turns=3, max_budget_usd=0.05, timeout_seconds=60,
    order_seed=20260921, model="haiku",
    client_version="observed Claude Code version",
    cache_state="fresh profile",
)
print(report["run_dir"])
```

This call makes twelve real external Claude Code sessions. It requires an authenticated Claude Code installation supporting the restricted and print-mode flags described in [the pair runner](claude-pair.md). No model call occurs on import, while grading, or while reading the saved report. Per-arm turn, USD, and wall-time limits are explicit. The USD cap is a client stop condition and may be exceeded by an in-flight call.

The CLI exposes the same explicit run. `--execute`, `--project`, `--work-dir`, `--order-seed`, `--max-budget-usd`, and `--timeout-seconds` are required; `--max-turns` defaults to 4. The command prints the report, including its `run_dir`.

```sh
julius evaluate pilot --execute --project pilot --work-dir ./claude-pilot-runs --order-seed 20260921 --max-budget-usd 0.05 --timeout-seconds 60 --max-turns 3 --model haiku
```

Analyze a saved complete report offline with:

```sh
julius evaluate pilot-report --state-file ./claude-pilot-runs/claude-pilot-<uuid>/report.json
```

The command allowlist contains only the frozen harmless `printf` fixtures. A temporary `PreToolUse` hook checks exact command bytes and permits the command at most once. The only other admitted action tool is project-scoped Julius artifact recovery. Passing requires a complete client result, the exact answer, exactly one allowed Bash request and successful tool result, and no unexpected tool requests. A wrong answer or failed session remains in the report.

`report.json` records task order, one-based execution sequence, seed, requested model, per-arm limits, task metadata, and every attempt. It includes a SHA-256 hash of the canonical JSON array of frozen tasks. Each task and attempt includes a SHA-256 hash of that task's canonical JSON object. Canonical objects contain `id`, `language`, `command`, `output`, `answer`, and `prompt`; JSON is serialized with sorted keys, compact separators, and UTF-8 without ASCII escaping. These hashes make changes to any fixture or prompt visible. Caller-supplied `client_version` and `cache_state` are stored on the report and each attempt; omitted values remain null (unknown).

Before the first session, the runner writes read-only `registration.json` with the full task manifest, corpus hash, seeded order, model, client version, cache state, and per-arm limits. It then atomically updates `report.json` after each attempt. An interrupted run therefore retains the original denominator and all completed attempts; its `complete` field remains false. Each attempt includes the client's final result subtype, including budget-limit errors when the client reports them.

Each attempt retains final client-reported session input/output/cache counters, cost, observed model, wall time, answer, errors, tool evidence, and paths to saved stdout/stderr. Missing measurements stay null. Those counters are whole-session totals; differences between arms are descriptive and are not direct Julius input/output savings. The report makes no causal savings claim. The small sample, client version, cache state, model behavior, and ordering limit interpretation.

`analyze_claude_pilot_report(report)` runs offline. It requires `complete: true` and rejects missing tasks or arms, incorrect hashes, a sequence that disagrees with the recorded random seed, or an attempt whose recorded pass grade disagrees with its completion, exact answer, Bash request/result counts, and unexpected-request count. It also verifies per-attempt client version and cache state match the report. It maps each session to `evaluation.Trial` and includes failed tasks in the denominator. Anthropic's final usage fields are normalized to total input as noncached `input_tokens` plus cache-read and cache-creation input tokens; separate cache fields remain available. If any required component is unknown, total input remains null. The result includes all original attempts, task trials, descriptive paired differences, and paired bootstrap intervals. It reports `same_observed_model` only when every attempt has the same single observed model; otherwise it reports `mixed_or_unknown`. Those differences are whole-session observations and do not establish direct Julius savings or a causal effect.
