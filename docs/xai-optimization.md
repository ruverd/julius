# xAI Responses optimization candidates

`prepare_optimized_request` builds an offline candidate from a caller's xAI Responses request. It accepts array `input` and considers only string `output` in documented `function_call_output` items. It copies the request, preserving `call_id`, roles, instructions, tools, model, and continuation fields. Other input shapes fail closed. The caller's object is unchanged and no request is sent.

A candidate requires an explicit safe policy, project-scoped original stored in `ArtifactStore`, successful readback, a supplied `julius_restore_artifact` function definition, and an explicit assertion that the handler is available. The candidate records heuristic estimates and `realizedSavings: null`. No provider usage or billed savings is inferred. Failed or ineligible transformations retain their original output.

The preparation result is **candidate only**. A function definition and handler assertion do not establish that a raw single-send xAI call can fulfill a later restore call. Do not enable safe-mode dispatch until the client implements and tests a complete function-call loop, including restore execution and Responses continuation with `previous_response_id`. An unavailable or expired original must prevent use of the candidate. Fixture tests do not establish live xAI compatibility.

The request shape follows [xAI's function calling guide](https://docs.x.ai/developers/tools/function-calling), which shows `input=[{"type":"function_call_output","call_id":...,"output":...}]` for Responses continuation.
