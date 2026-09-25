export type Provider =
  | "none"
  | "ollama"
  | "openai"
  | "anthropic"
  | "kimi"
  | "bedrock"
  | "chatgpt"
  | "gemini"
  | "deepseek"
  | "xai"
  | "openrouter";
export type SecretName =
  | "materials_project"
  | "openai"
  | "anthropic"
  | "kimi"
  | "gemini"
  | "deepseek"
  | "xai"
  | "openrouter";
export type SecretState = "missing" | "session" | "encrypted" | "locked";
export interface ConnectionProfile {
  provider: Provider;
  model: string;
  ollama_url: string;
  aws_profile: string;
  aws_region: string;
  allow_paid_inference: boolean;
}
export interface ConnectionStatus {
  configured: boolean;
  profile: ConnectionProfile;
  credentials: Record<SecretName, SecretState>;
  vault: {
    available: boolean;
    locked: boolean;
    exists: boolean;
    can_create: boolean;
    key_source: "environment" | "file" | "passphrase" | "unavailable";
  };
  using_local_defaults: boolean;
  warnings: string[];
  accounts: ModelAccount[];
  active_account_id: string | null;
  source_connections?: { materials_project: SourceConnectionReadiness };
}
export interface SourceConnectionReadiness {
  status:
    | "not_configured"
    | "locked"
    | "verification_required"
    | "ready"
    | "error";
  selectable: boolean;
  requires_credentials: true;
  verified_at: string | null;
  message: string;
}
export interface ModelAccount {
  id: string;
  label: string;
  profile: ConnectionProfile;
  credential_state: SecretState | "not_required";
}
export interface AccountUpdate {
  label: string;
  profile: ConnectionProfile;
  secret_storage: "session" | "encrypted";
  api_key?: string;
}
export interface ModelCatalog {
  provider: Provider;
  models: { id: string; label: string }[];
  message: string;
  inference_tested: false;
}
export interface AwsProfiles {
  profiles: string[];
  regions: string[];
  setup: { commands: string[]; documentation_url: string; message: string };
}
export interface AgentRuntime {
  engine: "goose" | "direct";
  available: boolean;
  version: string;
  tools: string[];
  message: string;
}
export interface LoginFlow {
  flow_id: string;
  status:
    | "pending"
    | "complete"
    | "expired"
    | "cancelled"
    | "error"
    | "consumed";
  method?: "browser" | "device";
  verification_url?: string | null;
  user_code?: string | null;
  message?: string;
}
export interface UsageWindow {
  used_percent: number | null;
  remaining_percent: number | null;
  window_minutes: number | null;
  resets_at: number | null;
}
export interface AccountUsage {
  account_id: string | null;
  provider: Provider;
  rate_limits:
    | null
    | {
        id: string;
        label: string;
        primary: UsageWindow | null;
        secondary: UsageWindow | null;
      }[];
  token_activity: Record<string, unknown> | null;
  last_run: null | {
    provider: Provider;
    model: string;
    recorded_at: string;
    usage: Record<string, unknown> | null;
    status: string;
  };
  notices: string[];
  inference_tested: false;
}
export interface ResearchPlan {
  version: string;
  steps: string[];
  ranking_profile?: { name?: string } | null;
  source_preferences?: {
    search_public_references?: boolean;
    materials_project_mode?: string;
  };
  [key: string]: unknown;
}
export type TestTarget = "materials_project" | "model" | "aws";
export interface ConnectionTest {
  target: TestTarget;
  status: "ok" | "error" | "not_configured";
  message: string;
  billable: false;
  inference_tested: false;
}
export interface ConnectionUpdate {
  profile: ConnectionProfile;
  secret_storage: "session" | "encrypted";
  secrets?: Partial<Record<SecretName, string>>;
  forget_secrets?: SecretName[];
}
export type VaultAction =
  | { action: "create" | "unlock"; passphrase: string }
  | { action: "lock" }
  | { action: "reset"; confirm: true };
export const providerLabels: Record<Provider, string> = {
  none: "Local defaults · no language model",
  ollama: "Ollama · local model",
  openai: "OpenAI API (ChatGPT models)",
  anthropic: "Anthropic (Claude) API",
  kimi: "Kimi API",
  bedrock: "Amazon Bedrock",
  chatgpt: "ChatGPT · account sign-in",
  gemini: "Google Gemini API",
  deepseek: "DeepSeek API",
  xai: "xAI (Grok) API",
  openrouter: "OpenRouter API",
};
export const providerAccountLabels: Record<Provider, string> = {
  none: "Choose a provider",
  ollama: "Ollama",
  openai: "OpenAI",
  anthropic: "Anthropic",
  kimi: "Kimi",
  bedrock: "Amazon Bedrock",
  chatgpt: "ChatGPT",
  gemini: "Google Gemini",
  deepseek: "DeepSeek",
  xai: "xAI",
  openrouter: "OpenRouter",
};
export const secretLabels: Record<SecretName, string> = {
  materials_project: "Materials Project",
  openai: "OpenAI",
  anthropic: "Anthropic",
  kimi: "Kimi",
  gemini: "Google Gemini",
  deepseek: "DeepSeek",
  xai: "xAI",
  openrouter: "OpenRouter",
};
export const connectableProviders = [
  "chatgpt",
  "openai",
  "anthropic",
  "gemini",
  "kimi",
  "deepseek",
  "xai",
  "openrouter",
  "bedrock",
] as const;
export const apiKeyProviders = [
  "openai",
  "anthropic",
  "kimi",
  "gemini",
  "deepseek",
  "xai",
  "openrouter",
] as const;
export function isApiKeyProvider(
  provider: Provider,
): provider is (typeof apiKeyProviders)[number] {
  return (apiKeyProviders as readonly string[]).includes(provider);
}
export function isCloudProvider(provider: Provider) {
  return provider !== "none" && provider !== "ollama";
}

function invalid() {
  return new Error(
    "Connection settings returned an unsupported response. Reload connection settings.",
  );
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw invalid();
  return value as Record<string, unknown>;
}
function exact(value: Record<string, unknown>, names: string[]) {
  if (
    Object.keys(value).length !== names.length ||
    !names.every((name) => Object.hasOwn(value, name))
  )
    throw invalid();
}
function shortText(value: unknown, maximum = 2000): value is string {
  return typeof value === "string" && value.length <= maximum;
}
export function safeSignInUrl(value: unknown): value is string {
  return (
    value === "https://auth.openai.com/codex/device" ||
    safeBrowserSignInUrl(value)
  );
}
function safeBrowserSignInUrl(value: unknown): value is string {
  // Match the reviewed native Goose PKCE flow; optional upstream parameters
  // are allowed, but duplicate decoded names and alternate callbacks are not.
  if (
    !shortText(value, 8192) ||
    /[^\x21-\x7e]/.test(value) ||
    !value.startsWith("https://auth.openai.com/oauth/authorize?")
  )
    return false;
  try {
    const url = new URL(value);
    if (
      url.origin !== "https://auth.openai.com" ||
      url.pathname !== "/oauth/authorize" ||
      url.hash ||
      value.includes("#")
    )
      return false;
    const fields = url.search.slice(1).split("&");
    if (fields.some((field) => !field.includes("="))) return false;
    const params = url.searchParams;
    if (new Set(params.keys()).size !== [...params].length) return false;
    const expected = {
      client_id: "app_EMoamEEZ73f0CkXaXp7hrann",
      redirect_uri: "http://localhost:1455/auth/callback",
      response_type: "code",
      code_challenge_method: "S256",
    };
    if (
      Object.entries(expected).some(
        ([key, expectedValue]) => params.get(key) !== expectedValue,
      )
    )
      return false;
    return ["state", "code_challenge"].every((key) =>
      /^[A-Za-z0-9_-]{20,256}$/.test(params.get(key) ?? ""),
    );
  } catch {
    return false;
  }
}
function parseLogin(value: unknown): LoginFlow {
  const flow = object(value);
  if (
    Object.keys(flow).some(
      (key) =>
        ![
          "flow_id",
          "status",
          "method",
          "verification_url",
          "user_code",
          "message",
        ].includes(key),
    ) ||
    !shortText(flow.flow_id, 128) ||
    !flow.flow_id ||
    ![
      "pending",
      "complete",
      "expired",
      "cancelled",
      "error",
      "consumed",
    ].includes(flow.status as string) ||
    (flow.method !== undefined &&
      !["browser", "device"].includes(flow.method as string)) ||
    (flow.message !== undefined && !shortText(flow.message))
  )
    throw invalid();
  if (flow.method === "browser") {
    if (
      flow.user_code !== null ||
      (flow.status === "pending" &&
        !safeBrowserSignInUrl(flow.verification_url)) ||
      (flow.verification_url != null &&
        !safeBrowserSignInUrl(flow.verification_url))
    )
      throw invalid();
  } else if (
    (flow.verification_url !== undefined &&
      flow.verification_url !== "https://auth.openai.com/codex/device") ||
    (flow.user_code !== undefined &&
      (!shortText(flow.user_code, 64) ||
        !/^[A-Za-z0-9 -]+$/.test(flow.user_code))) ||
    (flow.status === "pending" && (!flow.verification_url || !flow.user_code))
  )
    throw invalid();
  return flow as unknown as LoginFlow;
}
function telemetry(value: unknown): Record<string, unknown> | null {
  if (value === null) return null;
  const result = object(value);
  if (JSON.stringify(result).length > 16384) throw invalid();
  function check(item: unknown, depth: number) {
    if (depth > 4) throw invalid();
    if (
      item === null ||
      typeof item === "boolean" ||
      (typeof item === "number" && Number.isFinite(item)) ||
      shortText(item, 2000)
    )
      return;
    if (Array.isArray(item)) {
      if (item.length > 32) throw invalid();
      item.forEach((child) => check(child, depth + 1));
      return;
    }
    for (const [key, child] of Object.entries(object(item))) {
      if (
        [
          "access_token",
          "refresh_token",
          "id_token",
          "api_key",
          "password",
          "authorization",
          "cookie",
          "secret",
          "credentials",
        ].includes(key.toLowerCase())
      )
        throw invalid();
      check(child, depth + 1);
    }
  }
  check(result, 0);
  return result;
}
function parseUsageWindow(value: unknown): UsageWindow | null {
  if (value === null) return null;
  const item = object(value);
  exact(item, [
    "used_percent",
    "remaining_percent",
    "window_minutes",
    "resets_at",
  ]);
  for (const field of [
    "used_percent",
    "remaining_percent",
    "window_minutes",
    "resets_at",
  ]) {
    const number = item[field];
    if (
      number !== null &&
      (typeof number !== "number" ||
        !Number.isFinite(number) ||
        number < 0 ||
        (field.endsWith("percent") && number > 100))
    )
      throw invalid();
  }
  return item as unknown as UsageWindow;
}
function parseProfile(value: unknown): ConnectionProfile {
  const profile = object(value);
  exact(profile, [
    "provider",
    "model",
    "ollama_url",
    "aws_profile",
    "aws_region",
    "allow_paid_inference",
  ]);
  if (
    typeof profile.provider !== "string" ||
    !Object.hasOwn(providerLabels, profile.provider) ||
    !["model", "ollama_url", "aws_profile", "aws_region"].every(
      (field) => typeof profile[field] === "string",
    ) ||
    typeof profile.allow_paid_inference !== "boolean"
  )
    throw invalid();
  return profile as unknown as ConnectionProfile;
}
function parseStatus(value: unknown): ConnectionStatus {
  const item = object(value),
    credentials = object(item.credentials),
    vault = object(item.vault);
  parseProfile(item.profile);
  exact(item, [
    "configured",
    "profile",
    "credentials",
    "vault",
    "using_local_defaults",
    "warnings",
    "accounts",
    "active_account_id",
    ...(item.source_connections === undefined ? [] : ["source_connections"]),
  ]);
  if (item.source_connections !== undefined) {
    const sources = object(item.source_connections);
    exact(sources, ["materials_project"]);
    const readiness = object(sources.materials_project);
    exact(readiness, [
      "status",
      "selectable",
      "requires_credentials",
      "verified_at",
      "message",
    ]);
    if (
      ![
        "not_configured",
        "locked",
        "verification_required",
        "ready",
        "error",
      ].includes(readiness.status as string) ||
      typeof readiness.selectable !== "boolean" ||
      readiness.selectable !== (readiness.status === "ready") ||
      readiness.requires_credentials !== true ||
      !shortText(readiness.message) ||
      (readiness.verified_at !== null &&
        (!shortText(readiness.verified_at, 80) ||
          Number.isNaN(Date.parse(readiness.verified_at))))
    )
      throw invalid();
  }
  exact(credentials, Object.keys(secretLabels));
  exact(vault, ["available", "locked", "exists", "can_create", "key_source"]);
  if (
    typeof item.configured !== "boolean" ||
    typeof item.using_local_defaults !== "boolean" ||
    !Object.values(credentials).every((state) =>
      ["missing", "session", "encrypted", "locked"].includes(state as string),
    ) ||
    !["available", "locked", "exists", "can_create"].every(
      (field) => typeof vault[field] === "boolean",
    ) ||
    !["environment", "file", "passphrase", "unavailable"].includes(
      vault.key_source as string,
    ) ||
    !Array.isArray(item.warnings) ||
    !item.warnings.every((warning) => typeof warning === "string") ||
    !Array.isArray(item.accounts) ||
    (item.active_account_id !== null &&
      typeof item.active_account_id !== "string")
  )
    throw invalid();
  const accounts = item.accounts.map((value) => {
    const account = object(value);
    exact(account, ["id", "label", "profile", "credential_state"]);
    if (
      typeof account.id !== "string" ||
      typeof account.label !== "string" ||
      !["missing", "session", "encrypted", "locked", "not_required"].includes(
        account.credential_state as string,
      )
    )
      throw invalid();
    parseProfile(account.profile);
    return account as unknown as ModelAccount;
  });
  if (
    new Set(accounts.map((account) => account.id)).size !== accounts.length ||
    (item.active_account_id !== null &&
      !accounts.some((account) => account.id === item.active_account_id))
  )
    throw invalid();
  return item as unknown as ConnectionStatus;
}

async function fetchJson(
  path: string,
  options: RequestInit,
  timeoutMs = 30000,
): Promise<unknown> {
  const controller = new AbortController();
  const parent = options.signal;
  const abort = () => controller.abort();
  parent?.addEventListener("abort", abort, { once: true });
  if (parent?.aborted) controller.abort();
  const timeout = window.setTimeout(abort, timeoutMs);
  try {
    const response = await fetch(path, {
      ...options,
      signal: controller.signal,
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    });
    if (!response.ok) {
      // The connection API uses 409 for a competing account operation. Never
      // display response text or automatically repeat the interrupted action.
      if (
        response.status === 409 &&
        (path === "/api/connections" || path.startsWith("/api/connections/"))
      )
        throw new Error(
          "Connection is busy with another account check or research request. Wait for it to finish, then try this action again.",
        );
      if (response.status === 503) {
        // Match only reviewed codes. Provider/server text may contain credentials
        // and must never be reflected into the connection form.
        const body: unknown = await response.json().catch(() => null);
        const detail =
          body && typeof body === "object" && "detail" in body
            ? body.detail
            : null;
        const code =
          detail && typeof detail === "object" && "code" in detail
            ? detail.code
            : null;
        if (code === "chatgpt_storage_unavailable")
          throw new Error(
            "Connection setup needs attention. This backend is missing the protected temporary storage required for ChatGPT sign-in. Start Labcat with the supplied Docker launcher, or ask your site administrator to repair the deployment.",
          );
        if (code === "chatgpt_helper_unavailable")
          throw new Error(
            "Connection setup needs attention. The ChatGPT sign-in helper is unavailable in this backend. Update or rebuild the Labcat Docker image, then restart the application. Your site administrator can check the installation.",
          );
        if (code === "chatgpt_callback_unavailable")
          throw new Error(
            "Connection setup needs attention. ChatGPT browser sign-in requires local port 1455. Free that port, then restart the supplied launcher with LABCAT_OAUTH_CALLBACK_PORT=1455, or ask your site administrator to do this. Other providers remain usable.",
          );
      }
      const hint =
        response.status === 401 || response.status === 403
          ? "Reload connection settings before trying again."
          : response.status === 422 || response.status === 400
            ? "Check the entered settings or vault passphrase and try again."
            : "Check the local application and reload connection settings.";
      throw new Error(
        `Connection request was not completed (${response.status}). ${hint}`,
      );
    }
    return await response.json();
  } catch (error) {
    if (parent?.aborted) throw error;
    if (error instanceof Error && error.message.startsWith("Connection "))
      throw error;
    throw new Error(
      "Connection settings could not be reached. Reload before retrying an interrupted change.",
    );
  } finally {
    window.clearTimeout(timeout);
    parent?.removeEventListener("abort", abort);
  }
}

async function mutate(
  path: string,
  body: unknown,
  method = "POST",
  signal?: AbortSignal,
): Promise<unknown> {
  // The token is held only for this request; the session cookie is HttpOnly.
  const session = object(
    await fetchJson("/api/session", {
      signal,
      headers: { Accept: "application/json" },
    }),
  );
  if (
    typeof session.csrf_token !== "string" ||
    session.csrf_token.length < 16 ||
    session.csrf_token.length > 512
  )
    throw invalid();
  return fetchJson(path, {
    method,
    signal,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-CSRF-Token": session.csrf_token,
    },
    body: JSON.stringify(body),
  });
}

export const connectionsApi = {
  async agent(signal?: AbortSignal): Promise<AgentRuntime> {
    const value = object(
      await fetchJson("/api/connections/agent", {
        signal,
        headers: { Accept: "application/json" },
      }),
    );
    exact(value, ["engine", "available", "version", "tools", "message"]);
    if (
      !["goose", "direct"].includes(value.engine as string) ||
      typeof value.available !== "boolean" ||
      !shortText(value.version, 80) ||
      !shortText(value.message) ||
      !Array.isArray(value.tools) ||
      value.tools.length > 8 ||
      !value.tools.every((tool) => shortText(tool, 80))
    )
      throw invalid();
    return value as unknown as AgentRuntime;
  },
  async usage(): Promise<AccountUsage> {
    const value = object(await mutate("/api/connections/usage", {}));
    exact(value, [
      "account_id",
      "provider",
      "rate_limits",
      "token_activity",
      "last_run",
      "notices",
      "inference_tested",
    ]);
    if (
      (value.account_id !== null && !shortText(value.account_id, 128)) ||
      typeof value.provider !== "string" ||
      !Object.hasOwn(providerLabels, value.provider) ||
      value.inference_tested !== false ||
      !Array.isArray(value.notices) ||
      value.notices.length > 20 ||
      !value.notices.every((note) => shortText(note))
    )
      throw invalid();
    if (value.rate_limits !== null) {
      if (!Array.isArray(value.rate_limits) || value.rate_limits.length > 32)
        throw invalid();
      for (const raw of value.rate_limits) {
        const rate = object(raw);
        exact(rate, ["id", "label", "primary", "secondary"]);
        if (!shortText(rate.id, 128) || !shortText(rate.label, 200))
          throw invalid();
        parseUsageWindow(rate.primary);
        parseUsageWindow(rate.secondary);
      }
    }
    telemetry(value.token_activity);
    if (value.last_run !== null) {
      const run = object(value.last_run);
      exact(run, ["provider", "model", "recorded_at", "usage", "status"]);
      if (
        typeof run.provider !== "string" ||
        !Object.hasOwn(providerLabels, run.provider) ||
        !shortText(run.model, 200) ||
        !shortText(run.recorded_at, 80) ||
        !shortText(run.status, 80)
      )
        throw invalid();
      telemetry(run.usage);
    }
    return value as unknown as AccountUsage;
  },
  async startLogin(id: string, secret_storage: "session" | "encrypted") {
    return parseLogin(
      await mutate(
        `/api/connections/accounts/${encodeURIComponent(id)}/login`,
        { secret_storage },
      ),
    );
  },
  async pollLogin(id: string, flowId: string) {
    return parseLogin(
      await mutate(
        `/api/connections/accounts/${encodeURIComponent(id)}/login/${encodeURIComponent(flowId)}/poll`,
        {},
      ),
    );
  },
  async cancelLogin(id: string, flowId: string) {
    return parseLogin(
      await mutate(
        `/api/connections/accounts/${encodeURIComponent(id)}/login/${encodeURIComponent(flowId)}/cancel`,
        {},
      ),
    );
  },
  async logout(id: string) {
    return parseStatus(
      await mutate(
        `/api/connections/accounts/${encodeURIComponent(id)}/logout`,
        {},
      ),
    );
  },
  async researchPlan(signal?: AbortSignal): Promise<ResearchPlan> {
    const value = object(
      await fetchJson("/api/research-plan", {
        signal,
        headers: { Accept: "application/json" },
      }),
    );
    if (
      !shortText(value.version, 128) ||
      !Array.isArray(value.steps) ||
      value.steps.length > 12 ||
      !value.steps.every((step) => shortText(step, 500)) ||
      JSON.stringify(value).length > 131072
    )
      throw invalid();
    return value as unknown as ResearchPlan;
  },
  async status(signal?: AbortSignal) {
    return parseStatus(
      await fetchJson("/api/connections", {
        signal,
        headers: { Accept: "application/json" },
      }),
    );
  },
  async save(update: ConnectionUpdate) {
    // Blank inputs never overwrite a stored key. Forgetting is a separate action.
    const secrets = Object.fromEntries(
      Object.entries(update.secrets ?? {}).filter(
        ([, value]) => typeof value === "string" && value.length > 0,
      ),
    );
    return parseStatus(
      await mutate(
        "/api/connections",
        {
          profile: update.profile,
          secret_storage: update.secret_storage,
          ...(Object.keys(secrets).length ? { secrets } : {}),
          ...(update.forget_secrets?.length
            ? { forget_secrets: update.forget_secrets }
            : {}),
        },
        "PUT",
      ),
    );
  },
  async localDefaults(persist: boolean) {
    return parseStatus(
      await mutate("/api/connections/local-defaults", { persist }),
    );
  },
  async saveMaterialsProject(
    update:
      | { secret_storage: "session" | "encrypted"; api_key?: string }
      | { forget: true },
  ) {
    return parseStatus(
      await mutate("/api/connections/sources/materials_project", update, "PUT"),
    );
  },
  async saveAccount(update: AccountUpdate, id?: string) {
    const { api_key, ...preferences } = update;
    return parseStatus(
      await mutate(
        id
          ? `/api/connections/accounts/${encodeURIComponent(id)}`
          : "/api/connections/accounts",
        { ...preferences, ...(api_key ? { api_key } : {}) },
        id ? "PUT" : "POST",
      ),
    );
  },
  async selectAccount(id: string) {
    return parseStatus(
      await mutate(
        `/api/connections/accounts/${encodeURIComponent(id)}/select`,
        {},
      ),
    );
  },
  async models(signal?: AbortSignal): Promise<ModelCatalog> {
    const value = object(
      await mutate("/api/connections/models", {}, "POST", signal),
    );
    exact(value, ["provider", "models", "message", "inference_tested"]);
    if (
      typeof value.provider !== "string" ||
      !Object.hasOwn(providerLabels, value.provider) ||
      !Array.isArray(value.models) ||
      typeof value.message !== "string" ||
      value.inference_tested !== false
    )
      throw invalid();
    for (const raw of value.models) {
      const model = object(raw);
      exact(model, ["id", "label"]);
      if (typeof model.id !== "string" || typeof model.label !== "string")
        throw invalid();
    }
    return value as unknown as ModelCatalog;
  },
  async awsProfiles(signal?: AbortSignal): Promise<AwsProfiles> {
    const value = object(
      await fetchJson("/api/connections/aws-profiles", {
        signal,
        headers: { Accept: "application/json" },
      }),
    );
    exact(value, ["profiles", "regions", "setup"]);
    const setup = object(value.setup);
    exact(setup, ["commands", "documentation_url", "message"]);
    for (const list of [value.profiles, value.regions, setup.commands])
      if (
        !Array.isArray(list) ||
        !list.every((item) => typeof item === "string")
      )
        throw invalid();
    if (
      typeof setup.documentation_url !== "string" ||
      typeof setup.message !== "string"
    )
      throw invalid();
    const url = new URL(setup.documentation_url);
    if (
      url.protocol !== "https:" ||
      url.hostname !== "docs.aws.amazon.com" ||
      url.username ||
      url.password
    )
      throw invalid();
    return value as unknown as AwsProfiles;
  },
  async vault(action: VaultAction) {
    return parseStatus(await mutate("/api/connections/vault", action));
  },
  async test(target: TestTarget): Promise<ConnectionTest> {
    const value = object(await mutate("/api/connections/test", { target }));
    exact(value, [
      "target",
      "status",
      "message",
      "billable",
      "inference_tested",
    ]);
    if (
      value.target !== target ||
      !["ok", "error", "not_configured"].includes(value.status as string) ||
      typeof value.message !== "string" ||
      value.billable !== false ||
      value.inference_tested !== false
    )
      throw invalid();
    return value as unknown as ConnectionTest;
  },
};

export function connectionError(error: unknown) {
  return error instanceof Error && error.message.startsWith("Connection ")
    ? error.message
    : "Connection request could not be completed. Reload connection settings.";
}
