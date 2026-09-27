import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  connectionError,
  connectionsApi,
  connectableProviders,
  isApiKeyProvider,
  isCloudProvider,
  providerAccountLabels,
  providerLabels,
  secretLabels,
} from "./connectionsApi";
import type {
  ConnectionProfile,
  ConnectionStatus,
  ConnectionTest,
  ModelCatalog,
  Provider,
  SecretName,
  TestTarget,
  VaultAction,
} from "./connectionsApi";
import PublicSourcesPanel from "./PublicSources";
import MaterialsProjectConnection from "./MaterialsProjectConnection";
import { AgentConnectionsCard, ChatGPTSignIn } from "./AgentConnections";
import ClaudeCodeConnection from "./ClaudeCodeConnection";
import { modelConnectionSummary } from "./modelConnectionSummary";
import type { SetupStatus } from "./setupApi";
import LabcatMascot from "./LabcatMascot";
import "./connections.css";
import "./mascotPlacements.css";

interface ConnectionContextValue {
  status: ConnectionStatus | null;
  loading: boolean;
  busy: boolean;
  error: string;
  reload: () => Promise<ConnectionStatus>;
  apply: (
    operation: () => Promise<ConnectionStatus>,
  ) => Promise<ConnectionStatus>;
}
const ConnectionContext = createContext<ConnectionContextValue | null>(null);
export function useConnections() {
  const value = useContext(ConnectionContext);
  if (!value) throw new Error("Connection context is unavailable.");
  return value;
}
export function ConnectionsProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<ConnectionStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(true);
  const lock = useRef(false);
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    connectionsApi
      .status(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setStatus(value);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setError(connectionError(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => {
      mounted.current = false;
      controller.abort();
    };
  }, []);
  async function reload() {
    setLoading(true);
    setError("");
    try {
      const next = await connectionsApi.status();
      if (mounted.current) setStatus(next);
      return next;
    } catch (error) {
      if (mounted.current) setError(connectionError(error));
      throw error;
    } finally {
      if (mounted.current) setLoading(false);
    }
  }
  async function apply(operation: () => Promise<ConnectionStatus>) {
    if (lock.current)
      throw new Error("Connection change is already in progress.");
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const next = await operation();
      if (mounted.current) setStatus(next);
      return next;
    } catch (error) {
      if (mounted.current) setError(connectionError(error));
      throw error;
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <ConnectionContext.Provider
      value={{ status, loading, busy, error, reload, apply }}
    >
      {children}
    </ConnectionContext.Provider>
  );
}

const emptySecrets = (): Record<
  Exclude<SecretName, "materials_project">,
  string
> => ({
  openai: "",
  anthropic: "",
  kimi: "",
  gemini: "",
  deepseek: "",
  xai: "",
  openrouter: "",
});
const stateLabels = {
  missing: "No key saved",
  session: "This session only",
  encrypted: "Encrypted on disk",
  locked: "Vault locked",
};

export function ConnectionNotice({
  onConfigure,
  readiness,
  checking = false,
  unavailable = false,
}: {
  onConfigure: () => void;
  readiness: SetupStatus | null;
  checking?: boolean;
  unavailable?: boolean;
}) {
  const { status, loading, busy, error } = useConnections();
  const model = modelConnectionSummary({
    status,
    readiness,
    checking: checking || loading || busy,
    unavailable: unavailable || Boolean(error),
  });
  return (
    <aside
      className="connection-notice"
      aria-label="Active research connections"
    >
      <div>
        <strong>{model.title}</strong>
        <p>{model.note} Saved chats and reports remain available.</p>
        {error && (
          <p className="connection-error-text" role="alert">
            {error}
          </p>
        )}
      </div>
      <button className="quiet-button" type="button" onClick={onConfigure}>
        Connections
      </button>
    </aside>
  );
}

type ConnectionSection = "all" | "model" | "sources";
export interface ConnectionFormState {
  dirty: boolean;
  busy: boolean;
}
export function ConnectionsPanel({
  onboarding = false,
  onDone,
  section = "all",
  onSetup,
  onStateChange,
  onVerifyModel,
  overview,
}: {
  overview?: ReactNode;
  onboarding?: boolean;
  onDone?: () => void;
  section?: ConnectionSection;
  onSetup?: () => void;
  onStateChange?: (state: ConnectionFormState) => void;
  onVerifyModel?: () => Promise<ConnectionTest>;
}) {
  const connection = useConnections();
  const { status } = connection;
  if (!status)
    return (
      <section className="connections-page">
        <h1>Connect your workspace.</h1>
        <p>
          {connection.loading
            ? "Reading saved connection settings…"
            : connection.error}
        </p>
        {!connection.loading && (
          <button
            className="primary-button"
            type="button"
            onClick={() => void connection.reload().catch(() => undefined)}
          >
            Reload connections
          </button>
        )}
      </section>
    );
  return (
    <ConnectionForm
      key={section}
      status={status}
      onboarding={onboarding}
      onDone={onDone}
      section={section}
      onSetup={onSetup}
      onStateChange={onStateChange}
      onVerifyModel={onVerifyModel}
      overview={overview}
    />
  );
}

function ConnectionForm({
  status,
  onboarding,
  onDone,
  section,
  onSetup,
  onStateChange,
  onVerifyModel,
  overview,
}: {
  overview?: ReactNode;
  status: ConnectionStatus;
  onboarding: boolean;
  onDone?: () => void;
  section: ConnectionSection;
  onSetup?: () => void;
  onStateChange?: (state: ConnectionFormState) => void;
  onVerifyModel?: () => Promise<ConnectionTest>;
}) {
  const connection = useConnections();
  const [profile, setProfile] = useState<ConnectionProfile>(() => ({
    ...status.profile,
  }));
  const [accountId, setAccountId] = useState(status.active_account_id ?? "");
  const [accountLabel, setAccountLabel] = useState(
    status.accounts.find((account) => account.id === status.active_account_id)
      ?.label ?? providerAccountLabels[status.profile.provider],
  );
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [catalogRevision, setCatalogRevision] = useState(0);
  const catalogAttempt = useRef<{
    status: ConnectionStatus;
    accountId: string;
    provider: Provider;
    revision: number;
  } | null>(null);
  const [signInRequested, setSignInRequested] = useState("");
  const [secrets, setSecrets] = useState(emptySecrets);
  const [sourceState, setSourceState] = useState<ConnectionFormState>({
    dirty: false,
    busy: false,
  });
  const [sourceCredentialState, setSourceCredentialState] =
    useState<ConnectionFormState>({ dirty: false, busy: false });
  const [storage, setStorage] = useState<"session" | "encrypted">(
    status.vault.available && !status.vault.locked ? "encrypted" : "session",
  );
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [tests, setTests] = useState<ConnectionTest[]>([]);
  const [passphrase, setPassphrase] = useState("");
  const [confirmPassphrase, setConfirmPassphrase] = useState("");
  const [confirmReset, setConfirmReset] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmNewPassword, setConfirmNewPassword] = useState("");
  const [credentialDraftRevision, setCredentialDraftRevision] = useState(0);
  const mounted = useRef(true);
  const lock = useRef(false);
  const savedProfile = JSON.stringify(status.profile);
  const preferredAccounts = useRef(new Map<Provider, string>());
  useEffect(() => {
    const active = status.accounts.find(
      (account) => account.id === status.active_account_id,
    );
    if (active)
      preferredAccounts.current.set(active.profile.provider, active.id);
  }, [status]);
  const savedAccountIdentity = JSON.stringify([
    status.active_account_id,
    status.accounts.find((account) => account.id === status.active_account_id)
      ?.label,
  ]);
  useEffect(() => {
    setProfile({ ...status.profile });
  }, [savedProfile, section]);
  useEffect(() => {
    setAccountId(status.active_account_id ?? "");
    setAccountLabel(
      status.accounts.find((account) => account.id === status.active_account_id)
        ?.label ?? providerAccountLabels[status.profile.provider],
    );
    setCatalog(null);
  }, [savedAccountIdentity, section]);
  useEffect(() => {
    if (!status.vault.available || status.vault.locked) setStorage("session");
  }, [status.vault.available, status.vault.locked]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const busy = working || connection.busy || connection.loading;
  const cloud = isCloudProvider(profile.provider);
  const keyProvider = isApiKeyProvider(profile.provider)
    ? profile.provider
    : null;
  const modelRequired =
    section !== "sources" &&
    profile.provider !== "none" &&
    profile.provider !== "ollama";
  const showModel = section !== "sources";
  const showSources = section === "all" || section === "sources";
  const changed =
    JSON.stringify(profile) !== savedProfile ||
    Object.values(secrets).some(Boolean) ||
    (modelRequired &&
      (!accountId ||
        accountLabel !==
          status.accounts.find((account) => account.id === accountId)?.label));
  const validProfile =
    !connection.error &&
    (section === "sources" ||
      (modelRequired &&
        profile.provider !== "ollama" &&
        Boolean(accountLabel.trim())));
  useEffect(() => {
    onStateChange?.({
      dirty:
        changed ||
        Boolean(connection.error) ||
        sourceState.dirty ||
        sourceCredentialState.dirty,
      busy:
        busy ||
        catalogLoading ||
        sourceState.busy ||
        sourceCredentialState.busy,
    });
  }, [
    changed,
    connection.error,
    busy,
    catalogLoading,
    sourceState,
    sourceCredentialState,
    onStateChange,
  ]);
  useEffect(
    () => () => onStateChange?.({ dirty: false, busy: false }),
    [onStateChange],
  );

  const selectedAccount = status.accounts.find(
    (account) => account.id === accountId,
  );
  const needsCredentialUnlock = status.vault.locked;
  const [advancedCredentialsOpen, setAdvancedCredentialsOpen] = useState(false);
  const advancedCredentials = useRef<HTMLDetailsElement>(null);
  const providerAccounts = status.accounts.filter(
    (account) => account.profile.provider === profile.provider,
  );
  function revealCredentialOptions() {
    setAdvancedCredentialsOpen(true);
    const details = advancedCredentials.current;
    if (details) {
      details.open = true;
      details.scrollIntoView({ block: "start", behavior: "smooth" });
      details.querySelector("summary")?.focus();
    }
  }
  const catalogReady =
    showModel &&
    Boolean(accountId) &&
    status.active_account_id === accountId &&
    selectedAccount?.profile.provider === profile.provider &&
    (selectedAccount?.credential_state === "session" ||
      selectedAccount?.credential_state === "encrypted" ||
      selectedAccount?.credential_state === "not_required") &&
    !connection.error;
  useEffect(() => {
    const controller = new AbortController();
    if (!catalogReady) {
      catalogAttempt.current = null;
      setCatalog(null);
      setCatalogError("");
      setCatalogLoading(false);
      return () => controller.abort();
    }
    // Saving/sign-in/verification may use the same provider metadata lock. Defer
    // discovery until that operation finishes and avoid repeating a completed
    // request merely because a form busy flag changed.
    if (busy) {
      setCatalogLoading(false);
      return () => controller.abort();
    }
    const previous = catalogAttempt.current;
    if (
      previous?.status === status &&
      previous.accountId === accountId &&
      previous.provider === profile.provider &&
      previous.revision === catalogRevision
    )
      return () => controller.abort();
    const attempt = {
      status,
      accountId,
      provider: profile.provider,
      revision: catalogRevision,
    };
    catalogAttempt.current = attempt;
    let settled = false;
    setCatalog(null);
    setCatalogError("");
    setCatalogLoading(true);
    connectionsApi
      .models(controller.signal)
      .then((next) => {
        if (controller.signal.aborted) return;
        if (next.provider !== profile.provider)
          throw new Error(
            "Connection provider changed. Refresh the model list.",
          );
        setCatalog(next);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setCatalogError(connectionError(error));
      })
      .finally(() => {
        settled = true;
        if (!controller.signal.aborted) setCatalogLoading(false);
      });
    return () => {
      controller.abort();
      if (!settled && catalogAttempt.current === attempt)
        catalogAttempt.current = null;
    };
  }, [
    status,
    accountId,
    profile.provider,
    catalogReady,
    catalogRevision,
    busy,
  ]);

  async function task(operation: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    setWorking(true);
    setError("");
    setNotice("");
    try {
      await operation();
    } catch (error) {
      if (mounted.current) setError(connectionError(error));
    } finally {
      lock.current = false;
      if (mounted.current) setWorking(false);
    }
  }
  async function runTests(targets: TestTarget[]) {
    const results: ConnectionTest[] = [];
    for (const target of targets) {
      const result =
        target === "model" && onVerifyModel
          ? await onVerifyModel()
          : await connectionsApi.test(target);
      results.push(result);
      if (mounted.current) setTests([...results]);
    }
    if (targets.includes("materials_project")) await connection.reload();
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!validProfile) return;
    const enteredSecrets = { ...secrets };
    setSecrets(emptySecrets());
    setTests([]);
    void task(async () => {
      const next = await connection.apply(async () => {
        if (!modelRequired)
          return connectionsApi.save({
            profile,
            secret_storage: storage,
            secrets: enteredSecrets,
          });
        const next = await connectionsApi.saveAccount(
          {
            label: accountLabel.trim(),
            profile,
            secret_storage:
              profile.provider === "claude_code" ? "session" : storage,
            ...(keyProvider && enteredSecrets[keyProvider]
              ? { api_key: enteredSecrets[keyProvider] }
              : {}),
          },
          accountId || undefined,
        );
        return next;
      });
      if (mounted.current) {
        setProfile({ ...next.profile });
        setNotice(
          "Connection settings saved. Checking configured connections without running inference…",
        );
      }
      const targets: TestTarget[] = [];
      if (
        next.profile.provider !== "none" &&
        next.profile.model &&
        section !== "sources"
      )
        targets.push("model");
      await runTests(targets);
      if (mounted.current)
        setNotice(
          targets.length
            ? "Settings saved. Review the connection check results below."
            : section === "sources"
              ? "Source settings saved."
              : "Connection saved. Finish sign-in or choose an available model above.",
        );
    });
  }
  function clearConnectionDraft() {
    setSecrets(emptySecrets());
    setTests([]);
    setNotice("");
    setError("");
    setCatalog(null);
    setSignInRequested("");
  }
  function startAnotherAccount(provider: Provider) {
    if (lock.current || busy || connection.error) return;
    clearConnectionDraft();
    setProfile((current) => ({
      ...current,
      provider,
      model: provider === "claude_code" ? "default" : "",
      allow_paid_inference: false,
    }));
    setAccountId("");
    const base = providerAccountLabels[provider];
    const labels = new Set(status.accounts.map((account) => account.label));
    let label = base,
      suffix = 2;
    while (labels.has(label)) label = `${base} ${suffix++}`;
    setAccountLabel(provider === "none" ? "" : label);
  }
  function selectAccount(identifier: string) {
    if (lock.current || busy || connection.error) return;
    const account = status.accounts.find((item) => item.id === identifier);
    if (!account) return;
    clearConnectionDraft();
    preferredAccounts.current.set(account.profile.provider, account.id);
    if (account.id === status.active_account_id) {
      restoreConnection(status);
      return;
    }
    void task(async () => {
      const next = await connection.apply(() =>
        connectionsApi.selectAccount(account.id),
      );
      if (mounted.current) {
        restoreConnection(next);
        setNotice(`${account.label} selected.`);
      }
    });
  }
  function selectProvider(provider: Provider) {
    if (lock.current || busy || connection.error) return;
    // Keep each provider's last selected account available without discarding
    // any saved account, model, consent or credential.
    const existing =
      status.accounts.find(
        (account) =>
          account.id === status.active_account_id &&
          account.profile.provider === provider,
      ) ??
      status.accounts.find(
        (account) =>
          account.id === preferredAccounts.current.get(provider) &&
          account.profile.provider === provider,
      ) ??
      status.accounts.find(
        (account) =>
          account.profile.provider === provider &&
          ["session", "encrypted"].includes(account.credential_state),
      ) ??
      status.accounts.find((account) => account.profile.provider === provider);
    if (existing) selectAccount(existing.id);
    else startAnotherAccount(provider);
  }
  function restoreConnection(next: ConnectionStatus) {
    setProfile({ ...next.profile });
    setAccountId(next.active_account_id ?? "");
    setAccountLabel(
      next.accounts.find((account) => account.id === next.active_account_id)
        ?.label ?? providerAccountLabels[next.profile.provider],
    );
  }
  function loadModels() {
    setCatalogRevision((value) => value + 1);
  }
  async function prepareChatGPTSignIn() {
    if (!validProfile) return;
    await task(async () => {
      const next = await connection.apply(() =>
        connectionsApi.saveAccount(
          {
            label: accountLabel.trim() || providerAccountLabels.chatgpt,
            profile,
            secret_storage: storage,
          },
          accountId || undefined,
        ),
      );
      if (mounted.current && next.active_account_id) {
        setProfile({ ...next.profile });
        setAccountId(next.active_account_id);
        setSignInRequested(next.active_account_id);
      }
    });
  }
  async function prepareClaudeCodeSignIn() {
    if (!validProfile) return;
    await task(async () => {
      const next = await connection.apply(() =>
        connectionsApi.saveAccount(
          {
            label: accountLabel.trim() || providerAccountLabels.claude_code,
            profile,
            secret_storage: "session",
          },
          accountId || undefined,
        ),
      );
      if (mounted.current) restoreConnection(next);
    });
  }
  function forget(name: SecretName) {
    setSecrets(emptySecrets());
    void task(async () => {
      await connection.apply(() =>
        connectionsApi.save({
          profile: status.profile,
          secret_storage: "session",
          forget_secrets: [name],
        }),
      );
      if (mounted.current) setNotice(`${secretLabels[name]} key forgotten.`);
    });
  }
  function vault(action: VaultAction) {
    if (action.action === "lock" || action.action === "reset") {
      setSecrets(emptySecrets());
      setCredentialDraftRevision((value) => value + 1);
    }
    setCurrentPassword("");
    setNewPassword("");
    setConfirmNewPassword("");
    setPassphrase("");
    setConfirmPassphrase("");
    setConfirmReset(false);
    void task(async () => {
      await connection.apply(() => connectionsApi.vault(action));
      if (
        mounted.current &&
        (action.action === "create" || action.action === "unlock")
      )
        setStorage("encrypted");
      if (mounted.current)
        setNotice(
          action.action === "reset"
            ? "Vault reset. Vault-managed saved and session-only credentials were cleared. Reconnect those accounts and keys; native Claude Code sessions, connection preferences and chat history are unchanged."
            : action.action === "change_passphrase"
              ? "Vault password changed. Your saved credentials are available without entering the API keys again."
              : `Credential vault ${action.action === "create" ? "created" : action.action === "unlock" ? "unlocked" : "locked"}.`,
        );
    });
  }
  const passphraseValid = passphrase.length >= 12 && passphrase.length <= 1024;
  const passwordChangeValid =
    currentPassword.length >= 12 &&
    currentPassword.length <= 1024 &&
    newPassword.length >= 12 &&
    newPassword.length <= 1024 &&
    newPassword === confirmNewPassword;
  const vaultCard = (
    <section
      className={`connection-card vault-card card ${status.vault.locked ? "locked" : ""}`}
    >
      <div className="connection-card-heading">
        <div>
          <p className="eyebrow">LOCAL CREDENTIAL VAULT</p>
          <h2>
            {status.vault.locked
              ? "Unlock saved credentials."
              : status.vault.available
                ? "Your credential vault is ready."
                : "Choose whether to remember keys."}
          </h2>
        </div>
        <span className="credential-badge">
          {status.vault.locked
            ? "Locked"
            : status.vault.available
              ? "Unlocked"
              : "Not configured"}
        </span>
      </div>
      {status.vault.can_create ? (
        <>
          <p>
            Create a vault password to remember credentials securely on this
            machine. Unlock once after the Labcat server restarts; you do not
            need to enter each saved API key again. This password is separate
            from your provider account password.
          </p>
          <div className="connection-field-grid">
            <div>
              <label htmlFor="vault-passphrase">New vault password</label>
              <input
                id="vault-passphrase"
                type="password"
                autoComplete="new-password"
                value={passphrase}
                minLength={12}
                maxLength={1024}
                disabled={busy}
                onChange={(event) => setPassphrase(event.target.value)}
              />
            </div>
            <div>
              <label htmlFor="vault-confirm">Confirm vault password</label>
              <input
                id="vault-confirm"
                type="password"
                autoComplete="new-password"
                value={confirmPassphrase}
                maxLength={1024}
                disabled={busy}
                onChange={(event) => setConfirmPassphrase(event.target.value)}
              />
            </div>
          </div>
          <p className="field-help">
            Use at least 12 characters. The password is not saved on disk. If
            you forget it, reset the vault and reconnect your credentials.
          </p>
          <button
            className="quiet-button"
            type="button"
            disabled={
              busy || !passphraseValid || passphrase !== confirmPassphrase
            }
            onClick={() => vault({ action: "create", passphrase })}
          >
            Create credential vault
          </button>
        </>
      ) : status.vault.locked && status.vault.key_source === "passphrase" ? (
        <>
          <p>
            Enter your vault password once after the Labcat server restarts.
            Your saved API keys and vault-managed account sign-ins become
            available without entering them again. Saved keys are never sent
            back to this browser. Chats remain available while the vault is
            locked.
          </p>
          <label htmlFor="vault-unlock">Vault password</label>
          <input
            id="vault-unlock"
            type="password"
            autoComplete="current-password"
            value={passphrase}
            maxLength={1024}
            disabled={busy}
            onChange={(event) => setPassphrase(event.target.value)}
          />
          <button
            className="quiet-button"
            type="button"
            disabled={busy || !passphraseValid}
            onClick={() => vault({ action: "unlock", passphrase })}
          >
            Unlock credentials
          </button>
        </>
      ) : status.vault.available ? (
        <>
          <p>
            {status.vault.key_source === "passphrase"
              ? "Your saved credentials are available. Leave API-key fields blank to keep using them; their values are never sent to this browser. Locking clears active vault-managed credentials, including session-only keys. Native Claude Code sessions are separate. Saved encrypted keys remain on disk and can be unlocked again."
              : "This installation supplies the encryption key through its deployment configuration."}
          </p>
          {status.vault.key_source === "passphrase" && (
            <button
              className="quiet-button"
              type="button"
              disabled={busy}
              onClick={() => vault({ action: "lock" })}
            >
              Lock credentials
            </button>
          )}
        </>
      ) : (
        <p>
          The deployment encryption key is unavailable. Ask the site
          administrator to restore it, or use session-only keys.
        </p>
      )}
      {status.vault.exists && status.vault.key_source === "passphrase" && (
        <details className="vault-change-password vault-reset">
          <summary>Change vault password</summary>
          <p>
            Enter the current password and choose a new password of at least 12
            characters. Saved credentials stay encrypted and remain available;
            you will use the new password after the next server restart.
          </p>
          <label htmlFor="vault-current-password">Current vault password</label>
          <input
            id="vault-current-password"
            type="password"
            autoComplete="current-password"
            maxLength={1024}
            value={currentPassword}
            disabled={busy}
            onChange={(event) => setCurrentPassword(event.target.value)}
          />
          <label htmlFor="vault-new-password">New vault password</label>
          <input
            id="vault-new-password"
            type="password"
            autoComplete="new-password"
            minLength={12}
            maxLength={1024}
            value={newPassword}
            disabled={busy}
            onChange={(event) => setNewPassword(event.target.value)}
          />
          <label htmlFor="vault-new-password-confirm">
            Confirm new vault password
          </label>
          <input
            id="vault-new-password-confirm"
            type="password"
            autoComplete="new-password"
            maxLength={1024}
            value={confirmNewPassword}
            disabled={busy}
            onChange={(event) => setConfirmNewPassword(event.target.value)}
          />
          <button
            className="quiet-button"
            type="button"
            disabled={busy || !passwordChangeValid}
            onClick={() =>
              vault({
                action: "change_passphrase",
                current_passphrase: currentPassword,
                new_passphrase: newPassword,
              })
            }
          >
            Change vault password
          </button>
        </details>
      )}
      {status.vault.exists && (
        <details className="vault-reset">
          <summary>
            {status.vault.key_source === "passphrase"
              ? "Forgot password? Reset vault"
              : "Reset credential vault"}
          </summary>
          <p>
            This clears all vault-managed saved encrypted and session-only
            credentials, including saved account sign-ins
            {status.vault.key_source === "passphrase"
              ? ", and removes the vault password"
              : ""}
            . You will need to enter API keys or sign in again. Connection
            preferences, projects, chats and reports are kept. Cleared
            credentials cannot be recovered by Labcat. Native Claude Code
            sessions are separate; use End Claude Code session to clear them.
          </p>
          <label className="reset-confirm">
            <input
              type="checkbox"
              checked={confirmReset}
              disabled={busy}
              onChange={(event) => setConfirmReset(event.target.checked)}
            />
            <span>
              I understand that all vault-managed encrypted and session-only
              credentials will be cleared.
            </span>
          </label>
          <button
            className="danger-button"
            type="button"
            disabled={busy || !confirmReset}
            onClick={() => vault({ action: "reset", confirm: true })}
          >
            Reset vault and clear credentials
          </button>
        </details>
      )}
    </section>
  );
  return (
    <section
      className={`connections-page ${section !== "all" ? "connection-setup-section" : ""}`}
    >
      {section === "all" && (
        <header className="connections-intro mascot-settings-header">
          {!onboarding && (
            <LabcatMascot scene="wires" className="mascot-header" />
          )}
          <p className="eyebrow">LOCAL WORKSPACE · CONNECTIONS</p>
          <h1>Your sources and model connections.</h1>
          <p>
            Connect a language model for research. Additional public databases
            are optional.
          </p>
          {onSetup && (
            <button className="quiet-button" type="button" onClick={onSetup}>
              Open setup
            </button>
          )}
        </header>
      )}
      {section === "all" && overview}
      {section === "all" && <AgentConnectionsCard />}
      {needsCredentialUnlock && (
        <div className="credential-unlock-notice" role="status">
          <p>
            {status.vault.key_source === "passphrase"
              ? "The vault is optional. Switch accounts or connect again for this server session without unlocking. Unlock only to reuse saved credentials; a forgotten password can be reset in credential options."
              : "The encryption key for saved credentials is unavailable. Review credential storage for session-only access or ask your administrator to restore it."}{" "}
            Chats and reports remain available.
          </p>
          <button
            className="quiet-button"
            type="button"
            onClick={revealCredentialOptions}
          >
            {status.vault.key_source === "passphrase"
              ? "Unlock saved credentials"
              : "Review credential storage"}
          </button>
        </div>
      )}
      {showModel && (
        <form
          onSubmit={submit}
          className="connection-settings-form"
          autoComplete="off"
        >
          {showModel && (
            <section className="connection-card card">
              <div className="connection-card-heading">
                <div>
                  <p className="eyebrow">REQUIRED RESEARCH MODEL</p>
                  <h2>Language model provider</h2>
                </div>
              </div>
              <p>
                Choose a provider and account, then select a model for research.
                The credential vault is optional; you can connect for this
                server session.
              </p>
              <label htmlFor="model-provider">Model provider</label>
              <select
                id="model-provider"
                value={profile.provider}
                disabled={busy || Boolean(connection.error)}
                onChange={(event) =>
                  selectProvider(event.target.value as Provider)
                }
              >
                {profile.provider === "none" && (
                  <option value="none" disabled>
                    Choose a provider…
                  </option>
                )}
                {profile.provider === "ollama" && (
                  <option value="ollama" disabled>
                    Choose an account provider…
                  </option>
                )}
                {connectableProviders.map((value) => (
                  <option key={value} value={value}>
                    {providerLabels[value]}
                  </option>
                ))}
              </select>
              {providerAccounts.length > 0 && (
                <>
                  <label htmlFor="provider-account">Account</label>
                  <select
                    id="provider-account"
                    value={accountId}
                    disabled={busy || Boolean(connection.error)}
                    onChange={(event) =>
                      event.target.value
                        ? selectAccount(event.target.value)
                        : startAnotherAccount(profile.provider)
                    }
                  >
                    {providerAccounts.map((account) => (
                      <option key={account.id} value={account.id}>
                        {account.label} ·{" "}
                        {account.profile.model || "Choose a model"}
                        {account.credential_state === "locked"
                          ? " · Reconnect or unlock"
                          : account.credential_state === "missing"
                            ? " · Connect to use"
                            : ""}
                      </option>
                    ))}
                    <option value="" disabled={status.accounts.length >= 12}>
                      Connect another account…
                    </option>
                  </select>
                  {!accountId && (
                    <>
                      <label htmlFor="new-account-label">Account label</label>
                      <input
                        id="new-account-label"
                        type="text"
                        value={accountLabel}
                        maxLength={80}
                        disabled={busy}
                        onChange={(event) =>
                          setAccountLabel(event.target.value)
                        }
                      />
                      <p className="field-help">
                        Give this account a name you will recognize when
                        switching. Your other accounts and their saved models
                        stay available.
                      </p>
                    </>
                  )}
                </>
              )}
              <p className="field-help">
                {profile.provider === "chatgpt"
                  ? "Connect using your existing ChatGPT account in the browser."
                  : profile.provider === "claude_code"
                    ? "Connect through the native Claude Code terminal sign-in. No API key or vault is required."
                    : profile.provider === "none" ||
                        profile.provider === "ollama"
                      ? "ChatGPT and Claude Code support account sign-in. API providers use an API key."
                      : `Connect ${providerAccountLabels[profile.provider]} using its API key.`}
              </p>

              {keyProvider && (
                <>
                  <div className="secret-field-heading">
                    <label htmlFor="provider-key">
                      {secretLabels[keyProvider]} API key
                    </label>
                    <span
                      className={`credential-badge ${accountId ? status.credentials[keyProvider] : "missing"}`}
                    >
                      {accountId
                        ? stateLabels[status.credentials[keyProvider]]
                        : "No key saved"}
                    </span>
                  </div>
                  <input
                    id="provider-key"
                    type="password"
                    autoComplete="off"
                    spellCheck={false}
                    maxLength={4096}
                    value={secrets[keyProvider]}
                    onChange={(event) =>
                      setSecrets((current) => ({
                        ...current,
                        [keyProvider]: event.target.value,
                      }))
                    }
                    disabled={busy}
                    placeholder={
                      accountId
                        ? "Leave blank to keep this account’s key"
                        : "Enter an API key for this account"
                    }
                  />
                  <p className="field-help">
                    {accountId && status.credentials[keyProvider] !== "missing"
                      ? "A key is already saved. Leave this field blank to keep it; saved key values are never sent to your browser. "
                      : "Enter this provider’s API key. "}
                    A consumer chat subscription is not an API login.
                  </p>
                  {status.vault.locked && (
                    <p className="field-help">
                      To use your encrypted key, unlock saved credentials above.
                      You can also paste the same or a different API key for
                      this server session. Submitted keys stay in memory until
                      the server stops; your saved encrypted keys stay
                      unchanged.
                    </p>
                  )}
                  <button
                    className="quiet-button"
                    type="button"
                    disabled={busy || !validProfile || !secrets[keyProvider]}
                    onClick={(event) => submit(event)}
                  >
                    {accountId
                      ? "Save API key"
                      : `Connect ${providerAccountLabels[profile.provider]}`}
                  </button>
                  <button
                    className="text-action"
                    type="button"
                    disabled={
                      busy ||
                      changed ||
                      !accountId ||
                      status.credentials[keyProvider] === "missing" ||
                      status.vault.locked
                    }
                    onClick={() => forget(keyProvider)}
                  >
                    Forget {secretLabels[keyProvider]} key
                  </button>
                </>
              )}
              {profile.provider === "chatgpt" && (
                <ChatGPTSignIn
                  key={accountId || "new-chatgpt-account"}
                  accountId={accountId}
                  saved={
                    Boolean(accountId) &&
                    JSON.stringify(profile) === savedProfile
                  }
                  storage={storage}
                  disabled={busy || Boolean(connection.error)}
                  onPrepare={() => void prepareChatGPTSignIn()}
                  startRequested={
                    signInRequested === accountId && Boolean(accountId)
                  }
                  onStartHandled={() => setSignInRequested("")}
                />
              )}
              {profile.provider === "claude_code" && (
                <ClaudeCodeConnection
                  key={accountId || "new-claude-code-account"}
                  accountId={accountId}
                  disabled={
                    busy ||
                    Boolean(connection.error) ||
                    (!accountId && !validProfile)
                  }
                  onPrepare={() => void prepareClaudeCodeSignIn()}
                />
              )}
              {profile.provider === "anthropic" && (
                <p className="field-help">
                  Claude models connect through an Anthropic API key here. For
                  native Claude Code account sign-in, choose Anthropic (Claude
                  Code sign-in) from Model provider.
                </p>
              )}
              {modelRequired && (
                <section
                  className="connection-model-choice"
                  aria-label="Choose an available model"
                >
                  <div className="model-picker-heading">
                    <label htmlFor="model-choice">Model</label>
                    {catalogReady && (
                      <button
                        className="text-action"
                        type="button"
                        disabled={busy || catalogLoading}
                        onClick={loadModels}
                      >
                        {catalogLoading ? "Loading models…" : "Refresh models"}
                      </button>
                    )}
                  </div>
                  <select
                    id="model-choice"
                    value={profile.model}
                    disabled={busy || catalogLoading || !catalogReady}
                    onChange={(event) =>
                      setProfile((current) => ({
                        ...current,
                        model: event.target.value,
                      }))
                    }
                  >
                    <option value="">
                      {catalogLoading
                        ? "Loading available models…"
                        : catalogReady
                          ? "Choose a model…"
                          : "Connect your account first…"}
                    </option>
                    {profile.model &&
                      !catalog?.models.some(
                        (model) => model.id === profile.model,
                      ) && (
                        <option value={profile.model}>
                          {profile.model} · saved model
                        </option>
                      )}
                    {catalog?.models.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.label}
                      </option>
                    ))}
                  </select>
                  <p className="field-help">
                    {catalogLoading
                      ? "Reading the models available to this account. No inference is run."
                      : catalog?.message ||
                        (catalogReady
                          ? "Choose a returned model, then save your selection below."
                          : profile.provider === "claude_code"
                            ? "Finish native terminal sign-in, then check its status above. Available choices are Claude Code aliases; they do not verify account entitlement or run inference."
                            : profile.provider === "chatgpt"
                              ? "Finish provider sign-in to load available models automatically."
                              : "Save your credentials above to load available models automatically.")}
                  </p>
                  {catalogError && (
                    <p className="connection-error-text" role="alert">
                      The model list could not be loaded. Check the connection
                      and use Refresh models to try again.
                    </p>
                  )}
                  {profile.provider !== "claude_code" && (
                    <details className="model-advanced">
                      <summary>Advanced model settings</summary>
                      <label htmlFor="custom-model-id">Model identifier</label>
                      <input
                        id="custom-model-id"
                        value={profile.model}
                        disabled={busy || !catalogReady}
                        autoComplete="off"
                        maxLength={200}
                        onChange={(event) =>
                          setProfile((current) => ({
                            ...current,
                            model: event.target.value,
                          }))
                        }
                        placeholder="Exact identifier supplied by your provider"
                      />
                      <p className="field-help">
                        Only use this when your provider documents a model that
                        is absent from its returned list.
                      </p>
                    </details>
                  )}
                </section>
              )}
              {cloud && (
                <div className="cloud-consent">
                  <strong>Before enabling cloud planning</strong>
                  <p>
                    New prompts and bounded conversation/project context will be
                    sent to {providerLabels[profile.provider]}. Model calls may
                    incur provider charges. The application stores chats
                    locally; only the selected context is sent for planning.
                  </p>
                  <label>
                    <input
                      type="checkbox"
                      checked={profile.allow_paid_inference}
                      disabled={busy}
                      onChange={(event) =>
                        setProfile((current) => ({
                          ...current,
                          allow_paid_inference: event.target.checked,
                        }))
                      }
                    />
                    <span>
                      I allow this provider to receive that context and run
                      potentially billable planning calls.
                    </span>
                  </label>
                </div>
              )}
              {modelRequired && (
                <div className="connection-inline-actions">
                  <button
                    className="quiet-button"
                    type="button"
                    disabled={
                      busy ||
                      Boolean(connection.error) ||
                      changed ||
                      catalogLoading
                    }
                    onClick={() => void task(() => runTests(["model"]))}
                  >
                    Verify connection
                  </button>
                  <span className="field-help">
                    Readiness only · No inference test
                  </span>
                </div>
              )}
            </section>
          )}

          {changed && (
            <p className="connection-unsaved">
              Connection changes are not active yet. Save them before testing or
              sending a new request.
            </p>
          )}
          <div className="connection-save-actions">
            <button
              className="quiet-button"
              type="button"
              disabled={busy}
              onClick={() => {
                setSecrets(emptySecrets());
                void task(async () => {
                  const next = await connection.reload();
                  if (mounted.current) {
                    restoreConnection(next);
                    setTests([]);
                    setCatalog(null);
                    setSignInRequested("");
                    setNotice("Connection settings reloaded.");
                  }
                });
              }}
            >
              Reload saved settings
            </button>
            <button
              className="primary-button"
              type="submit"
              disabled={busy || catalogLoading || !validProfile}
            >
              {busy ? "Working…" : "Save and test connections"}
            </button>
          </div>
        </form>
      )}
      {showSources && (
        <PublicSourcesPanel
          context="connections"
          onStateChange={setSourceState}
          refreshKey={JSON.stringify(status.source_connections ?? {})}
          materialsProjectCard={
            <MaterialsProjectConnection
              key={credentialDraftRevision}
              disabled={working}
              onCredentialOptions={revealCredentialOptions}
              onStateChange={setSourceCredentialState}
            />
          }
        />
      )}
      <details
        className="advanced-credentials card"
        ref={advancedCredentials}
        open={advancedCredentialsOpen}
        onToggle={(event) =>
          setAdvancedCredentialsOpen(event.currentTarget.open)
        }
      >
        <summary>Advanced credential options</summary>
        <p className="credential-privacy-note">
          Unlock saved credentials, change your vault password, or reset a
          forgotten password here. Connection credentials are kept out of chat
          and session history and are never sent back to the browser.
        </p>
        <div className="advanced-credential-controls">
          <section className="connection-card card">
            <p className="eyebrow">CREDENTIAL STORAGE</p>
            <h2>Choose how to remember credentials.</h2>
            <p>
              Keys entered here are write-only and never placed in browser
              storage. Connection preferences are remembered separately from
              secrets. Choose encrypted storage to remember an available model
              key without entering it again, then save the connection. Leaving
              the key field blank keeps its value. Research database keys use
              the storage option in their own card.
            </p>
            <div className="storage-options">
              <label>
                <input
                  type="radio"
                  name="secret-storage"
                  value="session"
                  checked={storage === "session"}
                  disabled={busy}
                  onChange={() => setStorage("session")}
                />
                <span>
                  <strong>This server session</strong>
                  <small>
                    Submitted keys stay in memory until the server stops. Any
                    existing encrypted key stays saved and is used again after
                    restarting and unlocking. Leave the key blank to keep its
                    saved value.
                  </small>
                </span>
              </label>
              <label>
                <input
                  type="radio"
                  name="secret-storage"
                  value="encrypted"
                  checked={storage === "encrypted"}
                  disabled={
                    busy || !status.vault.available || status.vault.locked
                  }
                  onChange={() => setStorage("encrypted")}
                />
                <span>
                  <strong>Encrypted credential vault</strong>
                  <small>
                    {status.vault.available && !status.vault.locked
                      ? "Encrypt submitted or already available model keys on disk when you save the connection."
                      : "Create or unlock the credential vault below before selecting this option."}
                  </small>
                </span>
              </label>
            </div>
            <p className="field-help">
              Passwords and keys are cleared from this form when submitted.
              Leave a key field blank to retain its saved value.
            </p>
          </section>
          {vaultCard}
        </div>
      </details>
      {(error || connection.error) && (
        <div className="workspace-error" role="alert">
          <p>{error || connection.error}</p>
        </div>
      )}
      {notice && (
        <p className="connection-saved" role="status">
          {notice}
        </p>
      )}
      {tests.length > 0 && (
        <section
          className="connection-test-results"
          aria-label="Connection check results"
        >
          <h2>Connection checks</h2>
          {tests.map((result) => (
            <div
              key={result.target}
              className={`connection-test ${result.status}`}
              role="status"
            >
              <strong>
                {result.target === "materials_project"
                  ? "Materials Project"
                  : "Model connection"}{" "}
                ·{" "}
                {result.status === "ok"
                  ? "Ready"
                  : result.status === "not_configured"
                    ? "Not configured"
                    : "Needs attention"}
              </strong>
              <p>{result.message}</p>
            </div>
          ))}
          <p className="field-help">
            These checks do not run model inference or prove the scientific
            quality of any result.
          </p>
        </section>
      )}
      {status.warnings.length > 0 && (
        <div className="connection-warnings" role="status">
          {status.warnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </div>
      )}
      {!onboarding && onDone && (
        <div className="connection-return">
          <button
            className="quiet-button"
            type="button"
            disabled={busy}
            onClick={onDone}
          >
            Return to chat
          </button>
        </div>
      )}
    </section>
  );
}
