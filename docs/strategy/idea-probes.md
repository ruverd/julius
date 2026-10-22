# Cheap idea validation before further implementation

These probes exercise existing code and tiny test-only protocol models. They add
no product behavior, provider calls, keys, agents, dependencies or host settings.
They are counterexample finders, not a coding benchmark or evidence of universal
savings. Results: [machine-readable report](idea-probes.json).

Developer reproduction (not part of the user coding workflow):

```sh
node --import tsx --test test/ideas.test.ts
node --import tsx scripts/experiments/ideas.ts
```

The probes also run with `npm test`. Temporary repositories are deleted afterward.
No build is needed for the focused experiment. Execution on the development machine
was under one second for the focused test run; this is an observation, not a limit.

## Decisions from the initial probes

| Hypothesis | Experiment | Observed offline tokens | Decision |
| --- | --- | --- | --- |
| Composition always saves | Existing two graph operations versus one investigation for the same known caller fact | 632 separate; 770 composed | Reject unconditional composition for tiny tasks. Test larger tasks before expanding the runtime. |
| Cache hit saves prompt tokens | Repeat an identical investigation; then add a previously absent caller | 457 cold; 457 warm; new caller invalidates | Reuse is verified computation reuse, not demonstrated token reduction. Do not build persistent storage on a token-savings assumption. |
| A preview preserves needed facts | Put a diagnostic outside the initial preview, then retrieve using a task-declared hint | Initial preview misses the fact; recovery succeeds | Budget compliance alone fails the quality criterion. Recovery is mandatory. |
| Selective recovery helps | Retrieve only the diagnostic from the frozen output | 2,482 full; 1,052 selected plus recovery | Advance this mechanism to unseen tasks, not automatic production approval. |
| Small budgets always help | Recover every original byte using bounded reads | 2,482 full; 5,720 across ten recovery reads plus preview | Reject this policy for all-content-required tasks. |
| Handoff can always send a delta | Test-only append protocol with fresh receiver, reset context, incorrect base and matching context | No token or performance claim | Require explicit context/base contract; otherwise send self-contained evidence. |

## Measurement boundaries

The tokenizer is `cl100k_base`. Composition uses the current Julius implementation,
not the original Trail executable. It counts operation schema discovery and
request/response envelopes. Common compact interface initialization cancels between
arms. Calls are scripted, not model-generated; model planning, corrections and
repeated conversation processing remain unknown. Both arms must expose the fixed,
independently specified caller fact. This is not full semantic equivalence of every
field or evidence that a model would act correctly.

Retrieval uses fixed output replay and counts request/result envelopes plus every
recovery. Interface and discovery are excluded in that separate probe. Its query
hint is fixed by the task, not derived from the resulting preview. Full recovery
must reproduce every byte. The negative case remains in the report.

Cache observations compare delivered report tokens only. They do not establish
speedup. The handoff policy is a small test model outside production; it assumes
explicit receiver state and tests the prerequisite, not live host support.

Provider usage, price and coding accuracy remain null. A lower local payload count
cannot establish a lower bill or equal coding quality.

## Gates before spending more engineering effort

1. Fail fast: missing required facts rejects a candidate even if token savings are
   large. Equal or higher token cost rejects that configuration for the fixture.
2. A passing fixture only permits another experiment. Do not ship a broader feature
   from these few synthetic examples.
3. Expand only selective recovery and promising composition sizes to a small,
   frozen held-out set: tiny tasks, large fan-out, ambiguous names, unindexed code,
   every-byte requirements and edits introducing new dependencies. Prepare answers
   independently before tuning policies.
4. Keep persistent shared memory, general execution plans and automatic delta
   suppression deferred until their prerequisites win controlled probes.
5. Only then run explicitly budgeted live trials on matched host/model/task versions,
   retaining failures and complete provider usage. Use the existing paired-trial
   importer; report uncertainty rather than inferring quality from payload counts.

Tests pin the quality gate, negative recovery result, missing-preview fact,
invalidation behavior and context-reset fallback. They intentionally do not assert
that every idea wins or that the current composition implementation must always lose.
