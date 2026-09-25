import type { Provider } from "./connectionsApi";
import { providerLabels } from "./connectionsApi";

export type SetupStep = "model" | "compute" | "sources" | "review";
export interface SetupStatus {
  version: 1;
  completed: boolean;
  current_step: SetupStep;
  required: true;
  can_research: boolean;
  model: {
    status:
      | "not_connected"
      | "model_required"
      | "consent_required"
      | "credentials_locked"
      | "verification_required"
      | "ready"
      | "error";
    provider: Provider;
    model: string;
    account_id: string | null;
    message: string;
    checked_at: string | null;
  };
  optional: {
    compute: "local" | "aws_bedrock";
    aws_required: false;
    data_apis_required: false;
  };
}
/** Completed setup may ask the server to renew an expired readiness check.
 * The server still verifies credentials, model access and consent before research.
 */
export function canSubmitResearch(status: SetupStatus | null): boolean {
  return Boolean(
    status?.can_research ||
      (status?.completed &&
        status.model.status === "verification_required" &&
        status.model.provider !== "none" &&
        status.model.model.trim()),
  );
}
const steps: SetupStep[] = ["model", "compute", "sources", "review"];
function invalid() {
  return new Error(
    "Setup returned an unsupported response. Reload setup before continuing.",
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
function short(value: unknown, maximum = 2000): value is string {
  return typeof value === "string" && value.length <= maximum;
}
export function parseSetup(value: unknown): SetupStatus {
  const item = object(value),
    model = object(item.model),
    optional = object(item.optional);
  exact(item, [
    "version",
    "completed",
    "current_step",
    "required",
    "can_research",
    "model",
    "optional",
  ]);
  exact(model, [
    "status",
    "provider",
    "model",
    "account_id",
    "message",
    "checked_at",
  ]);
  exact(optional, ["compute", "aws_required", "data_apis_required"]);
  if (
    item.version !== 1 ||
    typeof item.completed !== "boolean" ||
    !steps.includes(item.current_step as SetupStep) ||
    item.required !== true ||
    typeof item.can_research !== "boolean" ||
    ![
      "not_connected",
      "model_required",
      "consent_required",
      "credentials_locked",
      "verification_required",
      "ready",
      "error",
    ].includes(model.status as string) ||
    typeof model.provider !== "string" ||
    !Object.hasOwn(providerLabels, model.provider) ||
    !short(model.model, 200) ||
    !short(model.message) ||
    (model.account_id !== null && !short(model.account_id, 128)) ||
    (model.checked_at !== null && !short(model.checked_at, 80)) ||
    !["local", "aws_bedrock"].includes(optional.compute as string) ||
    optional.aws_required !== false ||
    optional.data_apis_required !== false ||
    (item.can_research && model.status !== "ready")
  )
    throw invalid();
  return item as unknown as SetupStatus;
}
async function request(
  path: string,
  options: RequestInit = {},
): Promise<unknown> {
  const controller = new AbortController();
  const parent = options.signal;
  const abort = () => controller.abort();
  parent?.addEventListener("abort", abort, { once: true });
  if (parent?.aborted) controller.abort();
  const timer = window.setTimeout(abort, 45000);
  try {
    const response = await fetch(path, {
      ...options,
      signal: controller.signal,
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      headers: { Accept: "application/json", ...options.headers },
    });
    if (
      response.status === 409 &&
      (path === "/api/connections/setup" ||
        path.startsWith("/api/connections/setup/"))
    )
      throw new Error(
        "Setup cannot continue while another account check or research request is running. Wait for it to finish, then try this step again.",
      );
    if (!response.ok)
      throw new Error(
        `Setup could not complete this step (${response.status}). Check the selected connection and try again.`,
      );
    return await response.json();
  } catch (error) {
    if (
      parent?.aborted ||
      (error instanceof Error && error.message.startsWith("Setup "))
    )
      throw error;
    throw new Error(
      "Setup could not reach the application. Reload setup before trying again.",
    );
  } finally {
    window.clearTimeout(timer);
    parent?.removeEventListener("abort", abort);
  }
}
async function change(path: string, body: unknown, method = "POST") {
  const session = object(await request("/api/session"));
  if (!short(session.csrf_token, 512) || session.csrf_token.length < 16)
    throw invalid();
  return parseSetup(
    await request(path, {
      method,
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": session.csrf_token,
      },
      body: JSON.stringify(body),
    }),
  );
}
export const setupApi = {
  async status(signal?: AbortSignal) {
    return parseSetup(await request("/api/connections/setup", { signal }));
  },
  async progress(current_step: SetupStep) {
    return change("/api/connections/setup", { current_step }, "PUT");
  },
  async verify() {
    return change("/api/connections/setup/verify", {});
  },
  async complete() {
    return change("/api/connections/setup/complete", {});
  },
};
export function setupError(error: unknown) {
  return error instanceof Error && error.message.startsWith("Setup ")
    ? error.message
    : "Setup could not complete this step. Reload setup before continuing.";
}
