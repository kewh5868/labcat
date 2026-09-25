export const publicSourceIds = [
  "hybrid3",
  "nomad",
  "europe_pmc",
  "arxiv",
  "wikipedia",
  "openalex",
  "chemrxiv",
  "public_dielectric",
] as const;
export type PublicSourceId = (typeof publicSourceIds)[number];
export interface SourceAvailability {
  requires_credentials: boolean;
  selectable: boolean;
  status:
    | "not_configured"
    | "locked"
    | "verification_required"
    | "ready"
    | "error";
  verified_at?: string | null;
  message?: string;
}
export interface PublicSource {
  id: PublicSourceId;
  name: string;
  description: string;
  homepage: string;
  documentation_url: string;
  requires_credentials: false;
  kind: string;
  scope: string;
  availability?: SourceAvailability;
}
export interface ConnectedSource
  extends Omit<
    PublicSource,
    "id" | "requires_credentials" | "availability" | "scope"
  > {
  scope?: string;
  id: "materials_project";
  requires_credentials: true;
  availability: SourceAvailability;
}
export interface SourceRegistry {
  sources: PublicSource[];
  connected_sources: ConnectedSource[];
}
export interface SourceSettings {
  search_public_references: boolean;
  enabled_sources: PublicSourceId[];
  materials_project_mode: "auto" | "snapshot" | "api" | "off";
  max_results_per_source: number;
}
function invalid() {
  return new Error(
    "Public source settings returned an unsupported response. Reload source settings.",
  );
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw invalid();
  return value as Record<string, unknown>;
}
function exact(value: Record<string, unknown>, keys: string[]) {
  if (
    Object.keys(value).length !== keys.length ||
    !keys.every((key) => Object.hasOwn(value, key))
  )
    throw invalid();
}
function sourceId(value: unknown): value is PublicSourceId {
  return publicSourceIds.includes(value as PublicSourceId);
}
function safeLink(value: unknown) {
  if (typeof value !== "string") throw invalid();
  const url = new URL(value);
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)
  )
    throw invalid();
}
function settings(value: unknown): SourceSettings {
  const item = object(value);
  exact(item, [
    "search_public_references",
    "enabled_sources",
    "materials_project_mode",
    "max_results_per_source",
  ]);
  if (
    typeof item.search_public_references !== "boolean" ||
    !Array.isArray(item.enabled_sources) ||
    !item.enabled_sources.every(sourceId) ||
    new Set(item.enabled_sources).size !== item.enabled_sources.length ||
    !["auto", "snapshot", "api", "off"].includes(
      item.materials_project_mode as string,
    ) ||
    !Number.isSafeInteger(item.max_results_per_source) ||
    Number(item.max_results_per_source) < 1 ||
    Number(item.max_results_per_source) > 10
  )
    throw invalid();
  return item as unknown as SourceSettings;
}
async function request(
  path: string,
  options: { method?: string; body?: unknown; signal?: AbortSignal } = {},
): Promise<unknown> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  options.signal?.addEventListener("abort", abort, { once: true });
  if (options.signal?.aborted) controller.abort();
  const timer = window.setTimeout(abort, 15000);
  try {
    const response = await fetch(path, {
      method: options.method ?? "GET",
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal: controller.signal,
    });
    if (!response.ok)
      throw new Error(
        response.status === 409
          ? "Public source verification is required. Connect and test the API in Connections, or choose another source."
          : `Public source request failed (${response.status}). Reload saved source settings before trying again.`,
      );
    return await response.json();
  } catch (error) {
    if (options.signal?.aborted) throw error;
    if (error instanceof Error && error.message.startsWith("Public source"))
      throw error;
    throw new Error(
      "Public source settings could not be reached. Check that the local application is running.",
    );
  } finally {
    window.clearTimeout(timer);
    options.signal?.removeEventListener("abort", abort);
  }
}
export const publicSourcesApi = {
  async catalog(signal?: AbortSignal): Promise<PublicSource[]> {
    return (await registry(signal)).sources;
  },
  registry,
  async settings(signal?: AbortSignal) {
    return settings(await request("/api/source-settings", { signal }));
  },
  async save(value: SourceSettings) {
    settings(value);
    return settings(
      await request("/api/source-settings", { method: "PUT", body: value }),
    );
  },
};
async function registry(signal?: AbortSignal): Promise<SourceRegistry> {
  const data = object(await request("/api/public-sources", { signal }));
  exact(data, [
    "sources",
    ...(data.connected_sources === undefined ? [] : ["connected_sources"]),
  ]);
  if (
    !Array.isArray(data.sources) ||
    (data.connected_sources !== undefined &&
      !Array.isArray(data.connected_sources))
  )
    throw invalid();
  function parse(value: unknown, connected: boolean) {
    const item = object(value);
    exact(item, [
      "id",
      "name",
      "description",
      "homepage",
      "documentation_url",
      "requires_credentials",
      "kind",
      ...(!connected || item.scope !== undefined ? ["scope"] : []),
      ...(item.availability === undefined ? [] : ["availability"]),
    ]);
    if (
      (connected
        ? item.id !== "materials_project" || item.requires_credentials !== true
        : !sourceId(item.id) || item.requires_credentials !== false) ||
      ![
        "name",
        "description",
        "kind",
        ...(!connected || item.scope !== undefined ? ["scope"] : []),
      ].every((key) => typeof item[key] === "string")
    )
      throw invalid();
    safeLink(item.homepage);
    safeLink(item.documentation_url);
    if (connected && item.availability === undefined) throw invalid();
    if (item.availability !== undefined) {
      const availability = object(item.availability);
      const names = [
        "requires_credentials",
        "selectable",
        "status",
        ...(availability.verified_at === undefined ? [] : ["verified_at"]),
        ...(availability.message === undefined ? [] : ["message"]),
      ];
      exact(availability, names);
      if (
        availability.requires_credentials !== connected ||
        typeof availability.selectable !== "boolean" ||
        ![
          "not_configured",
          "locked",
          "verification_required",
          "ready",
          "error",
        ].includes(availability.status as string) ||
        availability.selectable !== (availability.status === "ready") ||
        (!connected && !availability.selectable) ||
        (availability.message !== undefined &&
          (typeof availability.message !== "string" ||
            availability.message.length > 2000)) ||
        (availability.verified_at !== undefined &&
          availability.verified_at !== null &&
          (typeof availability.verified_at !== "string" ||
            Number.isNaN(Date.parse(availability.verified_at))))
      )
        throw invalid();
    }
    return item;
  }
  // This dataset supports backend retrieval, but is not a primary database choice.
  // Keep its ID in saved settings so unrelated UI edits preserve backend access.
  return {
    sources: data.sources
      .map((item) => parse(item, false) as unknown as PublicSource)
      .filter((source) => source.id !== "public_dielectric"),
    connected_sources: ((data.connected_sources ?? []) as unknown[]).map(
      (item) => parse(item, true) as unknown as ConnectedSource,
    ),
  };
}
export function publicSourceError(error: unknown) {
  return error instanceof Error && error.message.startsWith("Public source")
    ? error.message
    : "Public source settings could not be saved. Reload settings before trying again.";
}
