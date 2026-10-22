import { readFileSync } from 'node:fs';
import { compareTrials } from '../dist/evaluation/index.js';
try {
  if (process.argv.length !== 3) throw new Error('Usage: node scripts/compare-trials.mjs <provider-trials.json>');
  console.log(JSON.stringify(compareTrials(JSON.parse(readFileSync(process.argv[2], 'utf8'))), null, 2));
} catch (error) { console.error(error.message); process.exitCode = 1; }
