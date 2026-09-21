# Jev shadow Choice evaluation

`julius.jev_shadow_eval` scores already captured Choice answers against the frozen
`jev-policy-choice-pilot-v1` labels. Load the registration with
`load_frozen_registration()` and pass a tuple of `CapturedChoice` records to
`evaluate_replay()`. The module has no gateway, network call, or production action
path. Labels are pilot policy examples, not a measured quality benchmark.

The report identifies the registration by SHA-256, counts missing cases, provides
coverage and a three-action confusion matrix, and reports accuracy, confidence
calibration bins, and the binary correctness Brier score. An ineligible choice is
counted as incorrect. Calibration and Brier score describe the captured confidence
for exact policy-label agreement, not the probability of task success.

Auxiliary cost and token totals are `null` until every registered case has a
capture with that field. The known subtotals and unknown capture counts remain
visible; zero is only a recorded zero. Captures must be from a separate, already authorized run. This evaluator
never calls TypeSafe and never delegates a production decision.

`julius evaluate jev-shadow --state-file captures.json` exposes the same offline
evaluation from an installed executable. The file must be a JSON object with a
`captures` array of `CapturedChoice` objects; `{"captures": []}` reports zero
coverage and unknown aggregate cost without calling a model. Capture IDs must
match the packaged registration, and duplicates or extra cases fail validation.
