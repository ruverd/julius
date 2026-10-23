---
title: Review staged provenance and SDK guard check findings
author: Ruver
date: 2026-10-23
id: l-936fd3be
branch: perf/cold-start-index-reuse
touches:
  - src/graph/provenance.ts
  - test/cold-start.test.ts
  - test/engine-lazy-provider.test.ts
  - test/investigation-index-reuse.test.ts
  - docs/strategy/cold-start-validation.json
---

## Decided
The staged v0.24.2 scan adds findings in src/graph/provenance.ts, three regression tests, and docs/strategy/cold-start-validation.json. Those findings are also lexical false positives. The helper derives cryptographic verification from stored graph and configuration contents. Tests intentionally reject forbidden imports, serve local fake provider responses, and exercise stale-index rejection. The JSON contains diagnostic measurements. None reintroduces the rejected runtime behavior. Together with the changelog and harness findings, all ten findings were reviewed and accepted with justification in the PR.

## Tried and ruled out
Treating isolated words in test names, fixture operations, imports, or JSON descriptions as runtime semantics would incorrectly reject the regression guards themselves.

## Watch out
Retain exact error messages in the negative SDK guard and full stale-index regression coverage. A scanner exception must be supported by actual code review and test results.
