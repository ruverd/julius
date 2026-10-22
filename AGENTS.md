# Julius engineering rules

Julius is a TypeScript/npm fork of Trail-Code. This active stack replaces the earlier Python/Rust Julius product; see PROVENANCE.md for the pinned upstream source and archive.

- Write code identifiers, documentation, CLI output and commit messages in English.
- Use Node.js 20 or later, TypeScript and npm. Keep package-lock.json current.
- Build with `npm run build`; run inherited and new tests with `npm test` (node:test through tsx). Preserve native and WASM graph coverage in CI.
- The executable is `julius`, the package is `@ruverd/julius`, the exported engine is `Julius`, and local state belongs under `.julius`.
- Default operations must not contact telemetry collectors, cloud services or package registries. External services require explicit configuration or an explicit user command. Never embed production credentials or invent Julius service endpoints.
- Preserve upstream MIT copyright and source provenance. Historical names may remain in provenance and explicit migration documentation only.
- Never describe token estimates as provider measurements. Unknown values are null, not zero. Preserve negative savings. Never repeat an external operation just to measure it.
- Do not modify another worker's owned files without coordinating.
