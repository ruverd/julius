# Offline fixture replay

`julius.evaluation_runner.replay_paired_fixtures` aggregates caller-supplied task attempts and passes complete arm totals to the paired analyzer. It does not execute tasks, call models, or alter production state. A `FrozenFixture` binds a task ID and JSON snapshot to a SHA-256 fixture ID. Both arms must use every supplied fixture ID. Each arm records contiguous attempts beginning at zero; unsuccessful attempts and retries remain in the returned attempt list and in the totals. A successful attempt ends that arm's task run.

Each `Attempt` requires an outcome and explicit values or `None` for input, output, cache-read, cache-write, auxiliary tokens, USD cost, and latency. Unknown measurements propagate as null totals; zero means a measured zero. Savings retain the baseline-minus-candidate sign. The analyzer reports descriptive paired bootstrap intervals, subject to its documented limits.

This is a replay harness, not a benchmark result. Fixture tests only verify accounting and validation. A quality claim needs independently selected frozen tasks, consistent runtime and cache conditions, actual observed attempt data from both arms, and independent outcome grading. The caller is responsible for recording those observations; this module cannot infer them.
