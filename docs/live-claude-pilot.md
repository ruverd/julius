# Exploratory Claude Code pilot evidence

On September 21, 2026, Julius ran six frozen synthetic tasks through Claude Code 2.1.278 on macOS arm64. Three prompts were in English and three in Portuguese; the corpus included repetitive and compact Bash output. Each task ran once with the native baseline and once with the Julius safe `PostToolUse` hook, in fresh projects. The requested model was `haiku`; all twelve final client streams identified `claude-haiku-4-5-20251001`. The corpus SHA-256 was `98e2f2bad1638309e2ec310e603321192ee36f79ec3216be66fe168acdea09d4`, with arm order seed `20260921`. Cache state was uncontrolled. The configured limits were four turns, USD 0.02, and 90 seconds per session; a request already in flight could exceed the client USD limit.

| Client-reported session total across six tasks | Baseline | Julius safe hook |
| --- | ---: | ---: |
| Tasks passing strict answer and tool checks | 5/6 | 5/6 |
| Non-cached input tokens | 116 | 100 |
| Cache-read input tokens | 87,272 | 66,429 |
| Cache-creation input tokens | 13,140 | 19,369 |
| Output tokens | 2,781 | 3,185 |
| Client-estimated USD cost | 0.03917320 | 0.05754000 |
| Total wall-clock seconds | 46.89 | 61.85 |

The safe arm cost USD 0.01836680 more in these observed sessions. It also emitted 404 more output tokens. Those are **descriptive differences in whole-session totals**, not direct input or output savings attributable to a transform. The safe arm ended early on `count-en` with Claude result subtype `error_max_budget_usd` after one permitted Bash call; its client-estimated cost was USD 0.02177585. The baseline completed that task. For `words-en`, the baseline requested an unauthorized `printf ... | wc -w` command first; the `PreToolUse` gate denied it. It then ran the permitted command and answered `192`, but failed the predeclared one-command/no-unexpected-request criterion. The safe arm passed that task. Both failures remain in the six-task denominators and all reported cost totals.

The apparent difference in total input is dominated by changed trajectories, including one early stop, and cannot establish reduction in a comparable provider request. Julius still lacks a live before/after count of the exact sent request. This pilot was exploratory, tiny, and did not control provider cache state. It does not establish non-inferior quality, financial savings, a 20% direct-input reduction, or superiority over Headroom, RTK, or Context Mode. The full local streams and original report remain under the caller's temporary pilot directory; the repository records only this synthetic aggregate, without session IDs or local paths.
