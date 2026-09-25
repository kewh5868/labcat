export type StructureTarget = { kind: "material" | "lead"; id: string };

export type ReferenceStatus =
  | "cited_record_available"
  | "reference_lookup_available"
  | "references_found"
  | "no_reference_matches"
  | "reference_lookup_failed"
  | "unsupported";
export interface StructureComponent {
  component_id: string;
  formula: string;
  label: string;
  status: ReferenceStatus;
  reason?: string;
}
export interface ComponentAssociation {
  lead_id: string;
  component_id: string;
  formula: string;
  label: string;
}

export interface StructureRecord {
  material_id: string;
  formula: string;
  source_formula?: string;
  status: "not_loaded" | "ready" | "unsupported" | "connection_required";
  source_name: string;
  source_url: string;
  caveats: string[];
  reason?: string;
  id?: string;
  filename?: string;
  download_url?: string;
  sha256?: string;
  retrieved_at?: string;
  n_sites?: number;
  structure_match?: "source_metadata_match" | "composition_reference";
  structure_source_url?: string;
  structure_differences?: string[];
  literature_association?: {
    relation:
      | "cited_repository_record"
      | "composition_reference"
      | "component_reference";
    phase_match: "unverified";
    lead_ids: string[];
    lead_names: string[];
    components?: ComponentAssociation[];
  };
  source_cif?: {
    filename: string;
    block: string;
    sha256: string;
    archive_sha256: string;
    download_url: string;
  };
}
export interface LiteratureStructureCandidate {
  lead_id: string;
  name: string;
  rank?: number;
  reason?: string;
  status: ReferenceStatus;
  components?: StructureComponent[];
}
export interface ReportStructures {
  viewer_enabled: boolean;
  structures: StructureRecord[];
  literature_candidates?: LiteratureStructureCandidate[];
}

const invalid = () =>
  new Error(
    "The structure service returned an unsupported response. Try refreshing availability.",
  );
const scope = (chatId: string, reportId: string) =>
  `/api/chats/${encodeURIComponent(chatId)}/reports/${encodeURIComponent(reportId)}/structures`;
const candidatePath = (chatId: string, reportId: string, materialId: string) =>
  `${scope(chatId, reportId)}/${encodeURIComponent(materialId)}`;
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw invalid();
  return value as Record<string, unknown>;
}
function text(value: unknown, max = 2000): value is string {
  return typeof value === "string" && value.length <= max;
}
export function structureSourceLink(value: string): string | null {
  try {
    const url = new URL(value);
    const approved =
      [
        "materialsproject.org",
        "next-gen.materialsproject.org",
        "nomad-lab.eu",
      ].includes(url.hostname) ||
      (url.hostname === "materials.hybrid3.duke.edu" &&
        /^\/materials\/dataset\/[1-9][0-9]{0,8}$/.test(url.pathname) &&
        !url.search &&
        !url.hash) ||
      (url.hostname === "doi.org" &&
        url.pathname === "/10.6084/m9.figshare.7108790.v2" &&
        !url.search &&
        !url.hash);
    return url.protocol === "https:" &&
      !url.username &&
      !url.password &&
      !url.port &&
      approved
      ? url.href
      : null;
  } catch {
    return null;
  }
}
const referenceStatuses: ReferenceStatus[] = [
  "cited_record_available",
  "reference_lookup_available",
  "references_found",
  "no_reference_matches",
  "reference_lookup_failed",
  "unsupported",
];
function componentIdentity(value: unknown): boolean {
  const component = object(value);
  return (
    typeof component.component_id === "string" &&
    /^component-[a-f0-9]{24}$/.test(component.component_id) &&
    text(component.formula, 256) &&
    Boolean(component.formula.trim()) &&
    text(component.label, 120) &&
    Boolean(component.label.trim())
  );
}
function parseStructure(
  value: unknown,
  chatId: string,
  reportId: string,
): StructureRecord {
  const item = object(value);
  if (
    !text(item.material_id, 256) ||
    !item.material_id ||
    !text(item.formula, 256) ||
    (item.source_formula !== undefined && !text(item.source_formula, 256)) ||
    !text(item.source_name, 200) ||
    !text(item.source_url, 1000) ||
    !["not_loaded", "ready", "unsupported", "connection_required"].includes(
      item.status as string,
    ) ||
    !Array.isArray(item.caveats) ||
    item.caveats.length > 30 ||
    !item.caveats.every((entry) => text(entry)) ||
    (item.reason !== undefined && !text(item.reason))
  )
    throw invalid();
  if (
    item.status !== "ready" &&
    [
      item.source_cif,
      item.structure_match,
      item.structure_source_url,
      item.structure_differences,
    ].some((field) => field !== undefined)
  )
    throw invalid();
  if (item.literature_association !== undefined) {
    const association = object(item.literature_association);
    if (
      ![
        "cited_repository_record",
        "composition_reference",
        "component_reference",
      ].includes(association.relation as string) ||
      association.phase_match !== "unverified" ||
      !Array.isArray(association.lead_ids) ||
      association.lead_ids.length < 1 ||
      association.lead_ids.length > 12 ||
      !association.lead_ids.every(
        (id) => typeof id === "string" && /^lead-[a-f0-9]{24}$/.test(id),
      ) ||
      new Set(association.lead_ids).size !== association.lead_ids.length ||
      !Array.isArray(association.lead_names) ||
      association.lead_names.length !== association.lead_ids.length ||
      !association.lead_names.every((name) => text(name, 120) && name.trim())
    )
      throw invalid();
    if (association.components !== undefined) {
      if (
        !Array.isArray(association.components) ||
        !association.components.length ||
        association.components.length > 36 ||
        !association.components.every((value) => {
          const component = object(value);
          return (
            componentIdentity(component) &&
            (association.lead_ids as string[]).includes(
              component.lead_id as string,
            )
          );
        }) ||
        new Set(
          association.components.map(
            (entry) => `${entry.lead_id}:${entry.component_id}`,
          ),
        ).size !== association.components.length
      )
        throw invalid();
    }
    if (
      association.relation === "component_reference" &&
      !association.components
    )
      throw invalid();
  }
  if (item.status === "ready") {
    const hybrid =
      /^hybrid3:([1-9][0-9]{0,8}):dataset([1-9][0-9]{0,8}):subset([1-9][0-9]{0,8})$/.exec(
        item.material_id,
      );
    if (
      (!hybrid &&
        !/^(mp-\d{1,10}|nomad:[A-Za-z0-9_-]{1,80}|dielectric:mp-\d{1,10}(?::row\d{1,4})?)$/.test(
          item.material_id,
        )) ||
      (hybrid &&
        item.source_url !==
          `https://materials.hybrid3.duke.edu/materials/dataset/${hybrid[2]}`) ||
      !text(item.filename, 200) ||
      !/^[A-Za-z0-9_.-]+\.cif$/.test(item.filename) ||
      item.download_url !==
        `${candidatePath(chatId, reportId, item.material_id)}/download` ||
      !text(item.sha256, 64) ||
      !/^[a-f0-9]{64}$/.test(item.sha256) ||
      !text(item.retrieved_at, 80) ||
      !Number.isFinite(Date.parse(item.retrieved_at)) ||
      !Number.isSafeInteger(item.n_sites) ||
      Number(item.n_sites) < 1 ||
      Number(item.n_sites) > 20000 ||
      !structureSourceLink(item.source_url)
    )
      throw invalid();
    if (
      item.source_cif !== undefined ||
      item.structure_match !== undefined ||
      item.structure_source_url !== undefined ||
      item.structure_differences !== undefined
    ) {
      const sourceCif = object(item.source_cif);
      if (
        !hybrid ||
        !["source_metadata_match", "composition_reference"].includes(
          item.structure_match as string,
        ) ||
        !text(item.structure_source_url, 200) ||
        !/^https:\/\/materials\.hybrid3\.duke\.edu\/materials\/dataset\/[1-9][0-9]{0,8}$/.test(
          item.structure_source_url,
        ) ||
        !Array.isArray(item.structure_differences) ||
        item.structure_differences.length > 6 ||
        !item.structure_differences.every((entry) => text(entry, 200)) ||
        item.structure_differences.length > 0 !==
          (item.structure_match === "composition_reference") ||
        !text(sourceCif.filename, 124) ||
        !/^[A-Za-z0-9_.-]+\.cif$/i.test(sourceCif.filename) ||
        !text(sourceCif.block, 80) ||
        !/^[A-Za-z0-9_.-]+$/.test(sourceCif.block) ||
        !text(sourceCif.sha256, 64) ||
        !/^[a-f0-9]{64}$/.test(sourceCif.sha256) ||
        !text(sourceCif.archive_sha256, 64) ||
        !/^[a-f0-9]{64}$/.test(sourceCif.archive_sha256) ||
        sourceCif.download_url !==
          `${candidatePath(chatId, reportId, item.material_id)}/original`
      )
        throw invalid();
    }
  }
  return item as unknown as StructureRecord;
}
async function request(
  path: string,
  signal: AbortSignal,
  method = "GET",
  csrfToken?: string,
): Promise<Response> {
  const response = await fetch(path, {
    method,
    signal,
    headers: {
      Accept: "application/json",
      ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
    },
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
  });
  if (!response.ok) {
    if (response.status === 409)
      throw new Error(
        "The structure is not ready. Check the source connection in Connections, then refresh availability.",
      );
    if (response.status === 404)
      throw new Error(
        "This saved material or structure is no longer available. Refresh availability.",
      );
    if (response.status === 422) {
      const payload = await response.json().catch(() => null);
      const messages: Record<string, string> = {
        structure_access_unverified:
          "The public structure source did not confirm open access for this record. Labcat cannot retrieve it until public access can be verified.",
        structure_source_unavailable:
          "The public structure source is temporarily unavailable. You can try this material again later.",
        structure_busy:
          "The structure service is already handling a request. Wait for it to finish, then try again.",
        structure_missing:
          "The public structure source lists no atomic-structure datasets for this material.",
        structure_ambiguous:
          "The public structure source has several equally close structures. The saved record does not identify a unique structure.",
        structure_search_incomplete:
          "The public structure source has more datasets than the bounded search can inspect. Structure matching remains incomplete.",
        structure_invalid:
          "A supported, validated structure could not be obtained for this material. No structure is displayed.",
        structure_reference_unsupported:
          "This saved material does not identify a complete composition that the reference search can use. No structure was substituted.",
      };
      const code: unknown = payload?.detail?.code;
      throw new Error(
        typeof code === "string" && Object.hasOwn(messages, code)
          ? messages[code]
          : messages.structure_invalid,
      );
    }
    throw new Error(
      "The public structure could not be retrieved. Please try again later.",
    );
  }
  return response;
}
function parseList(
  value: unknown,
  chatId: string,
  reportId: string,
): ReportStructures {
  const item = object(value);
  if (
    typeof item.viewer_enabled !== "boolean" ||
    !Array.isArray(item.structures) ||
    item.structures.length > 250
  )
    throw invalid();
  const structures = item.structures.map((entry) =>
    parseStructure(entry, chatId, reportId),
  );
  if (
    new Set(structures.map((entry) => entry.material_id)).size !==
    structures.length
  )
    throw invalid();
  const leads = item.literature_candidates ?? [];
  if (
    !Array.isArray(leads) ||
    leads.length > 12 ||
    !leads.every((value) => {
      const lead = object(value);
      return (
        typeof lead.lead_id === "string" &&
        /^lead-[a-f0-9]{24}$/.test(lead.lead_id) &&
        text(lead.name, 120) &&
        lead.name.trim() &&
        referenceStatuses.includes(lead.status as ReferenceStatus) &&
        (lead.components === undefined ||
          (Array.isArray(lead.components) &&
            lead.components.length > 0 &&
            lead.components.length <= 3 &&
            lead.components.every((value) => {
              const component = object(value);
              return (
                componentIdentity(component) &&
                referenceStatuses.includes(
                  component.status as ReferenceStatus,
                ) &&
                (component.reason === undefined || text(component.reason))
              );
            }) &&
            new Set(lead.components.map((component) => component.component_id))
              .size === lead.components.length)) &&
        (lead.rank === undefined ||
          (Number.isSafeInteger(lead.rank) &&
            Number(lead.rank) > 0 &&
            Number(lead.rank) <= 200)) &&
        (lead.reason === undefined || text(lead.reason))
      );
    }) ||
    new Set(leads.map((lead) => lead.lead_id)).size !== leads.length
  )
    throw invalid();
  for (const structure of structures) {
    for (const component of structure.literature_association?.components ??
      []) {
      const matching = leads
        .find((lead) => lead.lead_id === component.lead_id)
        ?.components?.find(
          (entry: StructureComponent) =>
            entry.component_id === component.component_id,
        );
      if (
        !matching ||
        matching.formula !== component.formula ||
        matching.label !== component.label
      )
        throw invalid();
    }
  }
  return {
    viewer_enabled: item.viewer_enabled,
    structures,
    literature_candidates: leads as LiteratureStructureCandidate[],
  };
}
async function csrf(signal: AbortSignal): Promise<string> {
  const session = object(await (await request("/api/session", signal)).json());
  if (
    !text(session.csrf_token, 200) ||
    !/^[A-Za-z0-9_-]{20,200}$/.test(session.csrf_token)
  )
    throw invalid();
  return session.csrf_token;
}
export const structureApi = {
  async list(
    chatId: string,
    reportId: string,
    signal: AbortSignal,
  ): Promise<ReportStructures> {
    return parseList(
      await (await request(scope(chatId, reportId), signal)).json(),
      chatId,
      reportId,
    );
  },
  async references(
    chatId: string,
    reportId: string,
    leadId: string,
    signal: AbortSignal,
  ): Promise<ReportStructures> {
    if (!/^lead-[a-f0-9]{24}$/.test(leadId)) throw invalid();
    return parseList(
      await (
        await request(
          `${scope(chatId, reportId)}/references/${encodeURIComponent(leadId)}`,
          signal,
          "POST",
          await csrf(signal),
        )
      ).json(),
      chatId,
      reportId,
    );
  },
  async retrieve(
    chatId: string,
    reportId: string,
    materialId: string,
    signal: AbortSignal,
  ): Promise<StructureRecord> {
    const item = parseStructure(
      await (
        await request(
          candidatePath(chatId, reportId, materialId),
          signal,
          "POST",
          await csrf(signal),
        )
      ).json(),
      chatId,
      reportId,
    );
    if (item.material_id !== materialId || item.status !== "ready")
      throw invalid();
    return item;
  },
  async content(
    chatId: string,
    reportId: string,
    materialId: string,
    signal: AbortSignal,
  ): Promise<string> {
    const response = await request(
      `${candidatePath(chatId, reportId, materialId)}/content`,
      signal,
    );
    if (
      !/^(chemical\/x-cif|text\/plain)(?:;|$)/i.test(
        response.headers.get("Content-Type") ?? "",
      )
    )
      throw invalid();
    const cif = await response.text();
    if (
      !cif
        .split(/\r?\n/)
        .filter((line) => line && !line.startsWith("#"))[0]
        ?.startsWith("data_") ||
      cif.length > 500_000 ||
      cif.includes("\0")
    )
      throw invalid();
    return cif;
  },
};
export function structureError(error: unknown): string {
  return error instanceof Error &&
    /^(The structure|The public structure|This saved material|A supported, validated)/.test(
      error.message,
    )
    ? error.message
    : "The structure service could not be reached. Check that the application is running and try again.";
}
