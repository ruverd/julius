import { expect, test } from "bun:test";
import { mkdtempSync, rmSync, statSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Ledger } from "../src/ledger";
import { validateEvent, type EconomyEvent } from "../src/events";

const base = (): Extract<EconomyEvent,{eventType:"usage"}> => ({
 schemaVersion:1,eventId:crypto.randomUUID(),occurredAt:"2026-09-21T12:00:00.000Z",sourceId:"proxy",sourceEventId:crypto.randomUUID(),projectId:"p",taskId:null,sessionId:"s",requestId:"r",attemptId:"a1",clientId:"c",adapterVersion:"1",modelId:"m",providerId:"provider",executionLocation:"remote",evidence:"provider_reported",eventType:"usage",payload:{inputTokens:10,outputTokens:5,cacheReadTokens:null,cacheWriteTokens:null,complete:true,category:"primary",callId:"call-1",costUsd:null}
});
function withLedger(fn:(ledger:Ledger)=>void) { const dir=mkdtempSync(join(tmpdir(),"julius-ledger-"));const ledger=new Ledger(join(dir,"ledger.db"));try{fn(ledger)}finally{ledger.close();rmSync(dir,{recursive:true,force:true})} }
test("idempotent source, explicit cross-source dedup, and retries",()=>withLedger(l=>{
 const first=base();expect(l.record(first).inserted).toBe(true);expect(l.record(first).inserted).toBe(false);
 expect(()=>l.record({...first,payload:{...first.payload,inputTokens:11}})).toThrow();
 const imported={...first,eventId:crypto.randomUUID(),sourceId:"log",sourceEventId:"entry-1"};expect(l.record(imported).duplicateOf).toBe(first.eventId);
 const retry={...imported,eventId:crypto.randomUUID(),sourceEventId:"entry-2",attemptId:"a2"};expect(l.record(retry).inserted).toBe(true);expect(l.events().length).toBe(2);
}));
test("reconciliation retains history and replaces effective usage",()=>withLedger(l=>{
 const first=base();l.record(first);
 const correction: EconomyEvent={...first,eventId:crypto.randomUUID(),sourceEventId:"correction",eventType:"reconciliation",payload:{targetEventId:first.eventId,effectiveInputTokens:12,effectiveOutputTokens:6,effectiveCacheReadTokens:null,effectiveCacheWriteTokens:null,effectiveCostUsd:null,effectiveComplete:true,reason:"final bill"}};
 l.record(correction);expect(l.history().length).toBe(2);const usage=l.events()[0];expect(usage?.eventType).toBe("usage");if(usage?.eventType==="usage")expect(usage.payload.inputTokens).toBe(12);
}));
test("invalid counters and UTC dates are rejected",()=>{
 expect(()=>validateEvent({...base(),payload:{...base().payload,inputTokens:-1}})).toThrow();
 expect(()=>validateEvent({...base(),occurredAt:"2026-09-21T12:00:00+00:00"})).toThrow();
});
test("budget reservations compete and settle",()=>withLedger(l=>{
 const expiresAt=new Date(Date.now()+60000).toISOString();
 expect(l.reserveBudget({budgetId:"b",reservationId:"one",amount:7,limit:10,expiresAt})).toBe(true);
 expect(l.reserveBudget({budgetId:"b",reservationId:"two",amount:7,limit:10,expiresAt})).toBe(false);
 l.settleBudget("one",3);expect(l.reserveBudget({budgetId:"b",reservationId:"two",amount:7,limit:10,expiresAt})).toBe(true);
}));
test("transform chains preserve marginal lineage and signed deltas",()=>withLedger(l=>{
 const u=base();
 const first: EconomyEvent={...u,eventType:"transform",payload:{scope:"request",inputTokens:10000,outputTokens:4000,tokenizer:"tok",transformId:"t1",parentTransformId:null,inputArtifactId:null,outputArtifactId:null,strategy:"compact",sent:true}};
 const second: EconomyEvent={...first,eventId:crypto.randomUUID(),sourceEventId:"t2",payload:{...first.payload,inputTokens:4000,outputTokens:3000,transformId:"t2",parentTransformId:"t1"}};
 l.record(first);l.record(second);expect(l.events().length).toBe(2);
 expect(()=>l.record({...second,eventId:crypto.randomUUID(),sourceEventId:"bad",payload:{...second.payload,transformId:"t3",inputTokens:5000}})).toThrow();
 const negative:EconomyEvent={...first,eventId:crypto.randomUUID(),sourceEventId:"negative",payload:{...first.payload,transformId:"t4",inputTokens:100,outputTokens:120,sent:false}};
 expect(l.record(negative).inserted).toBe(true);
}));
test("call identity is project scoped and source identity conflicts across projects",()=>withLedger(l=>{
 const a=base();l.record(a);
 const b={...a,projectId:"other",eventId:crypto.randomUUID(),sourceId:"log",sourceEventId:"other-entry"};expect(l.record(b).inserted).toBe(true);
 const duplicate={...a,eventId:crypto.randomUUID(),sourceId:"log",sourceEventId:"entry"};expect(l.record(duplicate).inserted).toBe(false);
 expect(()=>l.record({...duplicate,projectId:"other"})).toThrow("Conflicting source event");
}));
test("corrections stay in their project and latest append wins",()=>withLedger(l=>{
 const a=base();l.record(a);
 const correction=(tokens:number,sourceEventId:string,occurredAt:string):EconomyEvent=>({...a,eventId:crypto.randomUUID(),sourceEventId,occurredAt,eventType:"reconciliation",payload:{targetEventId:a.eventId,effectiveInputTokens:tokens,effectiveOutputTokens:null,effectiveCacheReadTokens:null,effectiveCacheWriteTokens:null,effectiveCostUsd:null,reason:"corrected"}});
 expect(()=>l.record({...correction(20,"foreign",a.occurredAt),projectId:"other"})).toThrow();
 l.record(correction(20,"first","2026-09-22T00:00:00.000Z"));l.record(correction(30,"second","2026-09-21T00:00:00.000Z"));
 const effective=l.events()[0];if(effective?.eventType==="usage")expect(effective.payload.inputTokens).toBe(30);
}));
test("timestamp windows normalize and exclude end",()=>withLedger(l=>{
 const a=base();l.record(a);
 expect(l.history({since:"2026-09-21T12:00:00Z"}).length).toBe(1);
 expect(l.history({until:"2026-09-21T12:00:00Z"}).length).toBe(0);
 expect(()=>l.history({since:"invalid"})).toThrow();
}));
test("budget IDs cannot be reused or over settled",()=>withLedger(l=>{
 const expiresAt=new Date(Date.now()+60000).toISOString();const input={budgetId:"a",reservationId:"same",amount:5,limit:10,expiresAt};
 expect(l.reserveBudget(input)).toBe(true);
 expect(()=>l.reserveBudget({...input,budgetId:"b"})).toThrow();
 expect(()=>l.reserveBudget({...input,limit:20})).toThrow();
 expect(()=>l.settleBudget("same",6)).toThrow();
 l.releaseBudget("same");expect(l.reserveBudget(input)).toBe(false);
}));
test("unknown models cannot have known costs and sibling sends conflict",()=>withLedger(l=>{
 const usage=base();expect(()=>validateEvent({...usage,modelId:null,payload:{...usage.payload,costUsd:1,costProvenance:{priceSource:"list",priceDate:"2026-09-21",priceModelId:"m"}}})).toThrow();
 const transform:EconomyEvent={...usage,eventType:"transform",payload:{scope:"request",inputTokens:10,outputTokens:5,tokenizer:"t",transformId:"x",parentTransformId:null,inputArtifactId:null,outputArtifactId:null,strategy:"s",sent:true}};
 l.record(transform);expect(()=>l.record({...transform,eventId:crypto.randomUUID(),sourceEventId:"sibling",payload:{...transform.payload,transformId:"y"}})).toThrow();
}));

test("eight processes atomically share a budget", async()=>{
 const dir=mkdtempSync(join(tmpdir(),"julius-budget-"));const dbPath=join(dir,"ledger.db");new Ledger(dbPath).close();
 try {
  const moduleUrl=new URL("../src/ledger.ts",import.meta.url).href;
  const code=`import { Ledger } from ${JSON.stringify(moduleUrl)}; const ledger=new Ledger(process.env.JULIUS_DB!); const ok=ledger.reserveBudget({budgetId:"shared",reservationId:process.env.JULIUS_ID!,amount:30,limit:100,expiresAt:new Date(Date.now()+60000).toISOString()});console.log(ok ? "reserved" : "denied");ledger.close();`;
  const workers=Array.from({length:8},(_,i)=>Bun.spawn([process.execPath,"-e",code],{env:{...process.env,JULIUS_DB:dbPath,JULIUS_ID:`worker-${i}`},stdout:"pipe",stderr:"pipe"}));
  const results=await Promise.all(workers.map(async worker=>({exit:await worker.exited,stdout:await new Response(worker.stdout).text(),stderr:await new Response(worker.stderr).text()})));
  expect(results.filter(r=>r.exit!==0)).toEqual([]);
  expect(results.filter(r=>r.stdout.trim()==="reserved").length).toBe(3);
 } finally {rmSync(dir,{recursive:true,force:true})}
});
test("expired reservation from a terminated process releases capacity", async()=>{
 const dir=mkdtempSync(join(tmpdir(),"julius-crash-"));const dbPath=join(dir,"ledger.db");
 try {
  const moduleUrl=new URL("../src/ledger.ts",import.meta.url).href;
  const code=`import { Ledger } from ${JSON.stringify(moduleUrl)}; const ledger=new Ledger(process.env.JULIUS_DB!); ledger.reserveBudget({budgetId:"shared",reservationId:"crashed",amount:80,limit:100,expiresAt:new Date(Date.now()+60).toISOString()});process.exit(0);`;
  const worker=Bun.spawn([process.execPath,"-e",code],{env:{...process.env,JULIUS_DB:dbPath},stdout:"pipe",stderr:"pipe"});expect(await worker.exited).toBe(0);
  await Bun.sleep(100);
  const ledger=new Ledger(dbPath);try{expect(ledger.reserveBudget({budgetId:"shared",reservationId:"recovered",amount:80,limit:100,expiresAt:new Date(Date.now()+60000).toISOString()})).toBe(true);expect(()=>ledger.reserveBudget({budgetId:"shared",reservationId:"crashed",amount:80,limit:100,expiresAt:new Date(Date.now()+60).toISOString()})).toThrow("Conflicting reservation")}finally{ledger.close()}
 } finally {rmSync(dir,{recursive:true,force:true})}
});
test("ledger file is private and symlink path is rejected",()=>{
 const dir=mkdtempSync(join(tmpdir(),"julius-permission-"));
 try {const dbPath=join(dir,"nested","ledger.db");new Ledger(dbPath).close();expect(statSync(dbPath).mode & 0o777).toBe(0o600);const link=join(dir,"link.db");symlinkSync(dbPath,link);expect(()=>new Ledger(link)).toThrow("Unsafe ledger path");const parentLink=join(dir,"parent-link");symlinkSync(join(dir,"nested"),parentLink);expect(()=>new Ledger(join(parentLink,"other.db"))).toThrow("Unsafe ledger parent");}finally{rmSync(dir,{recursive:true,force:true})}
});
test("shared budget cap is immutable across reservation IDs",()=>withLedger(l=>{
 const expiresAt=new Date(Date.now()+60000).toISOString();
 expect(l.reserveBudget({budgetId:"shared-cap",reservationId:"first",amount:80,limit:100,expiresAt})).toBe(true);
 expect(()=>l.reserveBudget({budgetId:"shared-cap",reservationId:"second",amount:80,limit:1000,expiresAt})).toThrow("Conflicting budget limit");
 l.releaseBudget("first");
 expect(()=>l.reserveBudget({budgetId:"shared-cap",reservationId:"third",amount:80,limit:1000,expiresAt})).toThrow("Conflicting budget limit");
}));
test("reconciliation replaces stale cost provenance",()=>withLedger(l=>{
 const first=base();first.payload.costUsd=1;first.payload.costProvenance={priceSource:"old",priceDate:"2026-09-21",priceModelId:"m"};l.record(first);
 const correction:EconomyEvent={...first,eventId:crypto.randomUUID(),sourceEventId:"price-correction",eventType:"reconciliation",payload:{targetEventId:first.eventId,effectiveInputTokens:10,effectiveOutputTokens:5,effectiveCacheReadTokens:null,effectiveCacheWriteTokens:null,effectiveCostUsd:2,effectiveCostProvenance:{priceSource:"new",priceDate:"2026-09-22",priceModelId:"m"},reason:"updated price"}};
 l.record(correction);const effective=l.events()[0];if(effective?.eventType==="usage"){expect(effective.payload.costUsd).toBe(2);expect(effective.payload.costProvenance?.priceSource).toBe("new");}
 expect(()=>l.record({...correction,eventId:crypto.randomUUID(),sourceEventId:"invalid-price",payload:{...correction.payload,effectiveCostProvenance:null}})).toThrow();
}));
