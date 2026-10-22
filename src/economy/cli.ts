import { Command } from 'commander';
import { createReadStream } from 'node:fs';
import { Economy, ECONOMY_MAX_BYTES } from './index.js';

export function registerEconomyCommands(program: Command): void {
  const options = (command: Command) => command.option('--repo <path>', 'repository root', '.').option('--budget <tokens>', 'complete delivery budget in cl100k_base tokens', '512');
  options(program.command('capture').description('Capture stdin or a file locally with exact recovery'))
    .option('--file <path>', 'read bytes from this file instead of stdin')
    .action(async (opts) => {
      const parts: Buffer[] = []; let size = 0;
      const stream = opts.file ? createReadStream(opts.file) : process.stdin;
      for await (const chunk of stream) {
        const bytes = Buffer.from(chunk); size += bytes.length;
        if (size > ECONOMY_MAX_BYTES) { stream.destroy(); throw new Error(`Input exceeds ${ECONOMY_MAX_BYTES} byte capture limit`); }
        parts.push(bytes);
      }
      const result = await new Economy(opts.repo).capture(Buffer.concat(parts), { budget: Number(opts.budget) });
      process.stdout.write(result.text);
    });
  options(program.command('read').description('Recover an economy handle; ranges use end-exclusive byte offsets').argument('<handle>'))
    .option('--start <byte>', 'first byte offset').option('--end <byte>', 'exclusive last byte offset')
    .option('--search <text>', 'start at the first exact UTF-8 match within the range')
    .option('--raw', 'emit exact bytes, explicitly bypassing the preview budget')
    .action(async (handle, opts) => {
      const result = await new Economy(opts.repo).read(handle, { budget: Number(opts.budget), raw: opts.raw,
        start: opts.start === undefined ? undefined : Number(opts.start), end: opts.end === undefined ? undefined : Number(opts.end), search: opts.search });
      process.stdout.write(opts.raw ? result.bytes : result.text);
    });
  options(program.command('run').description('Execute argv once; use -- before the command and its arguments').argument('<argv...>'))
    .option('--max-bytes <bytes>', 'combined stdout/stderr capture limit', String(ECONOMY_MAX_BYTES))
    .option('--timeout-ms <ms>', 'execution and pipe timeout', '300000')
    .action(async (argv, opts) => {
      const result = await new Economy(opts.repo).run(argv, { budget: Number(opts.budget), maxBytes: Number(opts.maxBytes), timeoutMs: Number(opts.timeoutMs) });
      await new Promise<void>((resolve, reject) => process.stdout.write(result.text, error => error ? reject(error) : resolve()));
      if (result.signal) process.kill(process.pid, result.signal);
      else process.exitCode = result.status ?? 1;
    });
  const economy = program.command('economy').description('Offline captured-payload accounting');
  economy.command('clear').description('Delete all local economy objects and accounting; invalidates every handle. Stop active captures first.')
    .requiredOption('--all', 'explicitly delete all captured payloads and the ledger')
    .option('--repo <path>', 'repository root', '.')
    .action(async opts => { await new Economy(opts.repo).clear(); process.stdout.write('Economy store cleared; prior handles are now missing.\n'); });
  economy.command('stats')
    .option('--repo <path>', 'repository root', '.')
    .action(async opts => { process.stdout.write(JSON.stringify(await new Economy(opts.repo).stats(), null, 2) + '\n'); });
}
