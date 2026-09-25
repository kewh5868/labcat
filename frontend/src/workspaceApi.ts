export interface PinCounts {
  reports: number;
  sources: number;
}
export interface Project {
  id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  pin_counts: PinCounts;
  chat_count: number;
}
export interface Chat {
  id: string;
  project_id: string | null;
  title: string;
  created_at: string;
  updated_at: string;
  chat_number: number;
  display_title: string;
  pin_counts: PinCounts;
  message_count?: number;
}
export interface Message {
  id: string;
  chat_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  report_id: string | null;
  intake?: ResearchIntake;
}
export interface ResearchIntake {
  status: "accepted" | "clarification_required" | "refused";
  reason_code: string;
  questions: string[];
}
export interface ResearchStatus {
  run_id: string | null;
  status: "idle" | "running" | "completed" | "failed";
  phase: string;
  message: string;
  started_at: string | null;
  updated_at: string | null;
  sequence: number;
}
export interface ReportPin {
  id: string;
  project_id: string;
  mode: "snapshot" | "latest";
  chat_id: string;
  report_id: string | null;
  created_at: string;
  updated_at: string;
}
export interface ResearchReport {
  id: string;
  project_id: string | null;
  chat_id: string;
  message_id: string;
  title: string;
  stage: string;
  pi_summary: string;
  technical_audit: string;
  source_ids: string[];
  created_at: string;
  pinned: boolean;
  snapshot_pin?: ReportPin | null;
  tracking_pin?: ReportPin | null;
  latest_report_id?: string | null;
  pin?: ReportPin;
  result?: unknown;
}
export interface Source {
  id: string;
  project_id: string | null;
  title: string;
  url: string;
  source_name: string;
  access_scope: string;
  provenance_status: string;
  created_at: string;
  pinned: boolean;
  chat_ids: string[];
  report_ids: string[];
  kind?: string;
  is_material_evidence?: boolean;
}
export interface ChatDetail {
  chat: Chat;
  messages: Message[];
  reports: ResearchReport[];
  sources: Source[];
  report_tracking?: ReportPin | null;
}
export interface ProjectSearchMatch {
  project: Project;
  match_field: "name" | "description";
  snippet: string;
}
export interface ChatSearchMatch {
  chat: Chat;
  project_name: string | null;
  match_field: "title" | "message" | "report";
  snippet: string;
  message_id: string | null;
  report_id: string | null;
}
export interface WorkspaceSearchResults {
  query: string;
  projects: ProjectSearchMatch[];
  chats: ChatSearchMatch[];
  has_more: boolean;
}
export interface ProjectContents {
  chats: Chat[];
  reports: ResearchReport[];
  sources: Source[];
}
export interface RemovedProject extends Project {
  expires_at: string | null;
}
export interface RemovedChat extends Chat {
  expires_at: string | null;
}
export interface RemovedItems {
  projects: RemovedProject[];
  chats: RemovedChat[];
  retention_days: 30;
  snapshot: string;
}
export interface WorkspacePreferences {
  confirm_removal: boolean;
}
export interface About {
  name: string;
  version: string;
  developer: string;
  license: string;
  github_url: string | null;
}
export type PinKind = "report" | "source";
export type ReportView = "pi" | "audit";
export type ReportExportSection = ReportView | "sources";
export type ExportFormat = "text" | "json" | "pdf" | "docx";
export interface ReportLayout {
  page_size: "letter" | "a4";
  font_family: "sans" | "serif";
  font_size: 10 | 11 | 12;
  line_spacing: "compact" | "comfortable";
  accent: "sage" | "teal" | "slate";
  table_style: "striped" | "grid" | "minimal";
  page_numbers: boolean;
  text_width: 72 | 88 | 100;
  json_indent: 2 | 4;
}
export const defaultReportLayout: ReportLayout = {
  page_size: "letter",
  font_family: "sans",
  font_size: 11,
  line_spacing: "comfortable",
  accent: "sage",
  table_style: "striped",
  page_numbers: true,
  text_width: 88,
  json_indent: 2,
};
export interface ReportPresentation {
  style: ReportView;
  outputs: ReportView[];
  format: ExportFormat;
  terminology: "general" | "research" | "specialist";
  verbosity: "concise" | "standard" | "detailed";
  layout?: ReportLayout;
}
export interface SearchSettings {
  ranking: {
    stability: number;
    band_gap: number;
    element_screen: number;
    simplicity: number;
    evidence_quality: number;
  };
  presentation: ReportPresentation;
}
export const defaultSettings: SearchSettings = {
  ranking: {
    stability: 0.3,
    band_gap: 0.25,
    element_screen: 0.2,
    simplicity: 0.1,
    evidence_quality: 0.15,
  },
  presentation: {
    style: "pi",
    outputs: ["pi", "audit"],
    format: "text",
    terminology: "general",
    verbosity: "standard",
    layout: { ...defaultReportLayout },
  },
};

type RecordValue = Record<string, unknown>;
function record(value: unknown): RecordValue {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw invalid();
  return value as RecordValue;
}
function invalid() {
  return new Error(
    "The workspace returned an unsupported response. Please reload.",
  );
}
function fields(value: unknown, names: string[]): RecordValue {
  const item = record(value);
  if (!names.every((name) => typeof item[name] === "string")) throw invalid();
  return item;
}
function list<T>(value: unknown, parse: (item: unknown) => T): T[] {
  if (!Array.isArray(value)) throw invalid();
  return value.map(parse);
}
function strings(value: unknown): string[] {
  return list(value, (item) => {
    if (typeof item !== "string") throw invalid();
    return item;
  });
}
function project(value: unknown): Project {
  const item = fields(value, [
    "id",
    "name",
    "description",
    "created_at",
    "updated_at",
  ]);
  counts(item.pin_counts);
  if (!Number.isSafeInteger(item.chat_count) || Number(item.chat_count) < 0)
    throw invalid();
  return item as unknown as Project;
}
function counts(value: unknown) {
  const item = record(value);
  if (
    !["reports", "sources"].every(
      (key) => Number.isSafeInteger(item[key]) && Number(item[key]) >= 0,
    )
  )
    throw invalid();
}
function workspacePreferences(value: unknown): WorkspacePreferences {
  const item = record(value);
  if (
    Object.keys(item).length !== 1 ||
    typeof item.confirm_removal !== "boolean"
  )
    throw invalid();
  return { confirm_removal: item.confirm_removal };
}
function removalExpiry(value: unknown): string | null {
  if (value === null) return null;
  if (
    typeof value !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(
      value,
    ) ||
    !Number.isFinite(Date.parse(value))
  )
    throw invalid();
  return value;
}
function removalSnapshot(value: unknown): string {
  if (typeof value !== "string" || !/^[a-f0-9]{64}$/.test(value))
    throw invalid();
  return value;
}
function researchRunId(value: unknown): string {
  if (
    typeof value !== "string" ||
    !/^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(
      value,
    )
  )
    throw invalid();
  return value;
}
function researchStatus(value: unknown): ResearchStatus {
  const data = record(value);
  const keys = [
    "run_id",
    "status",
    "phase",
    "message",
    "started_at",
    "updated_at",
    "sequence",
  ];
  if (
    Object.keys(data).length !== keys.length ||
    !keys.every((key) => Object.hasOwn(data, key)) ||
    !["idle", "running", "completed", "failed"].includes(
      data.status as string,
    ) ||
    typeof data.phase !== "string" ||
    !/^[a-z][a-z0-9_]{0,63}$/.test(data.phase) ||
    typeof data.message !== "string" ||
    data.message.length > 500 ||
    /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(data.message) ||
    !Number.isSafeInteger(data.sequence) ||
    Number(data.sequence) < 0
  )
    throw invalid();
  if (data.status === "idle") {
    if (
      data.run_id !== null ||
      data.started_at !== null ||
      data.updated_at !== null
    )
      throw invalid();
  } else {
    researchRunId(data.run_id);
    if (
      !removalExpiry(data.started_at) ||
      !removalExpiry(data.updated_at) ||
      Date.parse(data.updated_at as string) <
        Date.parse(data.started_at as string)
    )
      throw invalid();
  }
  return data as unknown as ResearchStatus;
}
function chat(value: unknown, projectId?: string | null): Chat {
  const item = fields(value, [
    "id",
    "title",
    "display_title",
    "created_at",
    "updated_at",
  ]);
  if (
    !Number.isSafeInteger(item.chat_number) ||
    Number(item.chat_number) < 1 ||
    item.display_title !== `${item.title} · #${item.chat_number}`
  )
    throw invalid();
  if (item.project_id !== null && typeof item.project_id !== "string")
    throw invalid();
  if (projectId !== undefined && item.project_id !== projectId) throw invalid();
  counts(item.pin_counts);
  if (
    item.message_count !== undefined &&
    (!Number.isSafeInteger(item.message_count) ||
      Number(item.message_count) < 0)
  )
    throw invalid();
  return item as unknown as Chat;
}
function report(value: unknown, projectId: string | null): ResearchReport {
  const item = fields(value, [
    "id",
    "chat_id",
    "message_id",
    "title",
    "stage",
    "pi_summary",
    "technical_audit",
    "created_at",
  ]);
  if (item.project_id !== projectId || typeof item.pinned !== "boolean")
    throw invalid();
  strings(item.source_ids);
  if (
    item.latest_report_id !== undefined &&
    item.latest_report_id !== null &&
    typeof item.latest_report_id !== "string"
  )
    throw invalid();
  for (const [key, mode] of [
    ["snapshot_pin", "snapshot"],
    ["tracking_pin", "latest"],
    ["pin", undefined],
  ] as const) {
    if (item[key] === undefined || item[key] === null) continue;
    const pin = reportPin(item[key], projectId, item.chat_id as string);
    if (pin.report_id !== item.id || (mode && pin.mode !== mode))
      throw invalid();
  }
  return item as unknown as ResearchReport;
}
function reportPin(
  value: unknown,
  projectId: string | null,
  chatId?: string,
): ReportPin {
  const item = fields(value, [
    "id",
    "project_id",
    "mode",
    "chat_id",
    "created_at",
    "updated_at",
  ]);
  if (
    projectId === null ||
    item.project_id !== projectId ||
    (chatId !== undefined && item.chat_id !== chatId) ||
    !["snapshot", "latest"].includes(item.mode as string) ||
    (item.report_id !== null && typeof item.report_id !== "string") ||
    (item.mode === "snapshot" && item.report_id === null)
  )
    throw invalid();
  return item as unknown as ReportPin;
}
function source(value: unknown, projectId: string | null): Source {
  const item = fields(value, [
    "id",
    "title",
    "url",
    "source_name",
    "access_scope",
    "provenance_status",
    "created_at",
  ]);
  if (item.project_id !== projectId || typeof item.pinned !== "boolean")
    throw invalid();
  if (item.kind !== undefined && typeof item.kind !== "string") throw invalid();
  if (
    item.is_material_evidence !== undefined &&
    typeof item.is_material_evidence !== "boolean"
  )
    throw invalid();
  strings(item.chat_ids);
  strings(item.report_ids);
  return item as unknown as Source;
}
function detail(
  value: unknown,
  projectId: string | null | undefined,
  chatId: string,
): ChatDetail {
  const data = record(value);
  const parsedChat = chat(data.chat, projectId);
  if (parsedChat.id !== chatId) throw invalid();
  const messages = list(data.messages, (value) => {
    const item = fields(value, [
      "id",
      "chat_id",
      "role",
      "content",
      "created_at",
    ]);
    if (
      item.chat_id !== chatId ||
      !["user", "assistant"].includes(item.role as string)
    )
      throw invalid();
    if (item.report_id !== null && typeof item.report_id !== "string")
      throw invalid();
    if (item.intake !== undefined) {
      const intake = fields(item.intake, ["status", "reason_code"]);
      if (
        !["accepted", "clarification_required", "refused"].includes(
          intake.status as string,
        )
      )
        throw invalid();
      strings(intake.questions);
    }
    return item as unknown as Message;
  });
  const reports = list(data.reports, (item) =>
    report(item, parsedChat.project_id),
  );
  if (reports.some((item) => item.chat_id !== chatId)) throw invalid();
  const sources = list(data.sources, (item) =>
    source(item, parsedChat.project_id),
  );
  const report_tracking =
    data.report_tracking === undefined || data.report_tracking === null
      ? data.report_tracking
      : reportPin(data.report_tracking, parsedChat.project_id, chatId);
  if (report_tracking && report_tracking.mode !== "latest") throw invalid();
  return {
    chat: parsedChat,
    messages,
    reports,
    sources,
    ...(report_tracking !== undefined ? { report_tracking } : {}),
  };
}

export class ResearchRequestError extends Error {
  constructor(readonly setupRequired: boolean) {
    super(
      setupRequired
        ? "The workspace needs a verified model connection before research can run. Your prompt has not been submitted."
        : "The workspace model could not complete this research request. No report was saved; your draft is still here.",
    );
  }
}

export class RemovedItemsChangedError extends Error {
  constructor() {
    super(
      "The workspace removed items changed. Review the updated list and confirm again before deleting.",
    );
  }
}

export class GeneralChatsChangedError extends Error {
  constructor(detail: unknown) {
    super(
      detail ===
        "A general chat is still researching. Wait for it to finish, then try again."
        ? detail
        : "General chats changed. Review the updated list and try again.",
    );
  }
}

async function request(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    signal?: AbortSignal;
    timeout?: number;
    csrfToken?: string;
  } = {},
): Promise<unknown> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  options.signal?.addEventListener("abort", abort, { once: true });
  if (options.signal?.aborted) controller.abort();
  const timer = window.setTimeout(abort, options.timeout ?? 15000);
  try {
    const response = await fetch(path, {
      method: options.method ?? "GET",
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.csrfToken ? { "X-CSRF-Token": options.csrfToken } : {}),
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    });
    if (!response.ok) {
      if (
        response.status === 409 &&
        path === "/api/removed" &&
        options.method === "DELETE"
      )
        throw new RemovedItemsChangedError();
      if (response.status === 409 || response.status === 502) {
        const body = await response.json().catch(() => null);
        const detail = body?.detail;
        if (
          response.status === 409 &&
          path === "/api/general-chats" &&
          options.method === "DELETE"
        )
          throw new GeneralChatsChangedError(detail);
        if (
          response.status === 409 &&
          detail?.code === "model_setup_required" &&
          detail?.setup_required === true
        )
          throw new ResearchRequestError(true);
        if (
          response.status === 409 &&
          detail?.code === "model_connection_busy" &&
          detail?.setup_required === false
        )
          throw new Error(
            "The workspace model connection is busy. Wait for the current account check or research to finish, then send your request again. This request was not submitted to the model.",
          );
        if (
          response.status === 502 &&
          detail?.code === "model_execution_failed" &&
          detail?.setup_required === false
        )
          throw new ResearchRequestError(false);
        if (
          response.status === 409 &&
          /\/(report-pins|tracked-reports)\//.test(path)
        )
          throw new Error(
            "The workspace pin changed or this revision is already saved. Reload the chat or project contents before trying again.",
          );
      }
      throw new Error(
        `The workspace request failed (${response.status}). Please reload and try again.`,
      );
    }
    return response.status === 204 ? null : await response.json();
  } catch (error) {
    if (options.signal?.aborted) throw error;
    if (
      error instanceof GeneralChatsChangedError ||
      (error instanceof Error && error.message.startsWith("The workspace"))
    )
      throw error;
    throw new Error(
      "The workspace could not be reached. Check that the local application is running.",
    );
  } finally {
    window.clearTimeout(timer);
    options.signal?.removeEventListener("abort", abort);
  }
}

const base = (projectId: string) =>
  `/api/projects/${encodeURIComponent(projectId)}`;
const conversation = (projectId: string, chatId: string) =>
  `${base(projectId)}/chats/${encodeURIComponent(chatId)}`;
function searchResults(value: unknown, query: string): WorkspaceSearchResults {
  const result = record(value);
  if (result.query !== query || typeof result.has_more !== "boolean")
    throw invalid();
  function snippet(value: unknown): string {
    if (typeof value !== "string" || value.length > 600) throw invalid();
    return value;
  }
  function identifier(value: unknown): string | null {
    if (
      value !== null &&
      (typeof value !== "string" || !/^[a-zA-Z0-9-]{1,64}$/.test(value))
    )
      throw invalid();
    return value as string | null;
  }
  const projects = list(result.projects, (value): ProjectSearchMatch => {
    const item = record(value);
    if (!["name", "description"].includes(item.match_field as string))
      throw invalid();
    return {
      project: project(item.project),
      match_field: item.match_field as ProjectSearchMatch["match_field"],
      snippet: snippet(item.snippet),
    };
  });
  const chats = list(result.chats, (value): ChatSearchMatch => {
    const item = record(value),
      found = chat(item.chat);
    if (
      !["title", "message", "report"].includes(item.match_field as string) ||
      (found.project_id === null
        ? item.project_name !== null
        : typeof item.project_name !== "string")
    )
      throw invalid();
    const message_id = identifier(item.message_id),
      report_id = identifier(item.report_id);
    if (
      (item.match_field === "message" && !message_id) ||
      (item.match_field === "report" && !report_id) ||
      (item.match_field === "title" &&
        (message_id !== null || report_id !== null))
    )
      throw invalid();
    return {
      chat: found,
      project_name: item.project_name as string | null,
      match_field: item.match_field as ChatSearchMatch["match_field"],
      snippet: snippet(item.snippet),
      message_id,
      report_id,
    };
  });
  if (
    projects.length > 20 ||
    chats.length > 20 ||
    new Set(projects.map(({ project }) => project.id)).size !==
      projects.length ||
    new Set(chats.map(({ chat }) => chat.id)).size !== chats.length
  )
    throw invalid();
  return { query, projects, chats, has_more: result.has_more };
}
export const workspaceApi = {
  async search(
    query: string,
    signal?: AbortSignal,
  ): Promise<WorkspaceSearchResults> {
    const normalized = query.trim();
    if (normalized.length > 200) throw invalid();
    if (!normalized)
      return { query: "", projects: [], chats: [], has_more: false };
    return searchResults(
      await request(
        `/api/workspace/search?q=${encodeURIComponent(normalized)}&limit=20`,
        { signal },
      ),
      normalized,
    );
  },
  async projects(signal?: AbortSignal) {
    return list(
      record(await request("/api/projects", { signal })).projects,
      project,
    );
  },
  async createProject(name: string, description: string) {
    return project(
      await request("/api/projects", {
        method: "POST",
        body: { name, description },
      }),
    );
  },
  async renameProject(projectId: string, name: string) {
    return project(
      await request(base(projectId), { method: "PATCH", body: { name } }),
    );
  },
  async removeProject(projectId: string) {
    await request(base(projectId), { method: "DELETE" });
  },
  async restoreProject(projectId: string) {
    return project(
      await request(`${base(projectId)}/restore`, { method: "POST" }),
    );
  },
  async chats(projectId: string, signal?: AbortSignal) {
    return list(
      record(await request(`${base(projectId)}/chats`, { signal })).chats,
      (item) => chat(item, projectId),
    );
  },
  async createChat(projectId: string, title: string) {
    return chat(
      await request(`${base(projectId)}/chats`, {
        method: "POST",
        body: { title },
      }),
      projectId,
    );
  },
  async projectDraft(projectId: string) {
    return chat(
      await request(`${base(projectId)}/draft-chat`, { method: "POST" }),
      projectId,
    );
  },
  async allChats(signal?: AbortSignal) {
    return list(record(await request("/api/chats", { signal })).chats, (item) =>
      chat(item),
    );
  },
  async startChat(title = "Untitled chat", projectId: string | null = null) {
    return chat(
      await request("/api/chats", {
        method: "POST",
        body: { title, project_id: projectId },
      }),
      projectId,
    );
  },
  async chat(chatId: string, signal?: AbortSignal) {
    return detail(
      await request(`/api/chats/${encodeURIComponent(chatId)}`, { signal }),
      undefined,
      chatId,
    );
  },
  async message(
    chatId: string,
    content: string,
    rankingProfileId?: string,
    runId?: string,
    searchReferenceStructures?: boolean,
  ) {
    return detail(
      await request(`/api/chats/${encodeURIComponent(chatId)}/messages`, {
        method: "POST",
        body: {
          content,
          ...(rankingProfileId === undefined
            ? {}
            : { ranking_profile_id: rankingProfileId }),
          ...(runId === undefined ? {} : { run_id: researchRunId(runId) }),
          ...(searchReferenceStructures === undefined
            ? {}
            : { search_reference_structures: searchReferenceStructures }),
        },
        timeout: 300000,
      }),
      undefined,
      chatId,
    );
  },
  async activeResearch(
    signal?: AbortSignal,
  ): Promise<(ResearchStatus & { chat_id: string })[]> {
    const data = record(
      await request("/api/research-runs", { signal, timeout: 5000 }),
    );
    const runs = list(data.runs, (item) => {
      const value = record(item);
      const { chat_id: chatId, ...progress } = value;
      const status = researchStatus(progress);
      if (
        typeof value.chat_id !== "string" ||
        !/^[A-Za-z0-9-]{1,64}$/.test(value.chat_id) ||
        status.status !== "running" ||
        !status.run_id ||
        !status.started_at
      )
        throw invalid();
      return { ...status, chat_id: chatId as string };
    });
    if (
      runs.length > 256 ||
      new Set(runs.map((run) => run.chat_id)).size !== runs.length
    )
      throw invalid();
    return runs;
  },
  async researchStatus(chatId: string, runId: string, signal?: AbortSignal) {
    const requestedRunId = researchRunId(runId);
    const result = researchStatus(
      await request(
        `/api/chats/${encodeURIComponent(chatId)}/research-status?run_id=${encodeURIComponent(requestedRunId)}`,
        { signal, timeout: 5000 },
      ),
    );
    if (result.run_id !== null && result.run_id !== requestedRunId)
      throw invalid();
    return result;
  },
  async moveChat(chatId: string, projectId: string | null) {
    return detail(
      await request(`/api/chats/${encodeURIComponent(chatId)}`, {
        method: "PATCH",
        body: { project_id: projectId },
      }),
      projectId,
      chatId,
    );
  },
  async renameChat(chatId: string, title: string) {
    return detail(
      await request(`/api/chats/${encodeURIComponent(chatId)}`, {
        method: "PATCH",
        body: { title },
      }),
      undefined,
      chatId,
    );
  },
  async removeChat(chatId: string) {
    await request(`/api/chats/${encodeURIComponent(chatId)}`, {
      method: "DELETE",
    });
  },
  async clearGeneralChats(
    snapshot: string[],
    confirmed: boolean,
  ): Promise<number> {
    if (
      confirmed !== true ||
      !Array.isArray(snapshot) ||
      !snapshot.length ||
      new Set(snapshot).size !== snapshot.length ||
      snapshot.some(
        (id) => typeof id !== "string" || !/^[A-Za-z0-9_-]{1,128}$/.test(id),
      )
    )
      throw invalid();
    const reviewedSnapshot = [...snapshot];
    const session = record(await request("/api/session"));
    if (
      typeof session.csrf_token !== "string" ||
      !/^[A-Za-z0-9_-]{20,200}$/.test(session.csrf_token)
    )
      throw invalid();
    const data = record(
      await request("/api/general-chats", {
        method: "DELETE",
        body: { confirm: true, snapshot: reviewedSnapshot },
        csrfToken: session.csrf_token,
      }),
    );
    if (
      Object.keys(data).length !== 1 ||
      data.removed_chats !== reviewedSnapshot.length
    )
      throw invalid();
    return data.removed_chats as number;
  },
  async restoreChat(chatId: string) {
    return detail(
      await request(`/api/chats/${encodeURIComponent(chatId)}/restore`, {
        method: "POST",
      }),
      undefined,
      chatId,
    );
  },
  async removed(signal?: AbortSignal): Promise<RemovedItems> {
    const data = record(await request("/api/removed", { signal }));
    if (data.retention_days !== 30) throw invalid();
    return {
      projects: list(data.projects, (item) => ({
        ...project(item),
        expires_at: removalExpiry(record(item).expires_at),
      })),
      chats: list(data.chats, (item) => ({
        ...chat(item),
        expires_at: removalExpiry(record(item).expires_at),
      })),
      retention_days: 30,
      snapshot: removalSnapshot(data.snapshot),
    };
  },
  async workspacePreferences(signal?: AbortSignal) {
    return workspacePreferences(
      await request("/api/workspace/preferences", { signal }),
    );
  },
  async saveWorkspacePreferences(value: WorkspacePreferences) {
    return workspacePreferences(
      await request("/api/workspace/preferences", {
        method: "PUT",
        body: workspacePreferences(value),
      }),
    );
  },
  async permanentlyDelete(
    kind: "project" | "chat",
    id: string,
    confirmed: boolean,
  ) {
    if (confirmed !== true || !["project", "chat"].includes(kind))
      throw invalid();
    const session = record(await request("/api/session"));
    if (
      typeof session.csrf_token !== "string" ||
      !/^[A-Za-z0-9_-]{20,200}$/.test(session.csrf_token)
    )
      throw invalid();
    await request(
      `/api/removed/${kind === "project" ? "projects" : "chats"}/${encodeURIComponent(id)}`,
      {
        method: "DELETE",
        body: { confirm: true },
        csrfToken: session.csrf_token,
      },
    );
  },
  async permanentlyDeleteAll(snapshot: string, confirmed: boolean) {
    if (confirmed !== true) throw invalid();
    const reviewedSnapshot = removalSnapshot(snapshot);
    const session = record(await request("/api/session"));
    if (
      typeof session.csrf_token !== "string" ||
      !/^[A-Za-z0-9_-]{20,200}$/.test(session.csrf_token)
    )
      throw invalid();
    await request("/api/removed", {
      method: "DELETE",
      body: { confirm: true, snapshot: reviewedSnapshot },
      csrfToken: session.csrf_token,
    });
  },
  async about(signal?: AbortSignal): Promise<About> {
    const data = fields(await request("/api/about", { signal }), [
      "name",
      "version",
      "developer",
      "license",
    ]);
    if (data.github_url !== null) {
      if (typeof data.github_url !== "string") throw invalid();
      const url = new URL(data.github_url);
      if (
        url.protocol !== "https:" ||
        url.hostname !== "github.com" ||
        url.username ||
        url.password
      )
        throw invalid();
    }
    return data as unknown as About;
  },
  async detail(projectId: string, chatId: string, signal?: AbortSignal) {
    return detail(
      await request(conversation(projectId, chatId), { signal }),
      projectId,
      chatId,
    );
  },
  async send(projectId: string, chatId: string, content: string) {
    return detail(
      await request(`${conversation(projectId, chatId)}/messages`, {
        method: "POST",
        body: { content },
        timeout: 300000,
      }),
      projectId,
      chatId,
    );
  },
  async contents(
    projectId: string,
    signal?: AbortSignal,
  ): Promise<ProjectContents> {
    const data = record(
      await request(`${base(projectId)}/contents`, { signal }),
    );
    return {
      chats: list(data.chats, (item) => chat(item, projectId)),
      reports: list(data.reports, (item) => report(item, projectId)),
      sources: list(data.sources, (item) => source(item, projectId)),
    };
  },
  async pin(projectId: string, kind: PinKind, id: string, pinned: boolean) {
    await request(
      pinned
        ? `${base(projectId)}/pins/${kind}/${encodeURIComponent(id)}`
        : `${base(projectId)}/pins`,
      pinned
        ? { method: "DELETE" }
        : { method: "POST", body: { kind, target_id: id } },
    );
  },
  async trackReport(projectId: string, chatId: string, tracking: boolean) {
    const value = await request(
      `${base(projectId)}/tracked-reports/${encodeURIComponent(chatId)}`,
      tracking ? { method: "PUT", body: {} } : { method: "DELETE" },
    );
    if (!tracking) return null;
    const pin = reportPin(value, projectId, chatId);
    if (pin.mode !== "latest") throw invalid();
    return pin;
  },
  async updateReportSnapshot(
    projectId: string,
    pin: ReportPin,
    reportId: string,
  ) {
    if (
      pin.project_id !== projectId ||
      pin.mode !== "snapshot" ||
      !pin.report_id
    )
      throw invalid();
    const value = await request(
      `${base(projectId)}/report-pins/${encodeURIComponent(pin.id)}`,
      {
        method: "PUT",
        body: { expected_report_id: pin.report_id, report_id: reportId },
      },
    );
    const updated = reportPin(value, projectId, pin.chat_id);
    if (
      updated.id !== pin.id ||
      updated.mode !== "snapshot" ||
      updated.report_id !== reportId
    )
      throw invalid();
    return updated;
  },
  async settings(signal?: AbortSignal) {
    return settings(await request("/api/settings", { signal }));
  },
  async saveSettings(value: SearchSettings) {
    return settings(
      await request("/api/settings", { method: "PUT", body: value }),
    );
  },
};

function settings(value: unknown): SearchSettings {
  const data = record(value),
    weights = record(data.ranking),
    presentation = record(data.presentation);
  const exactKeys = (item: RecordValue, expected: string[]) =>
    Object.keys(item).length === expected.length &&
    expected.every((key) => Object.hasOwn(item, key));
  if (
    !exactKeys(data, ["ranking", "presentation"]) ||
    !exactKeys(weights, Object.keys(defaultSettings.ranking))
  )
    throw invalid();
  let sum = 0;
  for (const key of Object.keys(defaultSettings.ranking)) {
    const weight = weights[key];
    if (
      typeof weight !== "number" ||
      !Number.isFinite(weight) ||
      weight < 0 ||
      weight > 1
    )
      throw invalid();
    sum += weight;
  }
  if (Math.abs(sum - 1) > 0.000001) throw invalid();
  validatePresentation(presentation);
  return data as unknown as SearchSettings;
}

export function validatePresentation(value: unknown): ReportPresentation {
  const presentation = record(value);
  const keys = [
    "style",
    "outputs",
    "format",
    "terminology",
    "verbosity",
    ...(presentation.layout === undefined ? [] : ["layout"]),
  ];
  if (
    Object.keys(presentation).length !== keys.length ||
    !keys.every((key) => Object.hasOwn(presentation, key)) ||
    !["pi", "audit"].includes(presentation.style as string) ||
    !["text", "json", "pdf", "docx"].includes(presentation.format as string) ||
    !["general", "research", "specialist"].includes(
      presentation.terminology as string,
    ) ||
    !validOutputs(presentation.outputs) ||
    !["concise", "standard", "detailed"].includes(
      presentation.verbosity as string,
    )
  )
    throw invalid();
  if (presentation.layout !== undefined) {
    const layout = record(presentation.layout);
    if (
      Object.keys(layout).length !== Object.keys(defaultReportLayout).length ||
      !["letter", "a4"].includes(layout.page_size as string) ||
      !["sans", "serif"].includes(layout.font_family as string) ||
      ![10, 11, 12].includes(layout.font_size as number) ||
      !["compact", "comfortable"].includes(layout.line_spacing as string) ||
      !["sage", "teal", "slate"].includes(layout.accent as string) ||
      !["striped", "grid", "minimal"].includes(layout.table_style as string) ||
      typeof layout.page_numbers !== "boolean" ||
      ![72, 88, 100].includes(layout.text_width as number) ||
      ![2, 4].includes(layout.json_indent as number)
    )
      throw invalid();
  }
  return presentation as unknown as ReportPresentation;
}

function validOutputs(value: unknown): value is ReportView[] {
  return (
    Array.isArray(value) &&
    value.length >= 1 &&
    value.length <= 2 &&
    new Set(value).size === value.length &&
    value.every((view) => view === "pi" || view === "audit")
  );
}
export function toggleReportOutput(
  outputs: ReportView[],
  view: ReportView,
): ReportView[] {
  if (outputs.includes(view))
    return outputs.length > 1
      ? outputs.filter((item) => item !== view)
      : [...outputs];
  return (["pi", "audit"] as ReportView[]).filter(
    (item) => item === view || outputs.includes(item),
  );
}
export function reportExportUrl(
  chatId: string,
  reportId: string,
  format: ExportFormat,
  outputs: ReportExportSection[],
): string {
  const sections: ReportExportSection[] = ["pi", "audit", "sources"];
  if (
    !Array.isArray(outputs) ||
    outputs.length < 1 ||
    outputs.length > 3 ||
    new Set(outputs).size !== outputs.length ||
    !outputs.every((view) => sections.includes(view)) ||
    !["text", "json", "pdf", "docx"].includes(format)
  )
    throw invalid();
  const views =
    outputs.length === 3
      ? "all"
      : outputs.length === 2 && !outputs.includes("sources")
        ? "both"
        : sections.filter((view) => outputs.includes(view)).join(",");
  return `/api/chats/${encodeURIComponent(chatId)}/reports/${encodeURIComponent(reportId)}/export?format=${format}&views=${encodeURIComponent(views)}`;
}

export function publicLink(source: Source): string | null {
  if (source.access_scope !== "public") return null;
  try {
    const url = new URL(source.url);
    const host = url.hostname.toLowerCase();
    const localHost =
      host === "localhost" ||
      host.endsWith(".localhost") ||
      host.endsWith(".local") ||
      host.endsWith(".internal") ||
      /^(127\.|10\.|0\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.)/.test(
        host,
      ) ||
      host === "[::]" ||
      host === "[::1]" ||
      /^\[(fc|fd|fe8|fe9|fea|feb)/.test(host);
    return ["https:", "http:"].includes(url.protocol) &&
      !url.username &&
      !url.password &&
      !localHost
      ? url.href
      : null;
  } catch {
    return null;
  }
}

export function errorMessage(error: unknown): string {
  return error instanceof Error && error.message.startsWith("The workspace")
    ? error.message
    : "The workspace request could not be completed. Please reload and try again.";
}
