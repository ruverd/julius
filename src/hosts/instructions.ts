/** Canonical Julius instructions, wrapped in each coding host's native format. */
import type { Brand } from '../brand.js';
import { juliusSpelling } from '../claude/skill-template.js';

function inName(text: string, name: Brand): string {
  return juliusSpelling(text);
}

export function instructionBody(name: Brand = 'julius'): string {
  return inName(juliusBody(), name);
}

function juliusBody(): string {
  return `## Julius — repo context graph

This repo is indexed in \`julius/\`: small linked markdown nodes that explain each
system and carry exact file:line spans, kept in sync with the code through git.

For ANY task here — understanding how something works, finding where code lives,
or scoping a change — get context from the graph before grepping or opening
source files. Re-ask freely (it's cheap) and reuse literal identifiers you
already have (symbol, error string, file name) as the query. New to this repo?
Run \`julius map\` first — a token-budgeted orientation (dir clusters, hubs,
hotspots), no LLM, no key.

- Run \`julius ask "<your question>" --source\` → ranked nodes with the relevant
  code spans inlined (each hit's ≤8-line crux by default; \`--full\` for whole
  definitions when the crux isn't enough). Match the tool to the task shape:
  for understanding or editing, the top node IS the answer — cite its
  \`covers:\` file:line spans and edit straight from \`--source\`. For
  exhaustive tasks ("every occurrence / every caller of this pattern"), ranked
  results are top-N, not complete — run \`julius grep "<literal>"\` instead
  (exhaustive over indexed files, grouped by enclosing symbol), falling back
  to raw \`grep -rn\` only for unindexed files.
- \`julius skeleton <file>\` → every definition's signature + span, ~10× cheaper
  than reading the file; use it to skim an API surface.
- \`julius callers <symbol>\` gives precomputed, exact edges — who calls this.
  Add \`--direction out\` for what it calls, or \`--depth N\` to walk
  transitively for the full blast radius. For structural questions, skip
  ranking and use this directly.
- Or browse: \`julius/INDEX.md\` lists every node; follow the links.
- Monorepos and folders of multiple repos rank fairly across sub-projects —
  hits carry \`[scope/]\` labels naming which one they're from. Narrow with
  \`julius ask "<task>" --in <scope>/\` once you know where you're working.

If a returned span is truncated ("+N more lines"), open the file at that exact
range before finalizing. Only open source files when a node genuinely lacks a
needed detail, and then at the exact file:line the node points to — never
re-read whole files.

After big code changes, refresh the graph with \`julius build\` (deterministic,
no API key, $0).`;
}

export function cursorRule(name: Brand = 'julius'): string {
  return inName(`---
description: Use the Julius context graph in julius/ before exploring source
alwaysApply: true
---
${juliusBody()}
`, name);
}

export function kiroSteering(name: Brand = 'julius'): string {
  return inName(`---
inclusion: always
---
${juliusBody()}
`, name);
}

export function windsurfRule(name: Brand = 'julius'): string {
  return inName(`${juliusBody()}
`, name);
}
