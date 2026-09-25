export interface Attribute {
  id: string;
  label: string;
  category: string;
  description: string;
  source_field: string | null;
  supported: boolean;
  availability_note: string;
}
export interface ScopeOption {
  id: string;
  label: string;
  scope: string;
}
export interface RankingProfile {
  id: string;
  name: string;
  material_class: string;
  application: string;
  importance: Record<string, number>;
  normalized_weights: Record<string, number>;
  minimum_band_gap_ev?: number | null;
  target_band_gap_ev?: number | null;
  band_gap_tolerance_ev?: number | null;
  preset: boolean;
  created_at: string;
  updated_at: string;
}
export interface RankingProfiles {
  catalog: {
    attributes: Attribute[];
    material_classes: ScopeOption[];
    applications: ScopeOption[];
  };
  profiles: RankingProfile[];
  active_profile_id: string;
}
export type ProfileInput = Pick<
  RankingProfile,
  | "name"
  | "material_class"
  | "application"
  | "importance"
  | "minimum_band_gap_ev"
  | "target_band_gap_ev"
  | "band_gap_tolerance_ev"
>;
function invalid() {
  return new Error(
    "The ranking settings returned an unsupported response. Reload saved ranking profiles.",
  );
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw invalid();
  return value as Record<string, unknown>;
}
function strings(value: Record<string, unknown>, keys: string[]) {
  if (!keys.every((key) => typeof value[key] === "string")) throw invalid();
}
function numbers(value: unknown): Record<string, number> {
  const item = object(value);
  if (
    !Object.keys(item).length ||
    !Object.values(item).every(
      (v) => typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 1,
    )
  )
    throw invalid();
  return item as Record<string, number>;
}
export function validMinimumBandGap(
  value: unknown,
): value is number | null | undefined {
  return (
    value === null ||
    value === undefined ||
    (typeof value === "number" &&
      Number.isFinite(value) &&
      value >= 0 &&
      value <= 100)
  );
}
export function validBandGapTarget(
  target: unknown,
  tolerance: unknown,
): boolean {
  return (
    validMinimumBandGap(target) &&
    (tolerance === null ||
      tolerance === undefined ||
      (typeof target === "number" &&
        typeof tolerance === "number" &&
        Number.isFinite(tolerance) &&
        tolerance > 0 &&
        tolerance <= 100))
  );
}
function profile(value: unknown): RankingProfile {
  const item = object(value);
  strings(item, [
    "id",
    "name",
    "material_class",
    "application",
    "created_at",
    "updated_at",
  ]);
  if (
    typeof item.preset !== "boolean" ||
    !validMinimumBandGap(item.minimum_band_gap_ev) ||
    !validBandGapTarget(item.target_band_gap_ev, item.band_gap_tolerance_ev)
  )
    throw invalid();
  numbers(item.importance);
  numbers(item.normalized_weights);
  if (
    Object.keys(item.importance as object)
      .sort()
      .join() !==
    Object.keys(item.normalized_weights as object)
      .sort()
      .join()
  )
    throw invalid();
  return item as unknown as RankingProfile;
}
async function request(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<unknown> {
  const controller = new AbortController(),
    abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) controller.abort();
  const timer = window.setTimeout(abort, 15000);
  try {
    const response = await fetch(path, {
      method,
      headers: {
        Accept: "application/json",
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal: controller.signal,
    });
    if (!response.ok)
      throw new Error(
        `The ranking settings request failed (${response.status}). Reload saved ranking profiles before retrying.`,
      );
    return await response.json();
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error instanceof Error && error.message.startsWith("The ranking"))
      throw error;
    throw new Error(
      "The ranking settings service could not be reached. Reload saved ranking profiles before retrying.",
    );
  } finally {
    window.clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}
export const rankingProfilesApi = {
  async list(signal?: AbortSignal): Promise<RankingProfiles> {
    const data = object(
        await request("/api/ranking-profiles", "GET", undefined, signal),
      ),
      catalog = object(data.catalog);
    if (
      !Array.isArray(catalog.attributes) ||
      !Array.isArray(data.profiles) ||
      typeof data.active_profile_id !== "string"
    )
      throw invalid();
    const attributes = catalog.attributes.map((value) => {
      const item = object(value);
      strings(item, [
        "id",
        "label",
        "category",
        "description",
        "availability_note",
      ]);
      if (
        (item.source_field !== null && typeof item.source_field !== "string") ||
        typeof item.supported !== "boolean"
      )
        throw invalid();
      return item as unknown as Attribute;
    });
    function scopes(value: unknown): ScopeOption[] {
      if (!Array.isArray(value)) throw invalid();
      return value.map((item) => {
        const parsed = object(item);
        strings(parsed, ["id", "label", "scope"]);
        return parsed as unknown as ScopeOption;
      });
    }
    const profiles = data.profiles.map(profile);
    if (!profiles.some((item) => item.id === data.active_profile_id))
      throw invalid();
    if (
      profiles.some((item) =>
        Object.keys(item.importance).some(
          (id) => !attributes.some((attribute) => attribute.id === id),
        ),
      )
    )
      throw invalid();
    return {
      catalog: {
        attributes,
        material_classes: scopes(catalog.material_classes),
        applications: scopes(catalog.applications),
      },
      profiles,
      active_profile_id: data.active_profile_id,
    };
  },
  async save(value: ProfileInput, id?: string) {
    if (
      !validMinimumBandGap(value.minimum_band_gap_ev) ||
      !validBandGapTarget(value.target_band_gap_ev, value.band_gap_tolerance_ev)
    )
      throw invalid();
    return profile(
      await request(
        id
          ? `/api/ranking-profiles/${encodeURIComponent(id)}`
          : "/api/ranking-profiles",
        id ? "PUT" : "POST",
        value,
      ),
    );
  },
  async activate(id: string) {
    const result = object(
      await request(
        `/api/ranking-profiles/${encodeURIComponent(id)}/activate`,
        "POST",
        {},
      ),
    );
    if (result.active_profile_id !== id) throw invalid();
    const active = profile(result.profile);
    if (active.id !== id) throw invalid();
    return active;
  },
};
export function relativeWeights(
  importance: Record<string, number>,
): Record<string, number> {
  const sum = Object.values(importance).reduce(
    (total, value) => total + (Number.isFinite(value) ? value : 0),
    0,
  );
  return Object.fromEntries(
    Object.entries(importance).map(([key, value]) => [
      key,
      sum > 0 && Number.isFinite(value) ? value / sum : 0,
    ]),
  );
}
export function matchingPreset(
  profiles: RankingProfile[],
  materialClass: string,
  application?: string,
): RankingProfile | undefined {
  return profiles.find(
    (profile) =>
      profile.preset &&
      profile.material_class === materialClass &&
      (!application || profile.application === application),
  );
}
