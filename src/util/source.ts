import { closeSync, constants, fstatSync, openSync, readFileSync, realpathSync } from "node:fs";
import { isAbsolute, relative, resolve, sep } from "node:path";

/** Read source text, decoding Windows tooling's common UTF-16LE output. UTF-16BE
 * is rare and unsupported by Node's built-in decoders, so callers silently skip it. */
export function readSourceFile(path: string): string | null {
  return decodeSource(readFileSync(path));
}

function decodeSource(bytes: Buffer): string | null {
  if (bytes[0] === 0xfe && bytes[1] === 0xff) return null;
  if (bytes[0] === 0xff && bytes[1] === 0xfe) return bytes.subarray(2).toString("utf16le");
  return bytes.toString("utf8");
}

/** Read a small regular file without following aliases within the repository. */
export function readScopedSource(root: string, path: string, maxBytes: number): string | null {
  try {
    const absolute = resolve(root, path);
    const local = relative(root, absolute);
    if (!local || isAbsolute(local) || local === '..' || local.startsWith(`..${sep}`)) return null;
    if (realpathSync(absolute) !== resolve(realpathSync(root), local)) return null;
    const fd = openSync(absolute, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0) | (constants.O_NONBLOCK ?? 0));
    try {
      const stat = fstatSync(fd);
      if (!stat.isFile() || stat.size > maxBytes) return null;
      const bytes = readFileSync(fd);
      return bytes.length <= maxBytes ? decodeSource(bytes) : null;
    } finally { closeSync(fd); }
  } catch { return null; }
}
