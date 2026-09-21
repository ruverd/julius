# Small repository pilot: observed runs

On September 21, 2026, Julius ran two of the four frozen [repository tasks](repo-task-pilot.md) against Claude Code 2.1.278, requesting Haiku. Each task had a fresh baseline session and a fresh safe-hook session. The English bug-localization task and Portuguese code-comprehension task both passed the exact answer and one-command tool-evidence checks in both arms. The observed model in all four sessions was `claude-haiku-4-5-20251001`.

| Task | Baseline result and client-estimated USD | Safe-hook result and client-estimated USD |
| --- | --- | --- |
| `bug-en` | Pass; 0.00713685 | Pass; 0.00722955 |
| `flow-pt` | Pass; 0.00448755 | Pass; 0.00496150 |
| Total | 2/2; 0.01162440 | 2/2; 0.01219105 |

The safe arm cost **USD 0.00056665 more** in client estimates. Its client-reported session totals were 29,704 input tokens and 1,135 output tokens, versus 29,671 input and 1,029 output for baseline. These are whole-session observations, including cache activity and auxiliary work. They are not direct sent-request reductions, provider invoices, or estimates of causal task savings. No restoration call occurred. The tiny source files had no repetitive output eligible for the current safe compressor, so this run does not exercise a useful compression case.

Both run directories contain pre-execution `corpus-registration.json`, `report.json`, and separate raw client streams. The frozen corpus SHA-256 was `61c8b1a42771a5b6763973a0f803756501b8f14aa7f0abaa93e591a236f90a4e` in both. Raw streams remain outside this repository under `/private/tmp/julius-repo-task-pilot-20260921/`; they may contain client metadata and are not public artifacts. The pilot ran each task baseline first, did not control cache state, and contains only one trial per arm. It establishes narrow workflow acceptance, not quality non-inferiority or financial savings.
