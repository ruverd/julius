/** The local graph cache lives under Julius state for every repository. */
import { join } from "node:path";
export const JULIUS_MAP_DIR = join(".julius", "cache");
export function mapDirFor(root: string): string { return join(root, JULIUS_MAP_DIR); }
export function isJuliusMapDir(root: string, dir: string): boolean { return join(root, JULIUS_MAP_DIR) === join(dir); }
