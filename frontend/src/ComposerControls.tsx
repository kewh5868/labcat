import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { createPortal } from "react-dom";
import { useConnections } from "./Connections";
import RankingProfileHelp from "./RankingProfileHelp";
import {
  connectionError,
  connectionsApi,
  isCloudProvider,
  providerLabels,
} from "./connectionsApi";
import type {
  ConnectionStatus,
  ModelAccount,
  ModelCatalog,
} from "./connectionsApi";
import { rankingProfilesApi } from "./rankingProfilesApi";
import type { RankingProfiles } from "./rankingProfilesApi";
import { AccountUsageView } from "./AgentConnections";
import { useSetup } from "./SetupWizard";
import { setupApi } from "./setupApi";
import "./composerControls.css";

interface ComposerControlsProps {
  children?: ReactNode;
  rankingProfileId: string;
  onRankingProfileChange: (id: string) => void;
  disabled: boolean;
  onOpenSettings: () => void;
  onOpenConnections: () => void;
}
type Picker = "ranking" | "model";

function needsCredentials(account: ModelAccount) {
  return (
    account.credential_state === "locked" ||
    account.credential_state === "missing"
  );
}

export default function ComposerControls({
  children,
  rankingProfileId,
  onRankingProfileChange,
  disabled,
  onOpenSettings,
  onOpenConnections,
}: ComposerControlsProps) {
  const connection = useConnections();
  const setup = useSetup();
  const id = useId();
  const [picker, setPicker] = useState<Picker | null>(null);
  const [profiles, setProfiles] = useState<RankingProfiles | null>(null);
  const [rankingLoading, setRankingLoading] = useState(false);
  const [rankingError, setRankingError] = useState("");
  const [rankingReload, setRankingReload] = useState(0);
  const [search, setSearch] = useState("");
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [modelBusy, setModelBusy] = useState(false);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogReload, setCatalogReload] = useState(0);
  const [verificationFailed, setVerificationFailed] = useState(false);
  const [modelError, setModelError] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const [notice, setNotice] = useState("");
  const [position, setPosition] = useState<CSSProperties>({
    visibility: "hidden",
  });
  const controls = useRef<HTMLDivElement>(null);
  const rankingButton = useRef<HTMLButtonElement>(null);
  const modelButton = useRef<HTMLButtonElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  const mounted = useRef(true);
  const operationLock = useRef(false);
  const catalogEpoch = useRef(0);
  const status = connection.status;
  const account = status?.accounts.find(
    (item) => item.id === status.active_account_id,
  );
  const providerAccounts = status
    ? [account, ...status.accounts]
        .filter((item): item is ModelAccount => Boolean(item))
        .filter(
          (item, index, accounts) =>
            item.profile.provider !== "none" &&
            accounts.findIndex(
              (other) => other.profile.provider === item.profile.provider,
            ) === index,
        )
    : [];
  const blocked =
    disabled ||
    connection.loading ||
    connection.busy ||
    modelBusy ||
    setup.busy;
  const changeBlocked =
    blocked || uncertain || Boolean(connection.error) || !status;
  const currentProfile = profiles?.profiles.find(
    (item) => item.id === rankingProfileId,
  );
  const profileLabel =
    rankingProfileId === "infer"
      ? "Infer from prompt"
      : (currentProfile?.name ?? "Ranking profile");
  const modelLabel = connection.loading
    ? "Loading models…"
    : !status || status.profile.provider === "none"
      ? "Connect model"
      : status.profile.model ||
        `${providerLabels[status.profile.provider]} · choose model`;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      catalogEpoch.current++;
    };
  }, []);
  useEffect(() => {
    if (disabled) setPicker(null);
  }, [disabled]);
  // A saved account can keep its identity/model while its credentials, local
  // endpoint or AWS profile change. Never reuse that connection's old catalog.
  useLayoutEffect(() => {
    setCatalog(null);
    catalogEpoch.current++;
  }, [status]);
  useEffect(() => {
    const epoch = ++catalogEpoch.current;
    setCatalog(null);
    setCatalogLoading(false);
    if (
      picker !== "model" ||
      !account ||
      needsCredentials(account) ||
      changeBlocked
    )
      return;
    const controller = new AbortController();
    setCatalogLoading(true);
    setModelError("");
    connectionsApi
      .models(controller.signal)
      .then((next) => {
        if (controller.signal.aborted || epoch !== catalogEpoch.current) return;
        if (next.provider !== account.profile.provider)
          throw new Error(
            "Connection model list changed. Reload connection settings.",
          );
        setCatalog(next);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted && epoch === catalogEpoch.current)
          setModelError(connectionError(error));
      })
      .finally(() => {
        if (!controller.signal.aborted && epoch === catalogEpoch.current)
          setCatalogLoading(false);
      });
    return () => {
      controller.abort();
      catalogEpoch.current++;
    };
  }, [picker, status, changeBlocked, catalogReload]);
  useEffect(() => {
    // New composers stay lazy. Restored explicit choices need their saved label
    // even before the scientist opens the picker.
    if (
      picker !== "ranking" &&
      (rankingProfileId === "infer" || profiles !== null)
    )
      return;
    const controller = new AbortController();
    setRankingLoading(true);
    setRankingError("");
    rankingProfilesApi
      .list(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setProfiles(value);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setRankingError(
            error instanceof Error && error.message.startsWith("The ranking")
              ? error.message
              : "Saved ranking profiles could not be loaded.",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setRankingLoading(false);
      });
    return () => controller.abort();
  }, [picker, rankingReload, rankingProfileId]);

  useLayoutEffect(() => {
    if (!picker) return;
    const anchor =
      picker === "ranking" ? rankingButton.current : modelButton.current;
    function place() {
      if (!anchor) return;
      const rect = anchor.getBoundingClientRect();
      const width = Math.min(380, window.innerWidth - 24);
      const above = rect.top - 20;
      const below = window.innerHeight - rect.bottom - 20;
      const useAbove = above >= 260 || above >= below;
      setPosition({
        width,
        left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)),
        ...(useAbove
          ? { bottom: Math.max(12, window.innerHeight - rect.top + 8) }
          : { top: Math.max(12, rect.bottom + 8) }),
        maxHeight: Math.max(
          1,
          Math.min(
            510,
            window.innerHeight - 24,
            Math.max(100, useAbove ? above : below),
          ),
        ),
      });
    }
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    popup.current?.querySelector<HTMLElement>("input, button")?.focus();
    function outside(event: PointerEvent) {
      if (
        event.target instanceof Node &&
        !popup.current?.contains(event.target) &&
        !controls.current?.contains(event.target)
      )
        setPicker(null);
    }
    function keyboard(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setPicker(null);
        anchor?.focus();
      }
    }
    function leave(event: FocusEvent) {
      if (
        event.target instanceof Node &&
        !popup.current?.contains(event.target) &&
        !controls.current?.contains(event.target)
      )
        setPicker(null);
    }
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", keyboard);
    document.addEventListener("focusin", leave);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", keyboard);
      document.removeEventListener("focusin", leave);
    };
  }, [picker]);

  function toggle(next: Picker) {
    if (disabled || (next === "model" && blocked)) return;
    setSearch("");
    setPicker((current) => (current === next ? null : next));
  }
  function selectProfile(next: string) {
    if (disabled || rankingLoading || rankingError) return;
    onRankingProfileChange(next);
    setPicker(null);
    rankingButton.current?.focus();
  }
  function manage(destination: "settings" | "connections") {
    if (disabled || modelBusy || connection.busy) return;
    if (destination === "connections" && (uncertain || connection.error))
      return;
    setPicker(null);
    if (destination === "settings") onOpenSettings();
    else onOpenConnections();
  }
  async function changeModel(
    operation: () => Promise<ConnectionStatus>,
    openSetup = false,
  ) {
    if (changeBlocked || catalogLoading || operationLock.current) return;
    operationLock.current = true;
    setModelBusy(true);
    setModelError("");
    setNotice("");
    setVerificationFailed(false);
    setCatalog(null);
    catalogEpoch.current++;
    try {
      let savedNotice = "Model connection saved.";
      await connection.apply(async () => {
        const next = await operation();
        const active = next.accounts.find(
          (item) => item.id === next.active_account_id,
        );
        if (
          active &&
          !needsCredentials(active) &&
          (!isCloudProvider(active.profile.provider) ||
            active.profile.allow_paid_inference)
        ) {
          savedNotice = await checkReadiness(next);
        } else if (
          active &&
          isCloudProvider(active.profile.provider) &&
          !active.profile.allow_paid_inference
        ) {
          savedNotice =
            "Model saved. Cloud planning stays paused until you enable consent in Connections.";
        }
        return next;
      });
      if (mounted.current) {
        setNotice(savedNotice);
        if (openSetup) {
          setPicker(null);
          onOpenConnections();
        }
      }
    } catch (error) {
      if (mounted.current) {
        setModelError(connectionError(error));
        setUncertain(true);
      }
    } finally {
      operationLock.current = false;
      if (mounted.current) setModelBusy(false);
    }
  }
  async function reloadConnection() {
    if (blocked || operationLock.current) return;
    operationLock.current = true;
    setModelBusy(true);
    setModelError("");
    setNotice("");
    setCatalog(null);
    catalogEpoch.current++;
    try {
      await connection.reload();
      if (mounted.current) {
        setUncertain(false);
        setVerificationFailed(false);
        setNotice("Saved model connection reloaded.");
      }
    } catch (error) {
      if (mounted.current) setModelError(connectionError(error));
    } finally {
      operationLock.current = false;
      if (mounted.current) setModelBusy(false);
    }
  }
  async function checkReadiness(saved: ConnectionStatus) {
    try {
      const next = await setup.apply(async () => {
        const verified = await setupApi.verify();
        if (
          verified.model.account_id !== saved.active_account_id ||
          verified.model.provider !== saved.profile.provider ||
          verified.model.model !== saved.profile.model
        ) {
          throw new Error("Connection changed while verifying the model.");
        }
        return verified;
      });
      if (mounted.current) setVerificationFailed(!next.can_research);
      return next.can_research
        ? `${saved.profile.model} is active and ready for your next request.`
        : `Model saved. ${next.model.message}`;
    } catch {
      if (mounted.current) setVerificationFailed(true);
      return "Model saved, but the connection check did not complete. Retry the connection check before sending a request.";
    }
  }
  async function retryVerification() {
    if (changeBlocked || catalogLoading || operationLock.current || !status)
      return;
    operationLock.current = true;
    setModelBusy(true);
    setNotice("");
    try {
      const next = await checkReadiness(status);
      if (mounted.current) setNotice(next);
    } finally {
      operationLock.current = false;
      if (mounted.current) setModelBusy(false);
    }
  }
  function chooseModel(model: string) {
    if (
      !account ||
      !catalog?.models.some((item) => item.id === model) ||
      model === account.profile.model
    )
      return;
    void changeModel(() =>
      connectionsApi.saveAccount(
        {
          label: account.label,
          profile: { ...account.profile, model },
          secret_storage:
            account.credential_state === "encrypted" ? "encrypted" : "session",
        },
        account.id,
      ),
    );
  }
  const filteredProfiles =
    profiles?.profiles.filter((profile) =>
      `${profile.name} ${profile.material_class} ${profile.application}`
        .toLowerCase()
        .includes(search.trim().toLowerCase()),
    ) ?? [];

  return (
    <div className="composer-controls" ref={controls}>
      <button
        ref={rankingButton}
        type="button"
        className="composer-picker-button composer-ranking-button"
        aria-label={`Ranking profile: ${profileLabel}`}
        aria-haspopup="dialog"
        aria-expanded={picker === "ranking"}
        aria-controls={picker === "ranking" ? `${id}-ranking` : undefined}
        title={`Ranking profile: ${profileLabel}`}
        disabled={disabled}
        onClick={() => toggle("ranking")}
      >
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <path d="M4 4v12M10 4v12M16 4v12M2 8h4M8 13h4M14 6h4" />
        </svg>
        <span>{profileLabel}</span>
        <span className="composer-picker-chevron" aria-hidden="true">
          ⌄
        </span>
      </button>
      <button
        ref={modelButton}
        type="button"
        className="composer-picker-button composer-model-button"
        aria-label={`Language model: ${modelLabel}`}
        aria-haspopup="dialog"
        aria-expanded={picker === "model"}
        aria-controls={picker === "model" ? `${id}-model` : undefined}
        title={modelLabel}
        disabled={blocked}
        onClick={() => toggle("model")}
      >
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <path d="m10 2 2.2 5.8L18 10l-5.8 2.2L10 18l-2.2-5.8L2 10l5.8-2.2Z" />
        </svg>
        <span>{modelLabel}</span>
        <span className="composer-picker-chevron" aria-hidden="true">
          ⌄
        </span>
      </button>
      {children}
      {picker &&
        createPortal(
          <div
            ref={popup}
            id={`${id}-${picker}`}
            className={`composer-picker-popover composer-${picker}-popover`}
            style={position}
            role="dialog"
            aria-label={
              picker === "ranking"
                ? "Choose a ranking profile"
                : "Choose a language model"
            }
          >
            <header>
              <div>
                <p className="composer-picker-eyebrow">
                  {picker === "ranking" ? "THIS REQUEST" : "MODEL CONNECTION"}
                </p>
                {picker === "ranking" ? (
                  <RankingProfileHelp compact>
                    <h2>Ranking profiles</h2>
                  </RankingProfileHelp>
                ) : (
                  <h2>Language model</h2>
                )}
              </div>
              <button
                type="button"
                className="composer-popup-close"
                aria-label="Close selector"
                onClick={() => {
                  setPicker(null);
                  (picker === "ranking"
                    ? rankingButton
                    : modelButton
                  ).current?.focus();
                }}
              >
                ×
              </button>
            </header>
            {picker === "ranking" ? (
              <>
                <p className="composer-picker-help">
                  Match the question to saved profiles; use the workspace
                  default when there is no clear match. Or choose a profile
                  below.
                </p>
                <button
                  type="button"
                  className="composer-choice"
                  aria-pressed={rankingProfileId === "infer"}
                  disabled={disabled || rankingLoading || Boolean(rankingError)}
                  onClick={() => selectProfile("infer")}
                >
                  <span>
                    <strong>Infer from prompt</strong>
                    <small>Automatic · default</small>
                  </span>
                  <span aria-hidden="true">
                    {rankingProfileId === "infer" ? "✓" : ""}
                  </span>
                </button>
                <label className="sr-only" htmlFor={`${id}-profile-search`}>
                  Find ranking profiles
                </label>
                <input
                  id={`${id}-profile-search`}
                  className="composer-profile-search"
                  type="search"
                  placeholder="Find ranking profiles…"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  disabled={disabled || rankingLoading}
                />
                {rankingLoading && (
                  <p className="composer-picker-help" role="status">
                    Loading ranking profiles…
                  </p>
                )}
                {rankingError && (
                  <div className="composer-picker-error" role="alert">
                    <p>{rankingError}</p>
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() => setRankingReload((current) => current + 1)}
                    >
                      Reload ranking profiles
                    </button>
                  </div>
                )}
                {!rankingLoading && !rankingError && (
                  <div className="composer-profile-list">
                    {filteredProfiles.map((profile) => (
                      <button
                        key={profile.id}
                        type="button"
                        className="composer-choice"
                        aria-pressed={rankingProfileId === profile.id}
                        disabled={disabled}
                        onClick={() => selectProfile(profile.id)}
                      >
                        <span>
                          <strong>{profile.name}</strong>
                          <small>
                            {profile.preset ? "Preset" : "Custom"}
                            {profiles?.active_profile_id === profile.id
                              ? " · Active in Search Criterion"
                              : ""}
                          </small>
                        </span>
                        <span aria-hidden="true">
                          {rankingProfileId === profile.id ? "✓" : ""}
                        </span>
                      </button>
                    ))}
                    {filteredProfiles.length === 0 && (
                      <p className="composer-picker-help">
                        No matching ranking profiles.
                      </p>
                    )}
                  </div>
                )}
                <footer>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => manage("settings")}
                  >
                    Manage in Search Criterion{" "}
                    <span aria-hidden="true">↗</span>
                  </button>
                </footer>
              </>
            ) : (
              <>
                <p className="composer-picker-help">
                  Your selection applies to new requests in this workspace.
                </p>
                <div className="composer-account-list">
                  {providerAccounts.map((saved) => (
                    <button
                      key={saved.id}
                      type="button"
                      className="composer-choice"
                      aria-pressed={status?.active_account_id === saved.id}
                      disabled={changeBlocked || catalogLoading}
                      onClick={() => {
                        if (saved.id === status?.active_account_id) {
                          if (needsCredentials(saved)) manage("connections");
                        } else
                          void changeModel(
                            () => connectionsApi.selectAccount(saved.id),
                            needsCredentials(saved),
                          );
                      }}
                    >
                      <span>
                        <strong>
                          {providerLabels[saved.profile.provider]}
                        </strong>
                        <small>
                          {saved.profile.model || "Choose a model"}
                          {saved.credential_state === "locked"
                            ? " · Unlock credentials"
                            : saved.credential_state === "missing"
                              ? saved.profile.provider === "chatgpt"
                                ? " · Sign in"
                                : " · Add API key"
                              : ""}
                        </small>
                      </span>
                      <span aria-hidden="true">
                        {status?.active_account_id === saved.id ? "✓" : ""}
                      </span>
                    </button>
                  ))}
                </div>
                {account && (
                  <section
                    className="composer-active-model"
                    aria-busy={catalogLoading || modelBusy}
                  >
                    <div className="composer-model-heading">
                      <label htmlFor={`${id}-model-choice`}>Active model</label>
                      <button
                        type="button"
                        disabled={
                          changeBlocked ||
                          catalogLoading ||
                          needsCredentials(account)
                        }
                        onClick={() => setCatalogReload((value) => value + 1)}
                      >
                        {catalogLoading ? "Loading models…" : "Refresh models"}
                      </button>
                    </div>
                    <select
                      id={`${id}-model-choice`}
                      value={account.profile.model}
                      disabled={
                        changeBlocked ||
                        catalogLoading ||
                        !catalog?.models.length ||
                        needsCredentials(account)
                      }
                      onChange={(event) => chooseModel(event.target.value)}
                    >
                      <option value="">
                        {catalogLoading
                          ? "Loading available models…"
                          : "Choose a model…"}
                      </option>
                      {account.profile.model &&
                        !catalog?.models.some(
                          (item) => item.id === account.profile.model,
                        ) && (
                          <option value={account.profile.model}>
                            {account.profile.model} · current
                          </option>
                        )}
                      {catalog?.models.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                    {catalog && (
                      <p className="composer-picker-help">{catalog.message}</p>
                    )}
                    {needsCredentials(account) ? (
                      <button
                        className="composer-setup-link"
                        type="button"
                        disabled={
                          blocked || uncertain || Boolean(connection.error)
                        }
                        onClick={() => manage("connections")}
                      >
                        {account.credential_state === "locked"
                          ? "Unlock credentials in Connections"
                          : account.profile.provider === "chatgpt"
                            ? "Sign in with ChatGPT in Connections"
                            : "Add this account’s key in Connections"}
                      </button>
                    ) : (
                      <p className="composer-picker-help" role="status">
                        {modelBusy
                          ? "Saving selection and checking the connection…"
                          : catalogLoading
                            ? "Loading this account’s available models…"
                            : catalog && !catalog.models.length
                              ? "No models were returned. Refresh the list or check this account in Connections."
                              : "Choose a model to save it here. Existing reports keep the model they used."}
                      </p>
                    )}
                    {isCloudProvider(account.profile.provider) &&
                      !account.profile.allow_paid_inference && (
                        <p className="composer-model-paused">
                          Cloud planning is paused. Review consent in
                          Connections to enable it.
                        </p>
                      )}
                  </section>
                )}
                {account && <AccountUsageView compact />}
                {(modelError || connection.error) && (
                  <div className="composer-picker-error" role="alert">
                    <p>{modelError || connection.error}</p>
                    {(uncertain || connection.error) && (
                      <p>
                        Reload the saved connection before making another
                        change.
                      </p>
                    )}
                  </div>
                )}
                {(uncertain || connection.error || !status) && (
                  <button
                    type="button"
                    className="composer-setup-link"
                    disabled={blocked}
                    onClick={() => void reloadConnection()}
                  >
                    Reload saved connection
                  </button>
                )}
                {notice && (
                  <p className="composer-picker-notice" role="status">
                    {notice}
                  </p>
                )}
                {verificationFailed && (
                  <button
                    type="button"
                    className="composer-setup-link"
                    disabled={changeBlocked || catalogLoading}
                    onClick={() => void retryVerification()}
                  >
                    Retry connection check
                  </button>
                )}
                <footer>
                  <button
                    type="button"
                    disabled={blocked || uncertain || Boolean(connection.error)}
                    onClick={() => manage("connections")}
                  >
                    Connect or manage providers{" "}
                    <span aria-hidden="true">↗</span>
                  </button>
                </footer>
              </>
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}
