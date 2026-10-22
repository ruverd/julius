import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const Parser = require("tree-sitter");
const cases = [
  ["typescript", "tree-sitter-typescript", "typescript", "function hello(): number { return 1; }"],
  ["tsx", "tree-sitter-typescript", "tsx", "function Hello() { return <div />; }"],
  ["python", "tree-sitter-python", null, "def hello():\n    return 1\n"],
  ["go", "tree-sitter-go", null, "package main\nfunc hello() int { return 1 }\n"],
  ["r", "tree-sitter-r", null, "hello <- function() { 1 }\n"],
  ["java", "tree-sitter-java", null, "class Hello { int hello() { return 1; } }"],
  ["kotlin", "tree-sitter-kotlin", null, "fun hello(): Int { return 1 }\n"],
  ["swift", "tree-sitter-swift", null, "func hello() -> Int { return 1 }\n"],
  ["php", "tree-sitter-php", "php", "<?php enum Hello { case One; const VALUES = [1, 2]; public function hello(): int { return 1; } }"],
];

// Require native bindings directly: a WASM fallback must not hide an ABI failure.
for (const [name, module, pick, source] of cases) {
  const grammar = require(module);
  const parser = new Parser();
  parser.setLanguage(pick ? grammar[pick] : grammar);
  const tree = parser.parse(source);
  assert.ok(tree, `${name}: parser returned no tree`);
  assert.equal(tree.rootNode.hasError, false, `${name}: ${tree.rootNode.toString()}`);
  assert.equal(tree.rootNode.text, source, `${name}: incomplete parse`);
  assert.ok(tree.rootNode.namedChildCount > 0, `${name}: empty syntax tree`);
  console.log(`${name}: native grammar compatible`);
}
