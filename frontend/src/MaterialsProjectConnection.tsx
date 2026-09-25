import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useConnections } from "./Connections";
import { connectionError, connectionsApi } from "./connectionsApi";
import "./materialsProjectConnection.css";

export default function MaterialsProjectConnection({
  disabled = false,
  onCredentialOptions,
  onStateChange,
}: {
  disabled?: boolean;
  onCredentialOptions: () => void;
  onStateChange: (state: { dirty: boolean; busy: boolean }) => void;
}) {
  const connection = useConnections();
  const { status } = connection;
  const keyId = useId();
  const [key, setKey] = useState("");
  const credentialState = status?.credentials.materials_project ?? "missing";
  const savedEncrypted =
    credentialState === "encrypted" || credentialState === "locked";
  const [remember, setRemember] = useState(savedEncrypted);
  const [phase, setPhase] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const lock = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    setRemember(savedEncrypted);
  }, [savedEncrypted]);
  const dirty = Boolean(key) || remember !== savedEncrypted;
  const working = Boolean(phase);
  const busy = working || disabled || connection.busy || connection.loading;
  const vaultReady = Boolean(status?.vault.available && !status.vault.locked);
  const needsVault = (remember || credentialState === "locked") && !vaultReady;
  const hasKey = Boolean(key) || credentialState !== "missing";
  useEffect(() => {
    onStateChange({ dirty, busy: working });
  }, [dirty, working, onStateChange]);
  useEffect(
    () => () => onStateChange({ dirty: false, busy: false }),
    [onStateChange],
  );

  async function verify(event: FormEvent) {
    event.preventDefault();
    if (busy || lock.current || needsVault || !hasKey) return;
    lock.current = true;
    setError("");
    setNotice("");
    const enteredKey = key;
    setKey("");
    setPhase(dirty ? "Saving key…" : "Verifying connection…");
    try {
      await connection.apply(async () => {
        if (dirty)
          await connectionsApi.saveMaterialsProject({
            secret_storage: remember ? "encrypted" : "session",
            ...(enteredKey ? { api_key: enteredKey } : {}),
          });
        if (mounted.current) setPhase("Verifying connection…");
        const result = await connectionsApi.test("materials_project");
        if (mounted.current) {
          if (result.status === "ok")
            setNotice(
              "Verified. Add Materials Project to your research in Search Criterion.",
            );
          else setError(result.message);
        }
        return connectionsApi.status();
      });
    } catch (error) {
      if (mounted.current) setError(connectionError(error));
      // A key may have saved successfully before a verification request failed.
      await connection.reload().catch(() => undefined);
    } finally {
      lock.current = false;
      if (mounted.current) setPhase("");
    }
  }
  async function forget() {
    if (busy || lock.current) return;
    lock.current = true;
    setKey("");
    setPhase("Removing key…");
    setError("");
    setNotice("");
    try {
      await connection.apply(() =>
        connectionsApi.saveMaterialsProject({ forget: true }),
      );
      if (mounted.current) {
        setRemember(false);
        setNotice("Materials Project key removed.");
      }
    } catch (error) {
      if (mounted.current) setError(connectionError(error));
    } finally {
      lock.current = false;
      if (mounted.current) setPhase("");
    }
  }
  const verified =
    status?.source_connections?.materials_project.selectable && !key;
  return (
    <article
      className="selected-public-source materials-project-connection"
      aria-label="Materials Project connection"
    >
      <div className="selected-source-heading">
        <h3>Materials Project</h3>
        <span>
          {verified
            ? "Verified"
            : credentialState === "locked"
              ? "Unlock to verify"
              : credentialState === "missing" && !key
                ? "Optional · API key required"
                : "Verification required"}
        </span>
      </div>
      <p>
        Crystal structures and computed material properties from the public
        database.
      </p>
      <div className="selected-source-actions">
        <a
          href="https://next-gen.materialsproject.org/"
          target="_blank"
          rel="noopener noreferrer"
        >
          Visit database <span aria-hidden="true">↗</span>
        </a>
        <a
          href="https://next-gen.materialsproject.org/api"
          target="_blank"
          rel="noopener noreferrer"
        >
          Register or get an API key <span aria-hidden="true">↗</span>
        </a>
      </div>
      <form onSubmit={(event) => void verify(event)}>
        <label htmlFor={keyId}>API key</label>
        <input
          id={keyId}
          type="password"
          autoComplete="off"
          spellCheck={false}
          maxLength={4096}
          value={key}
          disabled={busy}
          placeholder={
            credentialState === "missing"
              ? "Enter an API key to connect"
              : "Leave blank to use your saved key"
          }
          onChange={(event) => {
            setKey(event.target.value);
            setError("");
            setNotice("");
          }}
        />
        <label className="source-remember-key">
          <input
            type="checkbox"
            checked={remember}
            disabled={busy}
            onChange={(event) => {
              setRemember(event.target.checked);
              setNotice("");
            }}
          />
          <span>Remember key securely between sessions</span>
        </label>
        <p className="source-storage-note">
          {remember
            ? "Encrypted in your local vault. Unlock it after restarting."
            : "This session only. Keys stay out of chat and session history."}
        </p>
        {needsVault && (
          <p className="source-vault-prompt">
            {credentialState === "locked"
              ? "Unlock the vault before using or replacing this saved key."
              : "Create or unlock your local vault to remember this key."}{" "}
            <button
              className="text-action"
              type="button"
              disabled={busy}
              onClick={onCredentialOptions}
            >
              {status?.vault.can_create
                ? "Set up secure storage"
                : "Unlock secure storage"}
            </button>
          </p>
        )}
        <div className="source-key-actions">
          <button
            className="quiet-button"
            type="submit"
            disabled={busy || needsVault || !hasKey}
          >
            {phase || (dirty ? "Save and verify" : "Verify connection")}
          </button>
          {credentialState !== "missing" && (
            <button
              className="text-action"
              type="button"
              disabled={busy || credentialState === "locked"}
              onClick={() => void forget()}
            >
              Forget key
            </button>
          )}
        </div>
        {error && (
          <p className="source-key-error" role="alert">
            {error}
          </p>
        )}
        {notice && (
          <p className="source-key-notice" role="status">
            {notice}
          </p>
        )}
        {working && (
          <span className="sr-only" role="status">
            {phase}
          </span>
        )}
      </form>
    </article>
  );
}
