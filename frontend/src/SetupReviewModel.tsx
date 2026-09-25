import { useEffect, useRef, useState } from "react";
import { useConnections } from "./Connections";
import type { ConnectionFormState } from "./Connections";
import {
  connectionError,
  connectionsApi,
  providerLabels,
} from "./connectionsApi";
import type { ConnectionStatus, ModelCatalog } from "./connectionsApi";
import type { SetupStatus } from "./setupApi";

interface Props {
  disabled?: boolean;
  onStateChange: (state: ConnectionFormState) => void;
  onVerify: (saved: ConnectionStatus) => Promise<SetupStatus>;
  onManage: () => void;
}

export default function SetupReviewModel({
  disabled = false,
  onStateChange,
  onVerify,
  onManage,
}: Props) {
  const connection = useConnections();
  const status = connection.status;
  const account = status?.accounts.find(
    (item) => item.id === status.active_account_id,
  );
  const needsCredentials =
    !account || ["missing", "locked"].includes(account.credential_state);
  const [loaded, setLoaded] = useState<{
    connection: ConnectionStatus;
    catalog: ModelCatalog;
  } | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false),
    [reload, setReload] = useState(0);
  const [catalogError, setCatalogError] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false),
    [uncertain, setUncertain] = useState(false),
    [verificationFailed, setVerificationFailed] = useState(false);
  const mounted = useRef(true),
    lock = useRef(false);
  const catalog = loaded?.connection === status ? loaded.catalog : null;
  const blocked = disabled || connection.loading || connection.busy || busy;
  const changeBlocked = blocked || uncertain || Boolean(connection.error);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    onStateChange({
      busy: busy || catalogLoading,
      dirty: uncertain || verificationFailed,
    });
  }, [busy, catalogLoading, uncertain, verificationFailed, onStateChange]);
  useEffect(
    () => () => onStateChange({ busy: false, dirty: false }),
    [onStateChange],
  );
  useEffect(() => {
    setLoaded(null);
    setCatalogLoading(false);
    setCatalogError("");
    if (
      !status ||
      needsCredentials ||
      connection.loading ||
      connection.busy ||
      busy ||
      uncertain ||
      connection.error
    )
      return;
    const controller = new AbortController();
    setCatalogLoading(true);
    connectionsApi
      .models(controller.signal)
      .then((next) => {
        if (controller.signal.aborted) return;
        if (next.provider !== status.profile.provider)
          throw new Error("The model connection changed. Reload its settings.");
        setLoaded({ connection: status, catalog: next });
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setCatalogError(connectionError(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted) setCatalogLoading(false);
      });
    return () => controller.abort();
  }, [
    status,
    needsCredentials,
    connection.loading,
    connection.busy,
    busy,
    uncertain,
    connection.error,
    reload,
  ]);

  async function verify(saved: ConnectionStatus) {
    try {
      const next = await onVerify(saved);
      // Never report a successful check for a different account or model.
      if (
        next.model.account_id !== saved.active_account_id ||
        next.model.provider !== saved.profile.provider ||
        next.model.model !== saved.profile.model
      )
        throw new Error("Model connection changed during verification.");
      if (mounted.current) {
        setVerificationFailed(!next.can_research);
        setNotice(
          next.can_research
            ? `${saved.profile.model} is selected and ready.`
            : `Model saved. ${next.model.message}`,
        );
      }
    } catch {
      if (mounted.current) {
        setVerificationFailed(true);
        setNotice(
          "Model saved, but its connection check did not complete. Retry the check before finishing setup.",
        );
      }
    }
  }
  async function choose(model: string) {
    if (
      changeBlocked ||
      lock.current ||
      catalogLoading ||
      !account ||
      needsCredentials ||
      model === account.profile.model ||
      !catalog?.models.some((item) => item.id === model)
    )
      return;
    lock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    setVerificationFailed(false);
    setLoaded(null);
    try {
      await connection.apply(async () => {
        const saved = await connectionsApi.saveAccount(
          {
            label: account.label,
            profile: { ...account.profile, model },
            secret_storage:
              account.credential_state === "encrypted"
                ? "encrypted"
                : "session",
          },
          account.id,
        );
        await verify(saved);
        return saved;
      });
    } catch (failure) {
      if (mounted.current) {
        setError(connectionError(failure));
        setUncertain(true);
      }
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function retry() {
    if (changeBlocked || catalogLoading || lock.current || !status) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await verify(status);
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function reloadSaved() {
    if (blocked || lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setLoaded(null);
    try {
      const saved = await connection.reload();
      if (mounted.current) {
        setUncertain(false);
        setVerificationFailed(false);
        setNotice("Saved connection reloaded.");
      }
      await verify(saved);
    } catch (failure) {
      if (mounted.current) setError(connectionError(failure));
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <section
      className="setup-review-model"
      aria-label="Research model"
      aria-busy={busy}
    >
      <span>Research model</span>
      <strong>
        {status?.profile.provider && status.profile.provider !== "none"
          ? providerLabels[status.profile.provider]
          : "Not connected"}
      </strong>
      <div className="setup-model-picker-heading">
        <label htmlFor="setup-review-model">Active model</label>
        <button
          type="button"
          className="text-action"
          disabled={changeBlocked || catalogLoading || needsCredentials}
          onClick={() => setReload((value) => value + 1)}
        >
          {catalogLoading ? "Loading models…" : "Refresh models"}
        </button>
      </div>
      <select
        id="setup-review-model"
        value={account?.profile.model ?? ""}
        disabled={
          changeBlocked ||
          catalogLoading ||
          needsCredentials ||
          !catalog?.models.length
        }
        onChange={(event) => void choose(event.target.value)}
      >
        <option value="">
          {catalogLoading
            ? "Loading available models…"
            : needsCredentials
              ? "Connect your account first…"
              : "Choose a model…"}
        </option>
        {account?.profile.model &&
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
      <p className="field-help" role="status">
        {busy
          ? "Saving selection and checking the connection…"
          : notice ||
            (needsCredentials
              ? "Connect or unlock this account to choose an available model."
              : catalogLoading
                ? "Loading the models available to this account…"
                : catalog && !catalog.models.length
                  ? "No models were returned. Refresh models or check the connection."
                  : "Choose a model to save and verify it here. Existing reports stay unchanged.")}
      </p>
      {catalogError && (
        <p className="connection-error-text" role="alert">
          Could not load available models. Use Refresh models to try again.
        </p>
      )}
      {(error || connection.error) && (
        <p className="connection-error-text" role="alert">
          {error || connection.error}
        </p>
      )}
      {uncertain || connection.error ? (
        <button
          type="button"
          className="quiet-button"
          disabled={blocked}
          onClick={() => void reloadSaved()}
        >
          Reload saved connection
        </button>
      ) : (
        verificationFailed && (
          <button
            type="button"
            className="quiet-button"
            disabled={blocked || catalogLoading}
            onClick={() => void retry()}
          >
            Retry connection check
          </button>
        )
      )}
      <button
        type="button"
        className="text-action setup-change-connection"
        disabled={
          blocked || catalogLoading || uncertain || Boolean(connection.error)
        }
        onClick={onManage}
      >
        Change connection
      </button>
    </section>
  );
}
