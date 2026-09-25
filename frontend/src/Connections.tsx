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
  AwsProfiles,
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
import { modelConnectionSummary } from "./modelConnectionSummary";
import type { SetupStatus } from "./setupApi";
import "./connections.css";

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

type ConnectionSection = "all" | "model" | "compute" | "sources";
export interface ConnectionFormState {
  dirty: boolean;
  busy: boolean;
}
function draftConnection(status: ConnectionStatus, section: ConnectionSection) {
  return section === "compute" && status.profile.provider !== "bedrock"
    ? {
        ...status.profile,
        provider: "bedrock" as const,
        model: "",
        allow_paid_inference: false,
      }
    : { ...status.profile };
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
  const [profile, setProfile] = useState<ConnectionProfile>(() =>
    draftConnection(status, section),
  );
  const [accountId, setAccountId] = useState(
    section === "compute" && status.profile.provider !== "bedrock"
      ? ""
      : (status.active_account_id ?? ""),
  );
  const [accountLabel, setAccountLabel] = useState(
    section === "compute" && status.profile.provider !== "bedrock"
      ? "Amazon Bedrock"
      : (status.accounts.find(
          (account) => account.id === status.active_account_id,
        )?.label ?? providerAccountLabels[status.profile.provider]),
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
  const [aws, setAws] = useState<AwsProfiles | null>(null);
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
    setProfile(draftConnection(status, section));
  }, [savedProfile, section]);
  useEffect(() => {
    setAccountId(
      section === "compute" && status.profile.provider !== "bedrock"
        ? ""
        : (status.active_account_id ?? ""),
    );
    setAccountLabel(
      section === "compute" && status.profile.provider !== "bedrock"
        ? "Amazon Bedrock"
        : (status.accounts.find(
            (account) => account.id === status.active_account_id,
          )?.label ?? providerAccountLabels[status.profile.provider]),
    );
    setCatalog(null);
  }, [savedAccountIdentity, section]);
  useEffect(() => {
    if (profile.provider !== "bedrock") return;
    const controller = new AbortController();
    connectionsApi
      .awsProfiles(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setAws(value);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setError(connectionError(error));
      });
    return () => controller.abort();
  }, [profile.provider]);
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
        Boolean(accountLabel.trim()) &&
        (profile.provider !== "bedrock" ||
          Boolean(profile.aws_profile && profile.aws_region))));
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
  const needsCredentialUnlock =
    status.vault.locked &&
    ((showModel && selectedAccount?.credential_state === "locked") ||
      (showSources && status.credentials.materials_project === "locked"));
  const [advancedCredentialsOpen, setAdvancedCredentialsOpen] = useState(
    needsCredentialUnlock,
  );
  const advancedCredentials = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (needsCredentialUnlock) setAdvancedCredentialsOpen(true);
  }, [needsCredentialUnlock]);
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
            secret_storage: storage,
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
  function selectProvider(provider: Provider) {
    if (lock.current || busy || connection.error) return;
    setSecrets(emptySecrets());
    setTests([]);
    setNotice("");
    setError("");
    setCatalog(null);
    setSignInRequested("");
    // Retain provider sessions internally without making users manage named
    // connections. Prefer the active account when a legacy workspace has more
    // than one connection for this provider; never delete the others.
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
    if (existing) {
      if (existing.id === status.active_account_id) {
        restoreConnection(status);
      } else {
        void task(async () => {
          const next = await connection.apply(() =>
            connectionsApi.selectAccount(existing.id),
          );
          if (mounted.current) {
            restoreConnection(next);
            setNotice(`${providerAccountLabels[provider]} selected.`);
          }
        });
      }
      return;
    }
    setProfile((current) => ({
      ...current,
      provider,
      model: "",
      allow_paid_inference: false,
    }));
    setAccountId("");
    setAccountLabel(provider === "none" ? "" : providerAccountLabels[provider]);
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
    if (action.action === "lock" || action.action === "reset")
      setSecrets(emptySecrets());
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
            ? "Encrypted keys removed. Connection preferences and chat history are unchanged."
            : `Credential vault ${action.action === "create" ? "created" : action.action === "unlock" ? "unlocked" : "locked"}.`,
        );
    });
  }
  const passphraseValid = passphrase.length >= 12 && passphrase.length <= 1024;
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
            Create an application vault passphrase to encrypt keys on this
            machine. It is not an AWS or model-account password. You will need
            it to unlock saved keys after restarting.
          </p>
          <div className="connection-field-grid">
            <div>
              <label htmlFor="vault-passphrase">New vault passphrase</label>
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
              <label htmlFor="vault-confirm">Confirm vault passphrase</label>
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
            Use at least 12 characters. This app does not save the passphrase.
            If you forget it, encrypted keys must be reset and entered again.
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
            Unlock the vault to make its encrypted keys available for this
            server session. Saved chats remain available while the vault is
            locked.
          </p>
          <label htmlFor="vault-unlock">Vault passphrase</label>
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
              ? "Locking clears all active keys from memory, including session-only keys. Saved encrypted keys remain on disk and can be unlocked again."
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
      {status.vault.exists && (
        <details className="vault-reset">
          <summary>Reset encrypted credentials</summary>
          <p>
            This deletes the encrypted API keys. Separately entered session-only
            keys, connection preferences, projects and chat history are
            retained. You will need to enter those keys again.
          </p>
          <label className="reset-confirm">
            <input
              type="checkbox"
              checked={confirmReset}
              disabled={busy}
              onChange={(event) => setConfirmReset(event.target.checked)}
            />
            <span>I understand that the encrypted keys will be deleted.</span>
          </label>
          <button
            className="danger-button"
            type="button"
            disabled={busy || !confirmReset}
            onClick={() => vault({ action: "reset", confirm: true })}
          >
            Reset encrypted keys
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
          <p className="eyebrow">LOCAL WORKSPACE · CONNECTIONS</p>
          <h1>Your sources and model connections.</h1>
          <p>
            Connect a language model for research. AWS model compute and
            additional public databases are optional.
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
            Your saved connection needs its credentials unlocked. Chats and
            reports remain available.
          </p>
          <button
            className="quiet-button"
            type="button"
            onClick={revealCredentialOptions}
          >
            Review saved credentials
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
                  <p className="eyebrow">
                    {section === "compute"
                      ? "OPTIONAL AWS MODEL CONNECTION"
                      : "REQUIRED RESEARCH MODEL"}
                  </p>
                  <h2>Language model provider</h2>
                </div>
              </div>
              <p>
                Choose a provider, connect it, then select a model for research.
              </p>
              <label htmlFor="model-provider">Model provider</label>
              <select
                id="model-provider"
                value={profile.provider}
                disabled={
                  busy || Boolean(connection.error) || section === "compute"
                }
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
              <p className="field-help">
                {profile.provider === "chatgpt"
                  ? "Connect using your existing ChatGPT account in the browser."
                  : profile.provider === "bedrock"
                    ? "Use an AWS profile to access models available through Amazon Bedrock."
                    : profile.provider === "none" ||
                        profile.provider === "ollama"
                      ? "ChatGPT supports account sign-in. Other providers use an API key or AWS profile."
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
                    Use provider API credentials. A consumer chat subscription
                    is not an API login.
                  </p>
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
                      status.credentials[keyProvider] === "missing"
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
              {profile.provider === "anthropic" && (
                <p className="field-help">
                  Claude models connect through an Anthropic API key here, or
                  through Amazon Bedrock. Signing into a Claude consumer
                  subscription is not supported by this connection.
                </p>
              )}
              {profile.provider === "bedrock" && (
                <section className="aws-connection-setup">
                  <div className="connection-field-grid">
                    <div>
                      <label htmlFor="aws-profile">AWS profile</label>
                      <select
                        id="aws-profile"
                        value={profile.aws_profile}
                        disabled={busy}
                        onChange={(event) =>
                          setProfile((current) => ({
                            ...current,
                            aws_profile: event.target.value,
                          }))
                        }
                      >
                        <option value="" disabled>
                          Choose an installed AWS profile…
                        </option>
                        {profile.aws_profile &&
                          !aws?.profiles.includes(profile.aws_profile) && (
                            <option value={profile.aws_profile}>
                              {profile.aws_profile} · saved
                            </option>
                          )}
                        {aws?.profiles.map((name) => (
                          <option key={name} value={name}>
                            {name}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label htmlFor="aws-region">AWS region</label>
                      <select
                        id="aws-region"
                        value={profile.aws_region}
                        disabled={busy}
                        onChange={(event) =>
                          setProfile((current) => ({
                            ...current,
                            aws_region: event.target.value,
                          }))
                        }
                      >
                        <option value="">Choose a region…</option>
                        {profile.aws_region &&
                          !aws?.regions.includes(profile.aws_region) && (
                            <option value={profile.aws_region}>
                              {profile.aws_region}
                            </option>
                          )}
                        {aws?.regions.map((region) => (
                          <option key={region} value={region}>
                            {region}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <details className="aws-signin-guide">
                    <summary>
                      Connect an AWS profile available to this installation
                    </summary>
                    <p>
                      {aws?.setup.message ??
                        "Your site administrator can provision an AWS profile for this installation. Host account files are not imported automatically."}
                    </p>
                    {aws?.setup.commands.map((command) => (
                      <pre key={command}>
                        <code>{command}</code>
                      </pre>
                    ))}
                    {aws && (
                      <a
                        href={aws.setup.documentation_url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        AWS sign-in instructions{" "}
                        <span aria-hidden="true">↗</span>
                      </a>
                    )}
                    <p>
                      AWS handles your sign-in. This application does not
                      collect an AWS password. Bedrock runs model planning; the
                      workspace continues to run locally.
                    </p>
                  </details>
                  <button
                    type="button"
                    className="text-action"
                    disabled={busy}
                    onClick={() =>
                      void task(async () => {
                        const next = await connectionsApi.awsProfiles();
                        if (mounted.current) {
                          setAws(next);
                          setNotice("Available AWS profiles refreshed.");
                        }
                      })
                    }
                  >
                    Refresh AWS profiles
                  </button>
                </section>
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
                      Only use this when your provider documents a model that is
                      absent from its returned list.
                    </p>
                  </details>
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
          Connection credentials are kept out of chat and session history.
          Choose whether to remember them after a restart.
        </p>
        <div className="advanced-credential-controls">
          <section className="connection-card card">
            <p className="eyebrow">CREDENTIAL STORAGE</p>
            <h2>Choose how to remember credentials.</h2>
            <p>
              Keys entered here are write-only and never placed in browser
              storage. Connection preferences are remembered separately from
              secrets. This choice applies to newly submitted model credentials.
              Research database keys use the storage option in their own card;
              saved credentials stay unchanged.
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
                    Keys are held in memory and must be re-entered after the
                    server restarts.
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
                      ? "Encrypt submitted keys on disk using the unlocked vault."
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
                  : result.target === "aws"
                    ? "AWS credentials"
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
