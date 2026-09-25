import {
  isApiKeyProvider,
  isCloudProvider,
  providerAccountLabels,
} from "./connectionsApi";
import type { ConnectionStatus } from "./connectionsApi";
import type { SetupStatus } from "./setupApi";

export interface ModelConnectionSummary {
  title: string;
  note: string;
  available: boolean;
}

/** Present the selected connection without treating stored credentials as a verified login. */
export function modelConnectionSummary({
  status,
  readiness,
  checking = false,
  unavailable = false,
}: {
  status: ConnectionStatus | null;
  readiness: SetupStatus | null;
  checking?: boolean;
  unavailable?: boolean;
}): ModelConnectionSummary {
  const profile = status?.profile;
  const provider = profile?.provider ?? "none";
  const name =
    provider === "none" ? "Language model" : providerAccountLabels[provider];
  const model = profile?.model.trim();
  const summary = (label: string, detail: string, available = false) => ({
    title: `${name} · ${label}`,
    note: [model, detail].filter(Boolean).join(" · "),
    available,
  });
  if (unavailable)
    return summary(
      "Status unavailable",
      "Reload Connections to check this account.",
    );
  if (checking)
    return summary(
      "Checking connection…",
      "Reading the selected account and model status.",
    );
  if (!status || !profile)
    return summary(
      "Status unavailable",
      "Reload Connections to check this account.",
    );
  if (provider === "none")
    return {
      title: "No account selected",
      note: "Choose an account and model in Connections.",
      available: false,
    };

  const account = status.accounts.find(
    (item) => item.id === status.active_account_id,
  );
  const accountMatches =
    account &&
    (
      [
        "provider",
        "model",
        "ollama_url",
        "aws_profile",
        "aws_region",
        "allow_paid_inference",
      ] as const
    ).every((key) => account.profile[key] === profile[key]);
  const credential = accountMatches
    ? account.credential_state
    : !status.active_account_id && isApiKeyProvider(provider)
      ? status.credentials[provider]
      : "missing";
  const matched =
    readiness?.model.account_id === status.active_account_id &&
    readiness.model.provider === provider &&
    readiness.model.model === profile.model &&
    (!status.active_account_id || accountMatches);
  const state = matched ? readiness.model.status : null;
  if (credential === "locked" || state === "credentials_locked") {
    return summary(
      "Connection locked",
      "Unlock saved credentials in Connections.",
    );
  }
  const needsCredential = provider === "chatgpt" || isApiKeyProvider(provider);
  if (
    (needsCredential &&
      credential !== "session" &&
      credential !== "encrypted") ||
    state === "not_connected"
  ) {
    return provider === "chatgpt"
      ? summary("Not signed in", "Sign in to ChatGPT in Connections.")
      : summary("Not connected", "Connect this provider in Connections.");
  }
  if (state === "error")
    return summary(
      "Connection needs attention",
      "Check this account in Connections.",
    );
  if (!model || state === "model_required")
    return summary("Choose a model", "Select a model in Connections.");
  if (
    (isCloudProvider(provider) && !profile.allow_paid_inference) ||
    state === "consent_required"
  ) {
    return summary(
      "Allow research access",
      "Allow this provider to receive research context in Connections.",
    );
  }
  if (
    matched &&
    readiness.can_research &&
    state === "ready" &&
    readiness.model.checked_at
  ) {
    return summary(
      provider === "chatgpt" ? "Signed in" : "Connected",
      "Account and model verified. Ready for research.",
      true,
    );
  }
  return summary(
    "Check connection",
    "Saved connection. Verify it in Connections or when you send a research request.",
  );
}
