import { Database } from "bun:sqlite";
import { chmodSync, existsSync, lstatSync, mkdirSync, realpathSync } from "node:fs";
import { dirname, parse, resolve, sep } from "node:path";
import { normalizeUtc, validateEvent, type EconomyEvent } from "./events";

export interface EventFilters { projectId?: string; taskId?: string; modelId?: string; eventType?: EconomyEvent["eventType"]; since?: string; until?: string }
export interface RecordReceipt { eventId: string; inserted: boolean; duplicateOf: string | null }
export interface BudgetReservation { budgetId: string; reservationId: string; amount: number; limit: number; expiresAt: string }
const validAmount = (n: number) => Number.isFinite(n) && n >= 0;
function prepareLedgerPath(path: string): string {
  if (path === ":memory:") return path;
  const absolute = resolve(path);
  const parent = dirname(absolute);
  const root = parse(parent).root;
  const parts = parent.slice(root.length).split(sep).filter(Boolean);
  const first = parts.shift();
  let current = first ? realpathSync(resolve(root, first)) : root;
  for (const part of parts) {
    current = resolve(current, part);
    if (!existsSync(current)) mkdirSync(current, { mode: 0o700 });
    const stat = lstatSync(current);
    if (stat.isSymbolicLink() || !stat.isDirectory()) throw new Error("Unsafe ledger parent");
  }
  if (existsSync(absolute)) {
    const stat = lstatSync(absolute);
    if (stat.isSymbolicLink() || !stat.isFile()) throw new Error("Unsafe ledger path");
  }
  return absolute;
}

export class Ledger {
  private db: Database;
  constructor(path: string) {
    const safePath = prepareLedgerPath(path);
    this.db = new Database(safePath, { create: true });
    if (safePath !== ":memory:") chmodSync(safePath, 0o600);
    this.db.exec("PRAGMA busy_timeout=5000; PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_event_id TEXT NOT NULL, project_id TEXT NOT NULL, task_id TEXT, model_id TEXT, event_type TEXT NOT NULL, occurred_at TEXT NOT NULL, call_id TEXT, body TEXT NOT NULL, UNIQUE(source_id,source_event_id)); CREATE INDEX IF NOT EXISTS events_time ON events(occurred_at); CREATE TABLE IF NOT EXISTS event_aliases (event_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_event_id TEXT NOT NULL, canonical_event_id TEXT NOT NULL, body TEXT NOT NULL, UNIQUE(source_id,source_event_id)); CREATE TABLE IF NOT EXISTS budgets (budget_id TEXT PRIMARY KEY, limit_amount REAL NOT NULL); CREATE TABLE IF NOT EXISTS reservations (reservation_id TEXT PRIMARY KEY, budget_id TEXT NOT NULL, amount REAL NOT NULL, limit_amount REAL NOT NULL, spent REAL, expires_at TEXT NOT NULL, status TEXT NOT NULL); CREATE INDEX IF NOT EXISTS reservations_budget ON reservations(budget_id,status,expires_at);");
  }
  record(input: unknown): RecordReceipt {
    const event = validateEvent(input);
    return this.db.transaction(() => {
      const existing = this.db.query("SELECT event_id,body FROM events WHERE source_id=? AND source_event_id=? UNION ALL SELECT canonical_event_id AS event_id,body FROM event_aliases WHERE source_id=? AND source_event_id=?").get(event.sourceId,event.sourceEventId,event.sourceId,event.sourceEventId) as {event_id:string;body:string}|null;
      const body = JSON.stringify(event);
      if (existing) {
        if (existing.body !== body) throw new Error("Conflicting source event");
        return { eventId: existing.event_id, inserted: false, duplicateOf: existing.event_id };
      }
      const id = this.db.query("SELECT body FROM events WHERE event_id=? UNION ALL SELECT body FROM event_aliases WHERE event_id=?").get(event.eventId,event.eventId) as {body:string}|null;
      if (id) throw new Error("Conflicting event ID");
      if (event.eventType === "reconciliation") {
        const target = this.db.query("SELECT body FROM events WHERE event_id=?").get(event.payload.targetEventId) as {body:string}|null;
        const original = target ? JSON.parse(target.body) as EconomyEvent : null;
        if (!original || original.eventType !== "usage" || original.projectId !== event.projectId || original.requestId !== event.requestId || original.attemptId !== event.attemptId) throw new Error("Reconciliation target must be an owned usage event");
        if (event.payload.effectiveCostUsd !== null && !event.modelId) throw new Error("Cost requires a known model");
      }
      if (event.eventType === "transform") {
        const existingTransform = this.db.query("SELECT body FROM events WHERE event_type='transform' AND project_id=?").all(event.projectId) as {body:string}[];
        for (const row of existingTransform) {
          const prior = JSON.parse(row.body) as EconomyEvent;
          if (prior.eventType !== "transform") continue;
          if (prior.payload.transformId === event.payload.transformId) throw new Error("Duplicate transform ID");
          if (event.payload.sent && prior.payload.sent && prior.requestId === event.requestId && prior.attemptId === event.attemptId && prior.payload.scope === event.payload.scope && prior.payload.parentTransformId === event.payload.parentTransformId) throw new Error("Multiple sent transforms for one branch");
          if (prior.payload.transformId === event.payload.parentTransformId) {
            if (prior.requestId !== event.requestId || prior.modelId !== event.modelId || prior.payload.tokenizer !== event.payload.tokenizer || prior.payload.outputTokens !== event.payload.inputTokens) throw new Error("Transform chain mismatch");
          }
        }
        if (event.payload.parentTransformId !== null && !existingTransform.some(row => { const prior=JSON.parse(row.body) as EconomyEvent; return prior.eventType === "transform" && prior.payload.transformId === event.payload.parentTransformId; })) throw new Error("Missing parent transform");
      }
      const callId = event.eventType === "usage" ? event.payload.callId : null;
      if (callId !== null) {
        const duplicate = this.db.query("SELECT event_id,body FROM events WHERE call_id=? AND project_id=? AND event_type='usage' ORDER BY rowid LIMIT 1").get(callId,event.projectId) as {event_id:string;body:string}|null;
        if (duplicate) {
          const old = JSON.parse(duplicate.body) as EconomyEvent;
          if (old.eventType === "usage" && old.requestId === event.requestId && old.attemptId === event.attemptId && old.providerId === event.providerId && old.payload.category === (event.payload as Extract<EconomyEvent,{eventType:"usage"}>["payload"]).category) { this.db.query("INSERT INTO event_aliases VALUES (?,?,?,?,?)").run(event.eventId,event.sourceId,event.sourceEventId,duplicate.event_id,body); return { eventId: event.eventId, inserted: false, duplicateOf: duplicate.event_id }; }
        }
      }
      this.db.query("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)").run(event.eventId,event.sourceId,event.sourceEventId,event.projectId,event.taskId,event.modelId,event.eventType,event.occurredAt,callId,body);
      return { eventId: event.eventId, inserted: true, duplicateOf: null };
    }).immediate();
  }
  history(filters: EventFilters = {}): EconomyEvent[] {
    const clauses: string[] = []; const args: string[] = [];
    for (const [key,column] of [["projectId","project_id"],["taskId","task_id"],["modelId","model_id"],["eventType","event_type"],["since","occurred_at"]] as const) {
      const value = filters[key]; if (value !== undefined) { clauses.push(`${column}${key === "since" ? ">=" : "="}?`); args.push(value); }
    }
    if (filters.until !== undefined) { clauses.push("occurred_at<?"); args.push(normalizeUtc(filters.until)); }
    if (filters.since !== undefined) args[args.length - (filters.until !== undefined ? 2 : 1)] = normalizeUtc(filters.since);
    const sql = `SELECT body FROM events ${clauses.length ? `WHERE ${clauses.join(" AND ")}` : ""} ORDER BY occurred_at,event_id`;
    return (this.db.query(sql).all(...args) as {body:string}[]).map(row => JSON.parse(row.body) as EconomyEvent);
  }
  events(filters: EventFilters = {}): EconomyEvent[] {
    const history = this.history();
    const corrected = new Map<string, EconomyEvent & {eventType:"reconciliation"}>();
    for (const row of this.db.query("SELECT body FROM events WHERE event_type='reconciliation' ORDER BY rowid").all() as {body:string}[]) { const event = JSON.parse(row.body) as EconomyEvent; if (event.eventType === "reconciliation") corrected.set(event.payload.targetEventId,event); }
    return history.filter(e => e.eventType !== "reconciliation").map(e => {
      const correction = corrected.get(e.eventId);
      if (!correction || e.eventType !== "usage") return e;
      return { ...e, payload: { ...e.payload, inputTokens: correction.payload.effectiveInputTokens, outputTokens: correction.payload.effectiveOutputTokens, cacheReadTokens: correction.payload.effectiveCacheReadTokens, cacheWriteTokens: correction.payload.effectiveCacheWriteTokens, costUsd: correction.payload.effectiveCostUsd, costProvenance: correction.payload.effectiveCostProvenance ?? null, complete: correction.payload.effectiveComplete ?? e.payload.complete } };
    }).filter(e => (!filters.projectId || e.projectId === filters.projectId) && (!filters.taskId || e.taskId === filters.taskId) && (!filters.modelId || e.modelId === filters.modelId) && (!filters.eventType || e.eventType === filters.eventType) && (!filters.since || e.occurredAt >= normalizeUtc(filters.since)) && (!filters.until || e.occurredAt < normalizeUtc(filters.until)));
  }
  reserveBudget(input: BudgetReservation): boolean {
    if (![input.amount,input.limit].every(validAmount) || !input.budgetId || !input.reservationId || !Number.isFinite(Date.parse(input.expiresAt))) throw new Error("Invalid reservation");
    return this.db.transaction(() => {
      const budget = this.db.query("SELECT limit_amount FROM budgets WHERE budget_id=?").get(input.budgetId) as {limit_amount:number}|null;
      if (budget && budget.limit_amount !== input.limit) throw new Error("Conflicting budget limit");
      if (!budget) {
        const priorLimits = this.db.query("SELECT DISTINCT limit_amount FROM reservations WHERE budget_id=?").all(input.budgetId) as {limit_amount:number}[];
        if (priorLimits.length > 1 || (priorLimits.length === 1 && priorLimits[0]?.limit_amount !== input.limit)) throw new Error("Conflicting budget limit");
        this.db.query("INSERT INTO budgets VALUES (?,?)").run(input.budgetId,input.limit);
      }
      this.db.query("UPDATE reservations SET status='expired' WHERE status='reserved' AND expires_at<=?").run(new Date().toISOString());
      const prior = this.db.query("SELECT * FROM reservations WHERE reservation_id=?").get(input.reservationId) as Record<string,unknown>|null;
      if (prior) { if (prior.budget_id !== input.budgetId || prior.amount !== input.amount || prior.limit_amount !== input.limit || prior.expires_at !== input.expiresAt) throw new Error("Conflicting reservation"); return prior.status === "reserved" || prior.status === "settled"; }
      const row = this.db.query("SELECT COALESCE(SUM(CASE WHEN status='settled' THEN spent ELSE amount END),0) AS used FROM reservations WHERE budget_id=? AND status IN ('reserved','settled')").get(input.budgetId) as {used:number};
      if (row.used + input.amount > input.limit) return false;
      this.db.query("INSERT INTO reservations VALUES (?,?,?,?,NULL,?,'reserved')").run(input.reservationId,input.budgetId,input.amount,input.limit,input.expiresAt);
      return true;
    }).immediate();
  }
  settleBudget(reservationId: string, actualAmount: number): void {
    if (!validAmount(actualAmount)) throw new Error("Invalid settlement");
    this.db.transaction(() => {
      const row = this.db.query("SELECT status,spent,expires_at,amount FROM reservations WHERE reservation_id=?").get(reservationId) as {status:string;spent:number|null;expires_at:string;amount:number}|null;
      if (!row) throw new Error("Unknown reservation");
      if (row.status === "settled") { if (row.spent !== actualAmount) throw new Error("Conflicting settlement"); return; }
      if (actualAmount > row.amount) throw new Error("Settlement exceeds reservation");
      if (row.status !== "reserved" || row.expires_at <= new Date().toISOString()) throw new Error("Reservation inactive");
      this.db.query("UPDATE reservations SET status='settled',spent=? WHERE reservation_id=?").run(actualAmount,reservationId);
    }).immediate();
  }
  releaseBudget(reservationId: string): void { this.db.transaction(() => { this.db.query("UPDATE reservations SET status='released' WHERE reservation_id=? AND status='reserved'").run(reservationId); }).immediate(); }
  close(): void { this.db.close(); }
}
