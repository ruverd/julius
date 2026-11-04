import { resolve } from "node:path";

// Capture executable-code configuration before CLI dotenv loads repository data.
export const RUST_EXTRACTOR_PATH = process.env.JULIUS_RUST_EXTRACTOR_PATH
  ? resolve(process.env.JULIUS_RUST_EXTRACTOR_PATH)
  : undefined;
