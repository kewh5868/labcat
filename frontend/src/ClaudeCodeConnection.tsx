import { useEffect, useRef, useState } from "react";
import { useConnections } from "./Connections";
import {
  claudeCodeLoginCommand,
  connectionError,
  connectionsApi,
} from "./connectionsApi";
import type { ClaudeCodeStatus } from "./connectionsApi";

export default function ClaudeCodeConnection({
  accountId,
  disabled,
  onPrepare,
}: {
  accountId: string;
  disabled: boolean;
  onPrepare: () => void;
}) {
  const connection = useConnections();
  const [status, setStatus] = useState<ClaudeCodeStatus | null>(null);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState("");
  const [copyNotice, setCopyNotice] = useState("");
  const mounted = useRef(true);
  const actionLock = useRef(false);
  const command = claudeCodeLoginCommand(accountId);
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    if (accountId) {
      setReading(true);
      connectionsApi
        .claudeCodeStatus(accountId, controller.signal)
        .then((next) => {
          if (!controller.signal.aborted) setStatus(next);
        })
        .catch((reason: unknown) => {
          if (!controller.signal.aborted) setError(connectionError(reason));
        })
        .finally(() => {
          if (!controller.signal.aborted) setReading(false);
        });
    }
    return () => {
      mounted.current = false;
      controller.abort();
    };
  }, [accountId]);
  const blocked = disabled || reading || connection.busy || connection.loading;
  async function copyCommand() {
    if (!command) return;
    try {
      if (!navigator.clipboard?.writeText)
        throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(command);
      if (mounted.current)
        setCopyNotice("Command copied. Paste it into your terminal.");
    } catch {
      if (mounted.current)
        setCopyNotice(
          "Clipboard access is unavailable. Select and copy the command above manually.",
        );
    }
  }
  async function check(endSession = false) {
    if (blocked || actionLock.current || !accountId) return;
    actionLock.current = true;
    setReading(true);
    setError("");
    try {
      await connection.apply(async () => {
        const next = endSession
          ? await connectionsApi.claudeCodeLogout(accountId)
          : await connectionsApi.claudeCodeStatus(accountId);
        if (mounted.current) setStatus(next);
        return connectionsApi.status();
      });
    } catch (reason: unknown) {
      if (mounted.current) setError(connectionError(reason));
    } finally {
      actionLock.current = false;
      if (mounted.current) setReading(false);
    }
  }
  return (
    <section
      className="agent-sign-in claude-code-sign-in"
      aria-label="Claude Code account sign-in"
    >
      <h3>Claude Code account sign-in</h3>
      <p>
        The native Claude Code terminal handles authentication. Labcat never
        asks for your Claude password, sign-in code or tokens. The credential
        vault is not used for this connection.
      </p>
      {!accountId ? (
        <>
          <p>Save this account to get its terminal sign-in command.</p>
          <button
            className="quiet-button"
            type="button"
            disabled={blocked}
            onClick={onPrepare}
          >
            Set up Claude Code sign-in
          </button>
        </>
      ) : (
        <>
          <p role="status">
            {reading
              ? "Checking native sign-in status…"
              : status?.signed_in
                ? "Signed in to Claude Code."
                : status?.available
                  ? "Claude Code is available. Complete terminal sign-in for this account."
                  : status
                    ? "Claude Code is unavailable. Update or rebuild the Labcat Docker image, or ask your administrator to check the worker installation."
                    : "Check native sign-in status to continue."}
          </p>
          <h4>Sign in or reconnect in your terminal</h4>
          {command ? (
            <>
              <p>From the Labcat repository folder, run:</p>
              <pre className="claude-code-command">
                <code>{command}</code>
              </pre>
              <button
                className="quiet-button"
                type="button"
                disabled={disabled}
                onClick={() => void copyCommand()}
              >
                Copy sign-in command
              </button>
              {copyNotice && (
                <p className="field-help" role="status">
                  {copyNotice}
                </p>
              )}
              <p>
                Follow the native terminal instructions. It may open a browser
                or display a sign-in URL and request a code. Enter that code
                only in the native terminal, never in Labcat. Then check sign-in
                status below.
              </p>
            </>
          ) : (
            <p>
              Reload Connections to obtain a valid saved account before terminal
              sign-in.
            </p>
          )}
          <div className="connection-inline-actions">
            <button
              className="quiet-button"
              type="button"
              disabled={blocked}
              onClick={() => void check()}
            >
              Check Claude Code sign-in
            </button>
            {status?.signed_in && (
              <button
                className="text-action"
                type="button"
                disabled={blocked}
                onClick={() => void check(true)}
              >
                End Claude Code session
              </button>
            )}
          </div>
        </>
      )}
      <p className="field-help">
        Status checks inspect native sign-in metadata without running inference.
        They do not verify model entitlement. Claude Code aliases are default,
        sonnet and haiku. Research requires consent and may use your provider
        allowance or incur charges. This session ends when the worker container
        restarts; reconnect with the same command.
      </p>
      {error && (
        <p className="connection-error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
