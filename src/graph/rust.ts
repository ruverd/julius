import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { basename, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtractResult, Language, RawEdge } from "./extract.js";
import type { NodeV1 } from "./types.js";
import { RUST_EXTRACTOR_PATH } from "./rust-settings.js";

export type RustExtractorStatus =
  | { state: "disabled" }
  | { state: "ready" }
  | { state: "fallback"; reason: string };

type Addon = { protocolVersion: 1; extract(source: string, language: string): unknown };
type Loaded =
  | { state: "ready"; addon: Addon; identity: string }
  | { state: "fallback"; reason: string; identity: string | null };

const requireModule = createRequire(import.meta.url);
const defaultPath = fileURLToPath(new URL("../../native/extractor/extractor.node", import.meta.url));
let loaded: { path: string; value: Loaded } | undefined;

function isAddon(value: unknown): value is Addon {
  return typeof value === "object" && value !== null && "protocolVersion" in value && value.protocolVersion === 1 &&
    "extract" in value && typeof value.extract === "function";
}

function selected(): Loaded | null {
  if (process.env.JULIUS_EXTRACTOR !== "rust") return null;
  const path = resolve(RUST_EXTRACTOR_PATH || defaultPath);
  if (loaded?.path === path) return loaded.value;
  let value: Loaded;
  try {
    const identity = createHash("sha256").update(readFileSync(path)).digest("hex");
    const addon: unknown = requireModule(path);
    if (!isAddon(addon)) throw new Error("Unsupported Rust extractor protocol (expected version 1)");
    if (createHash("sha256").update(readFileSync(path)).digest("hex") !== identity) throw new Error("Rust extractor changed while loading; restart Julius");
    value = { state: "ready", addon, identity: `rust-v1:${identity}` };
  } catch (error) {
    value = { state: "fallback", reason: error instanceof Error ? error.message : String(error), identity: "typescript:rust-unavailable" };
  }
  loaded = { path, value };
  return value;
}

/** Identity of the backend actually loaded; a failed native call disables reuse. */
export function rustExtractorCacheKey(): string | null {
  const backend = selected();
  return backend === null ? "typescript" : backend.identity;
}

/** Also available from the public API and on explicitly requested build results. */
export function rustExtractorStatus(): RustExtractorStatus {
  const backend = selected();
  if (backend === null) return { state: "disabled" };
  return backend.state === "ready" ? { state: "ready" } : { state: "fallback", reason: backend.reason };
}

type DefinitionKind = "class" | "function" | "method" | "interface" | "type" | "enum";
type Definition = [string, string, DefinitionKind, number, number, number, number, number, boolean, string | null];
type Edge = [number, "contains" | "imports" | "calls" | "references" | "extends" | "implements", number | string | null, boolean | null, string | null, string | null];
type Packet = [number, Definition[], Edge[]];

function definitionKind(value: unknown): value is DefinitionKind {
  return value === "class" || value === "function" || value === "method" || value === "interface" || value === "type" || value === "enum";
}
function integer(value: unknown): value is number { return typeof value === "number" && Number.isSafeInteger(value); }
function text(value: unknown): value is string { return typeof value === "string" && value.length > 0; }
function nullableText(value: unknown): value is string | null { return value === null || text(value); }
function definition(value: unknown, bytes: number, rows: number): value is Definition {
  if (!Array.isArray(value) || value.length !== 10) return false;
  const [id, name, kind, start, end, header, first, last, exported, owner]: unknown[] = value;
  return text(id) && text(name) && definitionKind(kind) && integer(start) && integer(end) && integer(header) &&
    start >= 0 && start <= header && header <= end && end <= bytes && integer(first) && integer(last) &&
    first >= 1 && first <= last && last <= rows && typeof exported === "boolean" && nullableText(owner) &&
    (kind === "method" || owner === null);
}
function edge(value: unknown, count: number): value is Edge {
  if (!Array.isArray(value) || value.length !== 6) return false;
  const [source, relation, target, member, receiver, specifier]: unknown[] = value;
  if (!integer(source) || source < -1 || source >= count || !nullableText(receiver) || !nullableText(specifier)) return false;
  switch (relation) {
    case "contains": return integer(target) && target >= 0 && target < count && member === null && receiver === null && specifier === null;
    case "imports": return source === -1 && target === null && member === null && receiver === null && text(specifier);
    case "calls": return text(target) && typeof member === "boolean" && specifier === null;
    case "references": return text(target) && member === null && receiver === null && text(specifier);
    case "extends": case "implements": return text(target) && member === null && receiver === null && specifier === null;
    default: return false;
  }
}
function packet(value: unknown, bytes: number, rows: number): value is Packet {
  if (!Array.isArray(value) || value.length !== 3) return false;
  const [endRow, definitions, edges]: unknown[] = value;
  if (endRow !== rows || !Array.isArray(definitions) || !Array.isArray(edges) || definitions.length > 250_000 || edges.length > 500_000) return false;
  const ids = new Set<string>();
  for (const item of definitions) {
    if (!definition(item, bytes, rows) || ids.has(item[0])) return false;
    ids.add(item[0]);
  }
  return edges.every(item => edge(item, definitions.length));
}

type Materializers = {
  contentHash(source: string): string;
  fileResidual(source: string, nodes: NodeV1[]): string;
  searchBody(source: string): string;
  clean(source: string): string | null;
};

/** Null requests the existing TypeScript extractor; no compiler or downloads run. */
export function extractRustFile(rel: string, source: string, language: Language, helpers: Materializers): ExtractResult | null {
  if (language !== "typescript" && language !== "tsx") return null;
  if (process.env.JULIUS_EXTRACTOR !== "rust" || source.length > 4 * 1024 * 1024 || /[\uD800-\uDFFF]/u.test(source)) return null;
  const backend = selected();
  if (backend === null || backend.state !== "ready") return null;
  const bytes = Buffer.from(source, "utf8");
  if (bytes.length > 4 * 1024 * 1024) return null;
  try {
    const raw = backend.addon.extract(source, language);
    if (typeof raw !== "string" || raw.length > 64 * 1024 * 1024) throw new Error("Invalid Rust extractor response size/type");
    const data: unknown = JSON.parse(raw);
    const rows = source.split("\n").length;
    if (!packet(data, bytes.length, rows)) throw new Error("Invalid Rust extractor response schema or bounds");
    const [, definitions, edges] = data;
    for (const [, , , start, end, header] of definitions) {
      for (const offset of [start, end, header]) {
        if (offset < bytes.length && (bytes[offset] & 0xc0) === 0x80) throw new Error("Invalid Rust extractor UTF-8 offset");
      }
    }
    const slice = (start: number, end: number): string => bytes.subarray(start, end).toString("utf8");
    const nodes: NodeV1[] = [{ id: rel, name: basename(rel), kind: "file", path: rel, span: `L1-L${rows}`,
      signature: null, exported: true, origin: "ast", body_hash: helpers.contentHash(source), chars: source.length,
      summary_state: "pending", summary: null, crux: null }];
    for (const [id, name, kind, start, end, header, first, last, exported, owner] of definitions) {
      const body = slice(start, end);
      nodes.push({ id: `${rel}#${id}`, name, kind, path: rel, span: `L${first}-L${last}`,
        signature: helpers.clean(slice(start, header)), exported, origin: "ast", body_hash: helpers.contentHash(body),
        body_text: helpers.searchBody(body), summary_state: "pending", summary: null, crux: null,
        ...(owner === null ? {} : { owner }) });
    }
    const rawEdges: RawEdge[] = edges.map(([from, relation, target, member, receiver, specifier]) => {
      const result: RawEdge = { source: nodes[from + 1].id, relation, file: rel };
      if (relation === "contains" && typeof target === "number") result.targetId = nodes[target + 1].id;
      else if (typeof target === "string") result.name = target;
      if (member !== null) result.viaMember = member;
      if (receiver !== null) result.recvType = receiver;
      if (specifier !== null) result.specifier = specifier;
      return result;
    });
    nodes[0].body_text = helpers.fileResidual(source, nodes.slice(1));
    return { nodes, rawEdges };
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    if (!reason.startsWith("JULIUS_RUST_INPUT_LIMIT:") && loaded) loaded.value = { state: "fallback", reason, identity: null };
    return null;
  }
}
