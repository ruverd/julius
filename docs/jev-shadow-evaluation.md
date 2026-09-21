# Jev shadow Choice evaluation

`julius.jev_shadow_eval` scores already captured Choice answers against the frozen
`jev-policy-choice-pilot-v2` labels (schema version 2). Load the registration with
`load_frozen_registration()` and pass a tuple of `CapturedChoice` records to
`evaluate_replay()`. The module has no gateway, network call, or production action
path. Labels are pilot policy examples, not a measured quality benchmark. The
registration hash changes because the frozen records now include typed state and
evaluation mode.

Each case carries only bounded metadata: `input_tokens`,
`estimated_reduction_tokens`, `artifact_recoverable`,
`has_protected_content`, `model_local`, and `repetitive_content`. Unknown keys,
wrong types, negative token counts, and token counts above 1,000,000,000 fail
registration validation. These are illustrative estimates, not provider
measurements. The protected-content case is `deterministic_only`; it requires no
Jev call or capture. The other five are `optional_jev_shadow` cases. Their state
is available as `case.state.model_dump()` to an explicitly authorized runner.

The report identifies the registration by SHA-256, counts missing shadow cases,
provides coverage over the five optional shadow cases and a three-action confusion
matrix, and reports accuracy, confidence
calibration bins, and the binary correctness Brier score. An ineligible choice is
counted as incorrect. Calibration and Brier score describe the captured confidence
for exact policy-label agreement, not the probability of task success.

Auxiliary cost and token totals are `null` until every optional shadow case has
a capture with that field. The known subtotals and unknown capture counts remain
visible; zero is only a recorded zero. Captures must be from a separate, already authorized run. This evaluator
never calls TypeSafe and never delegates a production decision.

`julius evaluate jev-shadow --state-file captures.json` exposes the same offline
evaluation from an installed executable. The file must be a JSON object with a
`captures` array of `CapturedChoice` objects; `{"captures": []}` reports zero
coverage and unknown aggregate cost without calling a model. Capture IDs must
match an optional shadow case, and duplicates, deterministic-only captures, or
extra cases fail validation. `planned_cases` remains six;
`planned_shadow_cases` is five and `deterministic_only_case_ids` lists the bypass.

An explicit synthetic live pilot can call the five optional cases once:

```sh
TYPESAFE_API_KEY=... uv run --no-sync python scripts/run_jev_shadow_pilot.py \
  --execute --journal-dir /tmp/julius-jev-run-1 --data-dir /tmp/julius-jev-ledger \
  --input-usd-per-million 0.042 --max-input-tokens-per-call 64000 \
  --total-budget-usd 0.02 --price-source typesafe-public-model-page \
  --price-date 2026-09-21
```

The example uses TypeSafe's [published Jev 1.13 price and context
length](https://docs.typesafe.ai/models), checked September 21, 2026. Those
inputs are **assumptions**, not a provider-enforced charge limit or a verified
invoice. The script rejects the run if five times the modeled per-call maximum
exceeds the budget, pins `jev-1.13.0`, journals the registration before calls,
and writes an `attempting` marker before every external request. It stops on
unknown cost, model mismatch, bound violation, or a failed call. Never resume
an ambiguous attempt by rerunning the same journal; inspect its ledger and
journal first. The protected-content case uses a deterministic keep decision
and makes no Jev call. Captures contain typed metadata, counts, choice, model,
and modeled cost, not the API key or raw prompts. The result measures agreement
with five synthetic labels and does not validate production task quality or
calibrate confidence for target workloads.
