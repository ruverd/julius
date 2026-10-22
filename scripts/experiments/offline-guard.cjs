// Experiment-only preload. Both executables run with the same restrictions.
const fs = require('node:fs');
const deny = (operation) => {
  fs.appendFileSync(process.env.JULIUS_PROBE_GUARD_LOG, `${operation}\n`);
  throw new Error(`Offline experiment blocked ${operation}`);
};
globalThis.fetch = () => deny('fetch');
for (const name of ['http', 'https']) {
  const module = require(`node:${name}`);
  for (const method of ['request', 'get']) module[method] = () => deny(`${name}.${method}`);
}
require('node:net').Socket.prototype.connect = () => deny('net.connect');
require('node:dgram').createSocket = () => deny('dgram.createSocket');
const child = require('node:child_process');
for (const method of ['spawn', 'spawnSync', 'execFile', 'execFileSync']) {
  const original = child[method];
  child[method] = function (command, ...args) {
    if (require('node:path').basename(String(command)) !== 'git') return deny(`child.${method}:${command}`);
    return original.call(this, command, ...args);
  };
}
for (const method of ['exec', 'execSync', 'fork']) child[method] = () => deny(`child.${method}`);
require('node:module').syncBuiltinESMExports();
