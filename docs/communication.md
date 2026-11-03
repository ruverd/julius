# Communication voices

This repository vendors Kevin v0.2.0 as a portable skill. Codex loads
`.agents/skills/kevin`; Claude Code, Cursor and Grok CLI use project skill links.
No model API, Node dependency or Rust executable is required for direct skill use.
The checked-in `.kevin/config.json` contains public starter settings only.

Default voice: `tony-stark`, a concise engineer with optional dry humor.
Code review: `professional-reviewer`. Serious or uncertain contexts disable humor.
Explicit language and style requests take precedence; forge text remains English.
Facts, uncertainty, severity and test results must survive any rewrite.

With the optional Kevin CLI installed:

```bash
kevin voices
kevin voice default minimalist
kevin voice create my-reviewer --description "A precise, collaborative reviewer"
kevin rule set reviews --task review --voice professional-reviewer
kevin review --request review-request.json --prompt > review-prompt.txt
```

Voice creation starts a calibration interview; review the proposed voice before
saving it. Rules can also match supplied Slack workspace/channel or recipient IDs.
Memory is written only on explicit request and may be global or scoped to a voice.
Never commit private memories or writing samples. Use an ignored local config and
explicit `--config` when running the CLI with personal settings.

A skill install does not intercept CI output. A model-powered pipeline must add
the Kevin prompt before generating human-facing prose. Keep protocol JSON,
verdicts, evidence, permission gates and deterministic renderers unchanged.
See [Kevin CI example](https://github.com/ruverd/kevin/tree/main/examples/code-review-project).
