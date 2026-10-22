import { test } from "node:test";
import assert from "node:assert/strict";
import { liveLearnings, newLearningId, readLearningFields } from "../src/notes/learning-fields.js";
import { gateNote } from "../src/notes/note-gate.js";
import { parseNote, renderNote } from "../src/notes/notes.js";

test("a note written before ids still reads as active, and a replacement hides it", () => {
  const text = renderNote({
    title: "Keep the retry limit at 7",
    author: "Priya",
    date: "2026-10-22",
    touches: ["src/listing.ts"],
    body: "## Decided\nSeven, because three failed the burst.\n",
    id: newLearningId("2026-10-22-retry-priya.md"),
    replaces: "l-aabbcc",
  });
  const note = parseNote(text, "/repo/.julius/learnings/2026-10-22-retry-priya.md");
  assert.equal(note?.replaces, "l-aabbcc");
  assert.equal(note?.status, "active");
  const older = { id: "l-aabbcc", date: "2026-10-01", path: "/repo/.julius/learnings/old.md", status: "active" as const };
  const newer = { id: note!.id, date: "2026-10-22", path: note!.path, status: "active" as const, replaces: "l-aabbcc" };
  assert.deepEqual(liveLearnings([older, newer]).map((item) => item.id), [note!.id]);
  const bare = readLearningFields({}, "old.md");
  assert.match(bare.id, /^l-[0-9a-f]{6}$/);
  assert.equal(bare.status, "active");
});

test("a team note with no reason is refused, and status is refused", () => {
  const missing = gateNote({
    title: "Retry limit",
    body: "## Decided\nUse seven.",
    personal: false,
    files: ["src/listing.ts"],
    namesSymbol: false,
    touches: ["src/listing.ts"],
  }, []);
  assert.ok(missing.problems.some((problem) => /why/i.test(problem)));
  const status = gateNote({
    title: "Retry limit",
    body: "## Decided\nUse 7 because three failed.\nThe PR is open.",
    personal: false,
    files: ["src/listing.ts"],
    namesSymbol: false,
    touches: ["src/listing.ts"],
  }, []);
  assert.ok(status.problems.some((problem) => /status/i.test(problem)));
});
