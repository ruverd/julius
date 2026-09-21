# Controlled Claude Code synthetic pair

`julius.claude_pair.run_claude_pair` is an explicit, opt-in two-session evaluation. It runs the same frozen prompt and harmless `printf` task in two fresh temporary projects under a caller-chosen work directory. The baseline has no Julius `PostToolUse` replacement. The safe arm adds the existing Julius safe hook. Both arms have the same recovery MCP server, model selection, tool permissions, turn limit, USD budget, and wall-clock timeout. Each arm has its own Julius data directory, so artifacts and ledger events cannot mix.

The task emits 96 identical synthetic lines and asks for the exact answer `96`. A passing arm needs a complete Claude Code final result, that exact answer, one fixed Bash request, its tool result, and no unexpected tool requests. The harness uses `--restricted`, `--tools Bash`, `--strict-mcp-config`, `--permission-mode dontAsk`, `--permission-prompts none`, and an exact `--allowedTools` Bash rule. A temporary `PreToolUse` hook denies any different command or action tool and atomically admits the fixed command at most once. The only other allowed action tool is `mcp__julius-recovery__restore_artifact` for an ID in that arm's project-scoped recovery server; Claude Code's `EndConversation` completion tool remains available. The safe arm uses the existing `build_launch_plan` configuration for `PostToolUse`; the harness does not change user settings.

Call the API from an environment with Julius and its native extension installed and Claude Code authenticated. It makes **two real external Claude Code sessions** only when called, never on import:

```python
from pathlib import Path
from julius.claude_pair import run_claude_pair

report = run_claude_pair(
    work_dir=Path("./claude-pair-runs"),
    project_id="synthetic-evaluation",
    max_turns=3,
    max_budget_usd=0.05,
    timeout_seconds=60,
    model="haiku",
)
print(report["run_dir"])
```

Claude Code must support the flags used here, including `--restricted` (v2.1.248+), `--permission-prompts none` (v2.1.259+), and `--include-hook-events`. The CLI [reference](https://code.claude.com/docs/en/cli-reference) defines those flags, print mode, stream JSON, tool restriction, strict MCP config, and the per-session limits. Its USD cap stops further calls after the limit is reached; it is not a guarantee that an in-flight call cannot cross the limit. The [permissions reference](https://code.claude.com/docs/en/permissions) documents exact Bash rules, `dontAsk`, and hook decisions. The [hooks reference](https://code.claude.com/docs/en/hooks#posttooluse-decision-control) documents `updatedToolOutput` and says it changes the result Claude sees after the tool has already run.

Restricted mode still loads organization-managed settings. Their policies or hooks can affect either arm, so inspect the saved stream and client configuration if a run behaves unexpectedly.

The returned report and `report.json` contain one record per arm with client-reported final session token counters, client-reported cost, elapsed wall time, model, exit state, answer, and tool observations. Unknown counters and costs remain `null`. `stdout.jsonl`, `stderr.txt`, and `result.json` persist for each arm, including failures and timeouts. The safe arm also lists any Julius artifact that still exists after the session, whether its restored original exactly matches the fixed synthetic output, and whether its ID appeared in the client stream. A matching artifact is evidence that the hook saved an original; a stream ID is additional visibility into the client's emitted events. Neither proves the replacement entered a model request. One pair is descriptive and cannot establish causal token or cost savings. The harness does not record a realized savings claim or send any model request during offline report parsing.
