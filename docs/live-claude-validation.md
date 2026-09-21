# Claude Code live integration evidence

On September 21, 2026, Claude Code `2.1.278` on macOS arm64 ran four isolated synthetic probes against the locally built Julius module. These probes used an ephemeral directory, `--restricted`, `--strict-mcp-config`, `--no-session-persistence`, bounded turns and spend, and a Julius-only MCP configuration. No repository content, private prompt, or credential was sent in the test prompt. Claude's existing authenticated client handled its own authorization; Julius did not copy its session credentials.

| Probe | Observed result | Limit |
| --- | --- | --- |
| Recovery MCP | Claude called `mcp__julius-recovery__restore_artifact` and returned the exact synthetic original. CLI reported 4 non-cached input tokens, 8,479 cache-creation input tokens, 149 output tokens, and USD 0.07763375. | Confirms that this client session could connect and call the tool. Does not show input reduction. |
| Hook attempt 1 | Claude called Bash and the recovery tool; Julius recorded one candidate transform. Final request failed with a provider safeguard error. CLI reported USD 0.12103025. | Failed run remains part of validation evidence. It cannot establish a completed task or savings. |
| Hook attempt 2 | Claude called Bash, Julius recorded one candidate transform attributed to task `hook-probe`, and Claude called recovery with the exact artifact ID created by the hook. Final response succeeded (`Done.`). CLI reported USD 0.02264295. | Confirms this Bash `PostToolUse` replacement and project-scoped restoration path on one synthetic case. The candidate event remains `sent=false` because Julius has no per-request acknowledgement from Claude's provider transport. No sent-request token reduction or task-quality result is claimed. |
| Bounded print observation | `julius run --agent claude --prompt-file ... --model haiku --max-budget-usd 0.05` returned the exact synthetic marker. The client's final result identified `claude-haiku-4-5-20251001`, 4,221 normalized input tokens, 57 output tokens, and USD 0.00555875. Julius wrote one `session_delta` usage event with task identity and client-estimate cost provenance. | This is client-reported session usage. It is not a provider invoice, a per-call trace, or an input-savings measurement. The raw prompt was not stored in the Julius event. |

The second hook probe used Haiku; the first used the client's default model. The test allowed only a synthetic `printf` Bash command and the Julius recovery tool. The print observation used restricted mode and no built-in tools. These are client-integration acceptance checks, not a paired optimization benchmark. The four CLI-reported costs total USD 0.22686570 for validation activity; they are not a Julius savings figure or a verified invoice.

## One bounded baseline/safe pair

On the same date, `run_claude_pair` ran one further synthetic task under Claude Code `2.1.278` with requested `haiku`, four turns, USD 0.05, and 90 seconds as **per-arm** caps. Both arms used fresh projects and the same fixed 96-line Bash command. Both returned `96`, one Bash request, and one Bash result; neither called recovery. The client reported actual model `claude-haiku-4-5-20251001` for both arms.

| Client-reported session measure | Baseline | Julius safe hook |
| --- | ---: | ---: |
| Non-cached input tokens | 18 | 18 |
| Cache-read input tokens | 13,292 | 13,294 |
| Cache-creation input tokens | 3,320 | 5,425 |
| Output tokens | 477 | 667 |
| Client-estimated USD cost | 0.00788220 | 0.01146365 |
| Wall-clock seconds | 11.05 | 11.10 |

The safe arm cost USD 0.00358145 more and produced 190 more output tokens. These are observed session totals, not a provider invoice or a controlled estimate of savings. The safe arm created an original artifact and its ID appeared in the client stream. The stored original matched all 96 expected lines but omitted the command's trailing newline: strict byte comparison is false, comparison after removing exactly that final newline is true. The artifact receipt records both checks. No sent-request before/after token count exists for this pair, so direct input reduction is **unavailable**. One pair cannot establish quality equivalence, causal economy, or a general loss; it does show that enabling this hook was not cheaper in this observed run. This case should remain visible when evaluating cache-aware policy.

The [Claude CLI reference](https://code.claude.com/docs/en/cli-reference) documents the temporary settings and MCP flags, restricted mode, non-persistent print mode, turn and spend caps, and tool controls used here. The [hooks reference](https://code.claude.com/docs/en/hooks) defines `PostToolUse`; the [MCP guide](https://code.claude.com/docs/en/mcp) defines the client connection and tool naming. Future versions require another live acceptance test. The local `doctor` subprocess probe alone remains weaker evidence because it does not start Claude.
