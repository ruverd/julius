# Synthetic Jev shadow pilot: observed result

Date: September 21, 2026. Scope: five synthetic metadata cases sent once to
TypeSafe's System One endpoint in shadow mode. The sixth frozen case contained
protected content and was resolved deterministically as `keep`, with no Jev
request. The [registration and runner were committed before the
calls](https://github.com/ruverd/julius/commit/b3c854c). The
[capture file](evidence/jev-shadow-pilot-v2.json) contains choices, confidence,
the responding model, provider-reported token counters, and modeled cost; it
contains no API key, prompt, path, or raw response.

The run pinned `jev-1.13.0`. It used the [published September 21, 2026 model
price](https://docs.typesafe.ai/models) of USD 0.042 per million input tokens
and zero per output token, plus the documented 64,000-token context length as
an assumed per-call maximum. Five calls implied a modeled maximum of USD
0.01344, below the run's USD 0.02 budget. This was a pre-call assumption, not
a provider-enforced spending cap or a verified invoice. A new journal was
written before each external attempt. No retry was made.

| Frozen case | Label | Jev choice | Confidence | Match |
| --- | --- | --- | ---: | --- |
| Recoverable short context | keep | compress | 0.52 | No |
| Missing recoverable source | keep | keep | 0.24 | Yes |
| Recoverable large context | retrieve | compress | 0.69 | No |
| Repeated large context | compress | compress | 0.86 | Yes |
| Local model, long context | compress | compress | 0.77 | Yes |

All five optional cases returned the pinned actual model and complete usage.
The offline replay reproduced **3/5 label matches**, 1,964 provider-reported
input tokens, 176 provider-reported output tokens, and USD 0.000082488 in
**price-modeled** auxiliary cost. The Julius ledger independently shows five
observed auxiliary calls and the same modeled-cost subtotal. One correct answer
had confidence 0.24; one incorrect answer had confidence 0.69. Five synthetic
cases cannot calibrate confidence or prove task quality. No production action
changed, and these observations do not justify active Jev routing.

Replay locally, without a model call:

```sh
julius evaluate jev-shadow --state-file docs/evidence/jev-shadow-pilot-v2.json
```

The replay must report registration SHA-256
`668cd4459f1fec4734960a533ee7c9acc03806595a23b754dedcc17f564ae576`,
five captures, one deterministic bypass, and no missing optional cases. The
capture file was checked against the five local journal capture records. It
does not prove broader Jev version compatibility, causal token savings,
quality on real coding tasks, or billing reconciliation.
