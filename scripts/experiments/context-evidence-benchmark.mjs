import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import { lstatSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, relative, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { ECONOMY_ENCODING, economyTokens } from '../../dist/economy/index.js';
import { repoPlace } from '../../dist/notes/home.js';
import { tokenize } from '../../dist/ask/index-file.js';
import { evidenceLines } from '../../dist/economy/evidence-transport.js';
import { cases } from './context-evidence-cases.mjs';
import { historicalCases, historicalPlan } from './context-evidence-history.mjs';

const cli = fileURLToPath(new URL('../../dist/bin/julius.js', import.meta.url));
const onlyBaseline = process.argv.includes('--baseline-only');
const history = process.argv.includes('--historical');
const holdout = process.argv.includes('--holdout');
const marginalHoldout = process.argv.includes('--marginal-holdout');
const transportHoldout = process.argv.includes('--transport-holdout');
const namedSourceHoldout = process.argv.includes('--named-source-holdout');
const directed = holdout || marginalHoldout || transportHoldout || namedSourceHoldout || process.argv.includes('--directed');
const formatLines = process.argv.includes('--format-lines');
const transportControl = process.argv.includes('--transport-control');
const preferNext = process.argv.includes('--prefer-next');
const focusEvidence = process.argv.includes('--focus-evidence');
const sameDelivery = process.argv.includes('--same-delivery');
const reverse = process.argv.includes('--reverse');
const caseName = process.argv.find(arg => arg.startsWith('--case='))?.slice('--case='.length);
const bulmaRepo = process.argv.find(arg => arg.startsWith('--bulma-repo='))?.slice('--bulma-repo='.length);
const priorCli = process.argv.find(arg => arg.startsWith('--prior-cli='))?.slice('--prior-cli='.length);
const defaultCli = process.argv.find(arg => arg.startsWith('--default-cli='))?.slice('--default-cli='.length);
const scratch = mkdtempSync(join(tmpdir(), 'julius-context-benchmark-'));
const wire = value => `${JSON.stringify(value)}\n`;
const count = text => {
  try { return economyTokens(text); }
  catch (error) { if (error.message.startsWith('Exact token count unavailable')) return null; throw error; }
};
const sum = values => values.includes(null) ? null : values.reduce((total, value) => total + value, 0);

function put(path, content) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content);
}

function prepare(fixture, lane) {
  const repo = join(scratch, fixture.name, lane, 'repo');
  const home = join(scratch, fixture.name, lane, 'home');
  mkdirSync(repo, { recursive: true });
  mkdirSync(home, { recursive: true });
  if (fixture.historical) {
    const archive = execFileSync('git', ['-C', fixture.repo, 'archive', fixture.sha], { maxBuffer: 64 * 1024 * 1024, env: { ...process.env, GIT_NO_LAZY_FETCH: '1' } });
    execFileSync('tar', ['-x', '-C', repo], { input: archive });
  }
  execFileSync('git', ['init', '-q', repo]);
  const env = fixture.historical
    ? { PATH: process.env.PATH, SystemRoot: process.env.SystemRoot, TMPDIR: process.env.TMPDIR, TEMP: process.env.TEMP, TMP: process.env.TMP }
    : { ...process.env };
  Object.assign(env, { HOME: home, USERPROFILE: home, JULIUS_HOME: join(home, '.julius'), XDG_CONFIG_HOME: join(home, '.config') });
  for (const [path, content] of Object.entries(fixture.files ?? {})) put(join(repo, path), content);
  if (fixture.personal) put(join(repoPlace(repo, env).dir, 'notes', 'personal.md'), fixture.personal);
  return { repo, env };
}

async function client(repo, env, binary, run) {
  const child = spawn(process.execPath, [binary, 'mcp', repo], { cwd: repo, env, stdio: ['pipe', 'pipe', 'pipe'] });
  const exited = once(child, 'close');
  const output = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
  const record = [];
  let id = 0;
  let errors = '';
  child.stderr.on('data', data => { errors += data; });
  const request = async (method, params, phase, allowError = false) => {
    const json = wire({ jsonrpc: '2.0', id: ++id, method, params });
    child.stdin.write(json);
    const reply = await output.next();
    assert.ok(!reply.done, errors || 'MCP closed before responding');
    const parsed = JSON.parse(reply.value);
    assert.equal(parsed.id, id);
    assert.ok(parsed.result && (allowError || !parsed.result.isError), JSON.stringify(parsed));
    record.push({ phase, request: json, response: `${reply.value}\n` });
    return parsed.result;
  };
  const notify = (method, phase) => {
    const request = wire({ jsonrpc: '2.0', method });
    child.stdin.write(request);
    record.push({ phase, request, response: '' });
  };
  const timeout = setTimeout(() => child.kill(), 120_000);
  try { return await run({ request, notify, record }); }
  finally { clearTimeout(timeout); child.stdin.end(); child.kill(); await exited; }
}

function visible(value) {
  if (!value.startsWith('{')) return value;
  const { content, format } = JSON.parse(value);
  return format === 'utf8' ? content : '';
}

function noteText(content) {
  const bodyStart = content.indexOf('\n---\n', 4) + 5;
  const raw = content.slice(bodyStart);
  const leading = raw.length - raw.trimStart().length;
  return { body: raw.trim(), offset: content.slice(0, bodyStart + leading).split('\n').length - 1 };
}

function quote(path, kind, from, to, body) {
  return `${kind} ${JSON.stringify(path)} ${kind === 'note' ? 'body ' : ''}L${from}-L${to}\n${body}`;
}

function passage(text) {
  const data = decodeEvidence(text);
  if (data.hits) return data.hits.filter(hit => hit.format === 'utf8').map(({ evidence, content }) =>
    quote(evidence.path, evidence.kind, evidence.from, evidence.to, content)).join('\n\n');
  if (!data.evidence || data.format !== 'utf8') return visible(text);
  let body = data.content;
  if (data.next) body = body.slice(0, body.lastIndexOf('\n') + 1);
  const { path, kind, from, to } = data.evidence;
  return quote(path, kind, from, to, body);
}

function decodeEvidence(text) {
  if (!text.startsWith('evidence ')) return JSON.parse(text);
  const [header, ...rows] = text.split('\n');
  const handle = header.slice('evidence '.length);
  assert.match(handle, /^sha256:[a-f0-9]{64}$/);
  const sources = new Map();
  const hits = [];
  const more = [];
  let current;
  function flush() {
    if (!current) return;
    const content = current.rows.join('\n');
    hits.push({ start: current.start, end: current.start + Buffer.byteLength(content), evidence: current.evidence, content, format: 'utf8' });
    current = undefined;
  }
  for (const row of rows) {
    if (row.startsWith('| ')) { assert.ok(current); current.rows.push(row); continue; }
    flush();
    const source = /^source (\d+) (code|note) ("(?:[^"\\]|\\.)*")(?: ("(?:[^"\\]|\\.)*"))?$/.exec(row);
    if (source) {
      sources.set(Number(source[1]), { kind: source[2], path: JSON.parse(source[3]), ...(source[4] ? { heading: JSON.parse(source[4]) } : {}) });
      continue;
    }
    const item = /^(hit|more) (\d+) L(\d+)(?:-L(\d+))? (\d+)(?::(\d+))?$/.exec(row);
    assert.ok(item && sources.has(Number(item[2])), `Invalid evidence row: ${row}`);
    const evidence = { ...sources.get(Number(item[2])), from: Number(item[3]), to: Number(item[4] ?? item[3]) };
    const start = Number(item[5]);
    if (item[1] === 'hit') current = { start, evidence, rows: [] };
    else more.push({ start, end: Number(item[6]), evidence });
  }
  flush();
  return { delivery: 'evidence', handle, hits, ...(more.length ? { more } : {}) };
}

function profileTransport(delivery) {
  const results = [];
  for (const { phase, response } of delivery) {
    if (phase !== 'recovery') continue;
    const rpc = JSON.parse(response);
    const part = rpc.result.content[0];
    if (!part.text.startsWith('{')) continue;
    const data = JSON.parse(part.text);
    if (data.delivery !== 'evidence') continue;
    const { handle, hits, more = [] } = data;
    const wireCost = text => count(wire({ ...rpc, result: { ...rpc.result, content: [{ ...part, text }] } }));
    const sources = [];
    const tuple = range => {
      const { path, kind, heading, from, to } = range.evidence;
      const source = JSON.stringify([path, kind, heading]);
      let id = sources.indexOf(source);
      if (id === -1) { id = sources.length; sources.push(source); }
      return [id, range.start, range.end, from, to];
    };
    const groupedHits = hits.map(hit => [...tuple(hit), hit.content, ...(hit.format === 'utf8' ? [] : [hit.format])]);
    const groupedMore = more.map(tuple);
    const grouped = JSON.stringify({ delivery: 'evidence', handle, sources: sources.map(source => JSON.parse(source)), hits: groupedHits, ...(more.length ? { more: groupedMore } : {}) });
    const lines = evidenceLines(handle, hits, more);
    results.push({ json: count(response), quotesOnly: wireCost(hits.map(hit => hit.content).join('\n')), grouped: wireCost(grouped), lines: lines === null ? null : wireCost(lines) });
  }
  return results;
}

function quotedRanges(text) {
  return [...text.matchAll(/^(?:code|note) ("(?:[^"\\]|\\.)*") (?:body )?L(\d+)(?:-L(\d+))?/gm)].map(match => ({
    source: JSON.parse(match[1]), from: Number(match[2]), to: Number(match[3] ?? match[2]),
  }));
}

function sourcePaths(text, repo) {
  const paths = new Set(text.match(/[\w./-]+\.(?:[cm]?[jt]sx?|py|rs|md)\b/g) ?? []);
  return [...paths].filter(path => relative(repo, resolve(repo, path)).replaceAll('\\', '/') === path);
}

// Host-side fallback uses only the question and paths visible to the reader.
// Give both modes the same bounded excerpt operation and budget.
function localPassages(repo, path, query, budget) {
  let content;
  try {
    const file = join(repo, path);
    if (realpathSync(file) !== join(realpathSync(repo), path) || !lstatSync(file).isFile()) return '';
    content = readFileSync(file, 'utf8');
  }
  catch (error) { if (error.code === 'ENOENT' || error.code === 'EISDIR') return ''; throw error; }
  const kind = path.startsWith('.julius/learnings/') ? 'note' : 'code';
  const lines = (kind === 'note' ? noteText(content).body : content).split('\n');
  if (lines.at(-1) === '') lines.pop();
  const radius = /\b(?:exact|entire|complete)\b/i.test(query) ? 8 : 2;
  const terms = new Set(tokenize(query).map(term => term.replace(/([^s])s$/, '$1')));
  const score = line => new Set(tokenize(line).map(term => term.replace(/([^s])s$/, '$1')).filter(term => terms.has(term))).size;
  const anchors = lines.map((line, index) => ({ index, score: score(line) })).filter(anchor => anchor.score > 0);
  anchors.sort((a, b) => b.score - a.score || a.index - b.index);
  const fragments = [];
  const seen = new Set();
  for (const { index } of anchors.slice(0, 30)) {
    if (seen.has(index)) continue;
    const start = Math.max(0, index - radius);
    const end = Math.min(lines.length, index + radius + 1);
    if (lines.slice(start, end).some((_, offset) => seen.has(start + offset))) continue;
    const fragment = quote(path, kind, start + 1, end, lines.slice(start, end).map(line => `| ${line}`).join('\n'));
    if ((count([...fragments, fragment].join('\n\n')) ?? Infinity) > budget) continue;
    fragments.push(fragment);
    for (let line = start; line < end; line++) seen.add(line);
  }
  return fragments.join('\n\n');
}

function pilotFacts(text, fixture, repo) {
  const found = new Set();
  let source;
  let line = 0;
  for (const row of text.split('\n')) {
    const heading = /^(code|note) ("(?:[^"\\]|\\.)*") (?:body )?L(\d+)(?:-L\d+)?(?: under .*|)$/.exec(row);
    if (heading) {
      const path = JSON.parse(heading[2]);
      const original = fixture.files?.[path] ?? (fixture.historical ? readFileSync(join(repo, path), 'utf8') : undefined);
      assert.ok(original, `Unknown pilot source: ${path}`);
      const { body, offset } = heading[1] === 'note' ? noteText(original) : { body: original, offset: 0 };
      source = { path, lines: body.split('\n'), offset };
      line = Number(heading[3]);
    } else if (row.startsWith('| ')) {
      const excerpt = row.slice(2);
      assert.equal(excerpt, source?.lines[line - 1], `Inexact excerpt from ${source?.path}`);
      fixture.facts.forEach((fact, index) => {
        if (fact.path === source.path && fact.text === excerpt && (fact.line === undefined || fact.line === line + source.offset)) found.add(index);
      });
      line++;
    }
  }
  return found;
}

function baselineFacts(text, fixture) {
  const found = new Set();
  fixture.facts.forEach((fact, index) => {
    // The inherited renderer strips note bullet markers from displayed leads.
    if ((fact.previous !== undefined || fact.following !== undefined) && !text.split('\n').some((line, i, rows) => line === fact.text
      && ((fact.previous?.trim() && rows[i - 1] === fact.previous) || (fact.following?.trim() && rows[i + 1] === fact.following)))) return;
    if (text.includes(fact.path) && text.includes(fact.text.replace(/^- /, ''))) found.add(index);
  });
  return found;
}

async function evaluate(fixture, lane) {
  const { repo, env } = prepare(fixture, lane);
  const pilot = lane !== 'baseline';
  const candidate = lane === 'pilot' || lane === 'transport';
  const control = lane === 'baseline' ? defaultCli ?? priorCli : priorCli;
  const binary = !candidate && control ? resolve(control) : cli;
  const value = await client(repo, env, binary, async ({ request, notify, record }) => {
    const start = performance.now();
    const tool = async (name, args, phase, allowError) => (await request('tools/call', { name, arguments: args }, phase, allowError)).content[0].text;
    const discover = operation => tool('julius_discover', operation ? { operation } : {}, 'discovery');
    const find = () => tool('julius_call', { operation: 'julius_find_code', budget: fixture.budget,
      args: { query: fixture.query, ...(pilot ? { evidence: true } : {}), ...(lane === 'pilot' && focusEvidence ? { evidenceScope: 'auto' } : {}) } }, 'query');
    await request('initialize', { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'context-evidence-benchmark', version: '1' } }, 'setup');
    notify('notifications/initialized', 'setup');
    await request('tools/list', undefined, 'setup');
    await discover();
    await discover('julius_find_code');
    const initial = await find();
    const firstMs = performance.now() - start;
    assert.ok(economyTokens(initial) <= fixture.budget);
    const first = visible(initial);
    let all = first;
    const check = text => pilot ? pilotFacts(text, fixture, repo) : baselineFacts(text, fixture);
    const initialFacts = check(first);
    const found = new Set(initialFacts);
    const handle = initial.match(/sha256:[0-9a-f]{64}/)?.[0];
    const recoveredRanges = [];
    const recoveryTrace = [];
    let retained;
    const read = async phase => {
      const bounded = fixture.historical && phase === 'recovery';
      const reply = await tool('julius_call', { operation: 'context.read', delivery: 'complete', args: { handle },
        ...(bounded ? { budget: historicalPlan.recoveryBudget } : {}),
      }, phase);
      if (bounded) {
        assert.ok(economyTokens(reply) <= historicalPlan.recoveryBudget);
        const body = visible(reply);
        return JSON.parse(reply).next ? body.slice(0, body.lastIndexOf('\n') + 1) : body;
      }
      const newline = reply.indexOf('\n');
      const body = reply.slice(newline + 1);
      assert.equal(JSON.parse(reply.slice(0, newline)).start, 0);
      assert.equal(`sha256:${createHash('sha256').update(body).digest('hex')}`, handle);
      retained = body;
      return body;
    };
    if (directed && found.size < fixture.facts.length && handle) {
      await discover('context.read');
      const next = first.split('\n').filter(line => line.startsWith('next ')).map(line => JSON.parse(line.slice(5)));
      const clues = fixture.query.match(/\b[A-Z][A-Z0-9_]{2,}\b|\b[a-z]\w*[A-Z]\w*\b|\b\w+_\w+\b/g) ?? [];
      const searches = [...new Set(clues)].slice(0, 2).map(search => ({ search }));
      let requestedNext = false;
      for (let attempt = 0; attempt < 2 && found.size < fixture.facts.length; attempt++) {
        const exclude = quotedRanges(all).slice(0, 16);
        const nextRange = !requestedNext && (preferNext || attempt > 0)
          && next.find(item => !exclude.some(seen => seen.source === item.source && seen.from <= item.from && seen.to >= item.to));
        const selector = pilot ? { evidence: nextRange || { query: fixture.query, exclude, limit: 6 } } : searches[attempt] ?? {};
        requestedNext ||= Boolean(pilot && nextRange);
        if (!pilot && attempt > searches.length) break;
        const reply = await tool('julius_call', { operation: 'context.read', budget: historicalPlan.recoveryBudget,
          args: { handle, ...selector, ...(candidate && formatLines && selector.evidence ? { format: 'lines' } : {}),
            ...(lane === 'pilot' && focusEvidence && selector.evidence?.query ? { evidenceScope: 'auto' } : {}),
          },
        }, 'recovery', true);
        const trace = { attempt: attempt + 1, textTokens: count(reply), bytes: Buffer.byteLength(reply), newFacts: [] };
        recoveryTrace.push(trace);
        if (!reply.startsWith('{') && !reply.startsWith('evidence ')) continue;
        if (pilot) {
          const data = decodeEvidence(reply);
          assert.equal(data.handle, handle);
          const ranges = data.hits ?? (data.evidence ? [data] : []);
          recoveredRanges.push(...ranges);
          trace.ranges = ranges.map(({ start, end, evidence }) => ({ start, end, ...evidence }));
          trace.more = data.more ?? [];
        }
        const recovered = pilot ? passage(reply) : visible(reply);
        all += `\n${recovered}`;
        for (const index of check(recovered)) {
          if (!found.has(index)) trace.newFacts.push(index);
          found.add(index);
        }
      }
    } else if (found.size < fixture.facts.length && handle) {
      await discover('context.read');
      all = await read('recovery');
      for (const index of check(all)) found.add(index);
    }
    // A host can read exact repo files when the MCP response exposes a path.
    // Model that local read explicitly because main retains only formatted note leads.
    if (directed) {
      const paths = sourcePaths(`${fixture.query}\n${all}`, repo);
      for (const path of paths.slice(0, 3)) {
        if (found.size === fixture.facts.length) break;
        const content = localPassages(repo, path, fixture.query, historicalPlan.recoveryBudget);
        record.push({ phase: 'local-read', path, request: wire({ method: 'readPassages', path, query: fixture.query }), response: wire({ path, content }) });
        for (const index of pilotFacts(content, fixture, repo)) found.add(index);
      }
    } else {
      const missing = fixture.facts.filter((_, index) => !found.has(index));
      for (const path of new Set(missing.map(fact => fact.path))) {
        if (fixture.historical ? ![first, all, fixture.query].some(text => text.includes(path)) : !all.includes(path)) continue;
        const content = readFileSync(join(repo, path), 'utf8');
        record.push({ phase: 'local-read', path, request: wire({ method: 'readFile', path }), response: wire({ path, content }) });
        fixture.facts.forEach((fact, index) => { if (fact.path === path && content.split('\n').includes(fact.text)) found.add(index); });
      }
    }
    const totalMs = performance.now() - start;
    const delivery = [...record];
    if (pilot && handle && !retained) retained = await read('audit');
    let retainedFacts;
    if (pilot) {
      const available = check(retained ?? first);
      for (const { start, end, content, format } of recoveredRanges) {
        assert.deepEqual(Buffer.from(retained).subarray(start, end), Buffer.from(content, format));
      }
      retainedFacts = available.size;
      const absent = fixture.facts.filter((_, index) => !available.has(index));
      if (!fixture.historical) assert.deepEqual(absent, [], `${fixture.name}: evidence missing from retained sources`);
      if (fixture.requiresRecovery) assert.ok(retained && initialFacts.size < fixture.facts.length, 'fixture must require handle recovery');
      if (fixture.duplicate) assert.equal(first.split(fixture.duplicate).length - 1, 1);
      if (fixture.wrongReference) {
        assert.ok(handle, 'wrong-reference holdout needs a retained snapshot');
        const wrong = await tool('julius_call', { operation: 'context.read', args: { handle,
          evidence: { source: fixture.wrongReference, from: 62 },
        } }, 'audit', true);
        assert.equal(wrong, 'Requested evidence was not found in this snapshot');
      }
    }
    for (const text of [first, all, retained ?? '']) {
      for (const deny of [...(fixture.forbidden ?? []), ...(pilot ? fixture.pilotForbidden ?? [] : [])]) assert.ok(!text.includes(deny), `${fixture.name}: exposed ${deny}`);
    }
    const costs = phase => sum(delivery.filter(item => !phase || phase === item.phase).flatMap(({ request, response }) => [count(request), count(response)]));
    const localReads = delivery.filter(item => item.phase === 'local-read').map(item => ({ path: item.path, tokens: sum([count(item.request), count(item.response)]) }));
    return { firstFacts: initialFacts.size, finalFacts: found.size, firstFactIds: [...initialFacts], finalFactIds: [...found], retainedFacts,
      initialTextTokens: count(initial), initialCitations: quotedRanges(first), totalTokens: costs(), protocolBytes: sum(delivery.flatMap(({ request, response }) => [Buffer.byteLength(request), Buffer.byteLength(response)])),
      setupTokens: costs('setup'), discoveryTokens: costs('discovery'), queryTokens: costs('query'), contextReadTokens: costs('recovery'),
      verifiedRecoveryBytes: recoveredRanges.reduce((n, range) => n + range.end - range.start, 0), recoveryTrace, localReads, transportProfile: profileTransport(delivery),
      calls: delivery.filter(item => item.phase !== 'setup').length, recoveryCalls: delivery.filter(item => item.phase === 'recovery' || item.phase === 'local-read').length, firstMs, totalMs };
  });
  return value;
}

try {
  const historical = history || holdout || marginalHoldout || transportHoldout || namedSourceHoldout;
  if (historical && !bulmaRepo) throw new Error('Historical samples require --bulma-repo=/path/to/a/Bulma/git/repository');
  if (transportControl && (!formatLines || !focusEvidence || onlyBaseline)) throw new Error('--transport-control requires --format-lines and --focus-evidence');
  const sample = namedSourceHoldout ? 'named-source' : transportHoldout ? 'transport' : marginalHoldout ? 'marginal' : holdout;
  const fixtures = (historical ? historicalCases(process.cwd(), bulmaRepo, sample) : cases).filter(fixture => !caseName || fixture.name === caseName);
  assert.ok(fixtures.length, `Unknown case: ${caseName}`);
  const results = [];
  for (const [index, fixture] of fixtures.entries()) {
    const pilotFirst = (index % 2 === 1) !== reverse;
    const lanes = onlyBaseline ? ['baseline'] : pilotFirst ? ['pilot', 'baseline'] : ['baseline', 'pilot'];
    if (priorCli && !onlyBaseline) lanes.splice(1, 0, 'prior');
    if (transportControl) lanes.splice(pilotFirst ? 1 : lanes.length - 1, 0, 'transport');
    const row = { name: fixture.name, budget: fixture.budget, facts: fixture.facts.length };
    if (fixture.historical) Object.assign(row, { project: fixture.project, pr: fixture.pr, sha: fixture.sha, query: fixture.query,
      queryWords: fixture.query.split(/\s+/).length, oracle: fixture.facts.map(({ path, line }) => ({ path, line })),
    });
    for (const lane of lanes) row[lane] = await evaluate(fixture, lane);
    results.push(row);
  }
  const aggregate = lane => Object.fromEntries(['firstFacts', 'finalFacts', 'initialTextTokens', 'totalTokens', 'protocolBytes', 'discoveryTokens', 'contextReadTokens', 'verifiedRecoveryBytes', 'calls', 'recoveryCalls'].map(key => [key, sum(results.map(row => row[lane][key]))]));
  const baseline = aggregate('baseline');
  const pilot = onlyBaseline ? null : aggregate('pilot');
  const prior = priorCli && !onlyBaseline ? aggregate('prior') : null;
  const transport = transportControl ? aggregate('transport') : null;
  const preservesPrior = prior ? results.every(row => row.prior.finalFactIds.every(id => row.pilot.finalFactIds.includes(id))) : null;
  const preservesDefault = pilot ? results.every(row => row.baseline.finalFactIds.every(id => row.pilot.finalFactIds.includes(id))) : null;
  if (sameDelivery || transportControl) {
    assert.ok(prior, 'Transport identity requires an evidence control');
    for (const row of results) {
      const fixed = lane => ({ facts: lane.finalFactIds, initial: lane.initialCitations, ranges: lane.recoveryTrace.map(item => [item.ranges, item.more]),
        bytes: lane.verifiedRecoveryBytes, calls: lane.calls, paths: lane.localReads.map(item => item.path) });
      assert.deepEqual(fixed(transportControl ? row.transport : row.pilot), fixed(row.prior), `Transport changed evidence delivery in ${row.name}`);
    }
  }
  const objective = pilot && prior && preservesPrior && preservesDefault && pilot.totalTokens !== null
    && baseline.totalTokens !== null && prior.totalTokens !== null
    && pilot.totalTokens < baseline.totalTokens && pilot.totalTokens < prior.totalTokens;
  const { minimumTrafficReduction, minimumNewlyComplete } = historicalPlan;
  const gate = pilot && pilot.totalTokens !== null && baseline.totalTokens !== null
    && pilot.totalTokens <= baseline.totalTokens * (1 - minimumTrafficReduction)
    && (!prior || (preservesPrior && prior.totalTokens !== null && pilot.totalTokens < prior.totalTokens))
    && results.every(row => row.pilot.finalFacts === row.facts && row.pilot.firstFacts >= row.baseline.firstFacts)
    && results.filter(row => row.pilot.firstFacts === row.facts && row.baseline.firstFacts < row.facts).length >= minimumNewlyComplete;
  console.log(JSON.stringify({ encoding: ECONOMY_ENCODING, providerUsage: null, directed, holdout, marginalHoldout, transportHoldout, namedSourceHoldout,
    formatLines, preferNext, focusEvidence, sameDelivery, ...(historical ? { historicalPlan } : {}), baseline,
    ...(prior ? { prior, preservesPrior, preservesDefault, objective } : {}), ...(transport ? { transport } : {}), pilot, gate, results }, null, 2));
  if (!onlyBaseline && !caseName && !gate) process.exitCode = 1;
} finally { rmSync(scratch, { recursive: true, force: true }); }
