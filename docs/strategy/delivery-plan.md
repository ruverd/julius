# Julius investigation runtime: delivery and evaluation plan

Status: staged implementation. The first delivery adds two fixed investigation
recipes, process-local snapshot-validated reuse, structured budget selection and
paired usage-import contracts. See [implemented behavior](../investigations.md).
M0's actual upstream/model runners, generic M1 plans, persistent/fine-grained M2,
learned or cost-adaptive M3, M4 handoffs and M5 live trials remain open. No paid
experiment has been run.
Date: 2026-10-21. Context: [research study](research-study.md).

## Objective and decision rules

Reduce total tokens and financial cost per correctly completed coding task relative to pinned Trail-Code, without sacrificing useful correctness or simple installation. Prioritize eliminated intermediate work and validated reuse over increasingly lossy previews.

Provisional targets, not results: at least 30% lower aggregate provider-reported tokens and 20% lower aggregate cost in the held-out evaluation; no more than a 5 percentage-point success regression; no more than 20% p95 wall-time regression. Report each model and task stratum, not only the aggregate. If provider usage or comparable prices are unavailable, the corresponding claim is unproven.

These are product gates rather than statistical guarantees. A small pilot can reject a bad direction but cannot establish non-inferiority. If confidence intervals cannot resolve a gate, outcome is inconclusive and the default stays unchanged.

## Ordered milestones

| Milestone | Deliverable and likely code boundary | Exit evidence | Dependency |
| --- | --- | --- | --- |
| M0: baseline | Versioned task manifest, actual Trail runner, current Julius runner, usage importer; new evaluation scripts | Same task snapshots and checkers work for all arms; unknown usage preserved; failed runs retained | None |
| M1: composition | New investigation module; compact MCP discoverable operation; two deterministic recipes | Bounded plans match separate-call results; incomplete graphs remain explicit; all intermediate output accounted for | M0 |
| M2: validated reuse | Evidence store and conservative snapshot validation; later query dependencies | Cold/warm parity; additions, deletions, renames and concurrent edits invalidate correctly | M1 |
| M3: adaptive delivery | Policy around Economy rendering and recovery | Held-out improvement over fixed budgets; all-content and tiny-output workloads do not silently truncate | M1, M0 |
| M4: handoff | Evidence bundles and explicit receiver base/epoch contract | New agent and compaction tests receive self-contained evidence; supported delta mode remains correct | M2 |
| M5: product trial | Host capability/adoption report, retention, install/uninstall QA, full paired evaluation | Quality/cost gates resolved; packaged install works with no model/container dependency | M2, M3; M4 optional |

Each milestone produces a small reviewable change and report. Do not combine all phases into one rewrite. M4 ships only if supported hosts can satisfy its contract; lack of epoch support must not block local composition. Do not start a runtime rewrite in Rust or Python without a measured bottleneck.

## M0: experimental contract

Pin Trail source `b1211efd3eef0efa121b93800e5dd8e547aead77`, current Julius baseline, candidate commit, host version, model identifier, inference parameters, prompts, dependency lockfiles and task snapshots. Build the actual upstream executable. Preserve its useful semantics while explicitly disabling telemetry and unrelated network activity for the trial; disclose any harness changes. Never call an inherited-style schema fixture an upstream executable comparison.

Create six strata: failure localization, change-impact analysis, cross-file feature work, repeated investigation after a code change, agent handoff, and tiny/all-content-required tasks. Include at least three repositories and languages supported by the graph. Each task gets independent correctness checks prepared before optimization. Hidden tests assess actual patches; evidence questions use independently prepared facts. Never rely only on an LLM judge.

Use a disjoint development set of 12 tasks, two per stratum. Pilot 24 held-out tasks, four per stratum, with three repetitions per arm on one explicitly configured model/host. Four arms produce 288 runs: no helper, actual Trail, current Julius, candidate Julius. Freeze policy before the held-out pilot. Repeated runs of the same task are not independent tasks.

Randomize arm order, reset working trees and application caches, distinguish cold and warm conditions, and record provider cache hits rather than assuming control over provider caches. Warm reuse experiments form a separately reported stratum. Use sandboxed repositories and local services; external side effects must not be repeated as benchmark actions.

After the pilot, use observed task-level variance to size a larger independent confirmation set. Repeat on another model and a second host before broad compatibility claims. Paid trials need an explicit total spend cap, per-run token/time limit and stop behavior; if budget cannot support statistical confirmation, publish pilot evidence with that limitation.

## Metrics and accounting

Record success, failure reason, task completion time, provider usage categories, model/tool turns, discovery tokens, plan generation, retries, recovery, tool adoption, full-output fallbacks, stale-result detections, CPU time, index time and disk use. Record external command runs once in the trial arm that requested them; use deterministic recordings only for clearly labeled replay experiments.

Primary comparisons:

- Aggregate token reduction: `1 - sum(candidate total tokens) / sum(Trail total tokens)` on the same complete task set.
- Aggregate cost reduction: same formula on provider-reported or explicitly priced usage, keeping the measurement methods distinct.
- Cost per success: total arm cost including failed attempts divided by successful tasks; zero successes yields null, not zero cost.
- Success difference: candidate success rate minus baseline success rate, with a paired task-clustered confidence interval.

Provide task-level distributions and paired confidence intervals by resampling task IDs, keeping repeats clustered. Report mutually successful tasks as a secondary diagnostic only; selecting them as the primary population would hide regressions. Preserve negative savings, failed runs and timeouts. Disclose missing usage coverage; do not compute a supposedly complete total from partial provider data.

Run ablations against the same baseline: composition alone, reuse alone where possible, adaptive delivery alone, and the combined candidate. Handoff gets its own matched workload. This separates useful mechanisms from gains attributable only to smaller tool schemas.

## M1: first implementable slice

Start with `change-impact`: changed paths to symbols, callers/references, evidence spans and unresolved edges. Then `failure-localization`: captured diagnostic to symbol/file matches and nearby relevant source. Neither recipe automatically executes tests or declares root cause proven.

Define a versioned typed intermediate representation before execution. Validate references, cycles, types, limits and final projections. Operations must return structured values plus dependency metadata so M2 does not need to infer provenance from prose. Use existing graph functions after inspecting their contracts; retain native and WASM coverage.

Test semantic equivalence to separate operations, output budgeting, nonexistent symbols, unsupported syntax, dynamic dispatch uncertainty, cancellation, cycles, fan-out, traversal outside repository and concurrent changes. Compare full end-to-end model use, not only a human-authored ideal plan. Expose the feature experimentally until it wins the pilot.

## M2–M4: correctness before aggressive reuse

Start with whole-snapshot invalidation. Refine only when validation overhead or invalidation frequency is measured. Mutation suite must cover a new caller in a previously unmatched file, deleted symbol, path rename, changed lockfile/configuration, dirty worktree, generated source, parser version, branch switch and edits during execution.

Keep deterministic facts and model annotations separate. An annotation can be retrieved as attributed historical context, never promoted to verified current evidence. Cache keys include scope and engine semantics; cross-repository/worktree collisions must be impossible.

Adaptive selection uses development traces only. Compare fixed budgets, complete output and a deterministic policy with explicit fallback. Charge all recovery. Include repeated searches and all-content recovery as adverse cases.

For handoff, test two receivers, missing base, stale base, context reset, replayed acknowledgment and expired evidence. If context retention is not observable, return a compact self-contained bundle every time. Never claim that a receiver remembers text because another agent read it.

## Packaging and release gates

Keep `julius`, `@ruverd/julius`, `.julius`, English interfaces and upstream attribution. No default network access. Add bounded storage retention, explainable status and explicit experimental toggles. Preserve existing installer rollback and unrelated configuration. Verify packed installation in isolated home directories on macOS/Linux/Windows where supported; include Node and WASM CI coverage.

Run `npm run build`, inherited/new `npm test`, existing offline economy benchmark and milestone-specific evaluation. Documentation must distinguish current capability, experimental capability and proposed work. Publish successful and adverse cases with reproducible manifests and redacted logs. Promotion requires evidence, not completion of a feature checklist.

## Separate frontier track

Only start after M0 and a separate hardware/time budget. Reproduce one self-hosted baseline before integrating anything: ReCache for schema invocation or EfficientAgent for multi-agent prefix reuse. Measure quality, GPU/host memory, prefill computation and latency separately from token counts and financial cost. Do not add their percentages to client-side savings.

RecursiveMAS requires a distinct model/training experiment. Compare text communication against its trained link setup on matched tasks and compute budget; test coding transfer rather than assuming mathematical benchmark performance transfers. A local evidence-reference protocol is not a substitute for that reproduction.

Proceed only if the experiment adds a capability unavailable in the portable product and the infrastructure burden fits an explicitly chosen deployment. Keep the ordinary npm installation independent.

## Immediate next deliverable

Implement M0 task/usage contracts and the M1 change-impact recipe behind an experimental flag. Produce one paired trace showing every model-visible message and independent task outcome. That trace decides whether to expand the runtime, improve integration, or abandon the mechanism before building the memory system.
