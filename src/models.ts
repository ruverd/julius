export interface AdapterCapabilities {
  canObserveUsage: boolean;
  canOptimizeInput: boolean;
  canImportUsage: boolean;
  liveCompatibilityTested: boolean;
}

const unsupportedCapabilities: AdapterCapabilities = {
  canObserveUsage: false, canOptimizeInput: false, canImportUsage: false,
  liveCompatibilityTested: false,
};

export interface ClientDiscovery {
  name: "claude" | "codex";
  executable: string;
  installed: boolean;
  version: string | null;
  capability: "observe_only" | "unsupported";
  capabilities: AdapterCapabilities;
  detail: string;
}

export interface DoctorResult { clients: ClientDiscovery[] }

async function probe(name: "claude" | "codex"): Promise<ClientDiscovery> {
  const base = { name, executable: name };
  try {
    const process = Bun.spawn([name, "--version"], { stdout: "pipe", stderr: "pipe" });
    const timeout = setTimeout(() => process.kill(), 2000);
    try {
      const [stdout, stderr, status] = await Promise.all([
        new Response(process.stdout).text(), new Response(process.stderr).text(), process.exited,
      ]);
      const version = (stdout || stderr).trim().split("\n")[0]?.slice(0, 200) || null;
      if (status !== 0 || !version) return { ...base, installed: false, version: null, capability: "unsupported", capabilities: unsupportedCapabilities, detail: "Version probe failed" };
      return { ...base, installed: true, version, capability: "unsupported", capabilities: unsupportedCapabilities, detail: "Executable detected; no live integration capability verified" };
    } finally { clearTimeout(timeout); }
  } catch {
    return { ...base, installed: false, version: null, capability: "unsupported", capabilities: unsupportedCapabilities, detail: "Executable unavailable" };
  }
}

/** Non-destructive executable discovery. Does not inspect credentials or configuration. */
export async function doctor(): Promise<DoctorResult> {
  return { clients: await Promise.all([probe("claude"), probe("codex")]) };
}

export interface OllamaModel {
  id: string;
  name: string;
  digest: string | null;
  quantization: string | null;
  installed: boolean;
  loaded: boolean | null;
}

export interface OllamaDiscovery {
  endpoint: string;
  models: OllamaModel[];
  error: string | null;
}

interface RuntimeModel { name?: unknown; model?: unknown; digest?: unknown; details?: { quantization_level?: unknown } }

function entries(value: unknown): RuntimeModel[] {
  if (value === null || typeof value !== "object" || !("models" in value) || !Array.isArray(value.models)) throw new Error("Invalid Ollama model list");
  return value.models as RuntimeModel[];
}

function modelName(item: RuntimeModel): string | null {
  const value = item.model ?? item.name;
  return typeof value === "string" && value.length > 0 ? value : null;
}

function identity(endpoint: string, item: RuntimeModel): string | null {
  const name = modelName(item);
  if (!name) return null;
  const digest = typeof item.digest === "string" ? item.digest : "unknown";
  const quant = typeof item.details?.quantization_level === "string" ? item.details.quantization_level : "unknown";
  return `${endpoint}|${name}|${digest}|${quant}`;
}

async function requestModels(url: URL): Promise<RuntimeModel[]> {
  const response = await fetch(url, { signal: AbortSignal.timeout(2000), redirect: "error" });
  if (!response.ok) throw new Error(`Ollama ${url.pathname} returned HTTP ${response.status}`);
  return entries(await response.json());
}

/** Read-only discovery against a loopback Ollama endpoint. */
export async function discoverOllama(endpoint = "http://127.0.0.1:11434"): Promise<OllamaDiscovery> {
  let base: URL;
  try {
    base = new URL(endpoint);
    if (base.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(base.hostname) || base.username || base.password || base.pathname !== "/" || base.search || base.hash) {
      throw new Error("Ollama discovery requires a loopback HTTP endpoint");
    }
  } catch (error) {
    return { endpoint, models: [], error: error instanceof Error ? error.message : "Invalid endpoint" };
  }
  try {
    const installed = await requestModels(new URL("/api/tags", base));
    let loadedIds: Set<string> | null = null;
    let loadedError: string | null = null;
    try {
      const loaded = await requestModels(new URL("/api/ps", base));
      loadedIds = new Set(loaded.map((item) => identity(base.origin, item)).filter((id): id is string => id !== null));
    } catch (error) {
      loadedError = error instanceof Error ? error.message : "Ollama loaded-state discovery failed";
    }
    const models = installed.flatMap((item): OllamaModel[] => {
      const name = modelName(item);
      const id = identity(base.origin, item);
      if (!name || !id) return [];
      return [{ id, name, digest: typeof item.digest === "string" ? item.digest : null,
        quantization: typeof item.details?.quantization_level === "string" ? item.details.quantization_level : null,
        installed: true, loaded: loadedIds === null ? null : loadedIds.has(id) }];
    });
    return { endpoint: base.origin, models, error: loadedError };
  } catch (error) {
    return { endpoint: base.origin, models: [], error: error instanceof Error ? error.message : "Ollama discovery failed" };
  }
}
