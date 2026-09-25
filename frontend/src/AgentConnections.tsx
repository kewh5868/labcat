import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useConnections } from "./Connections";
import {
  connectionError,
  connectionsApi,
  providerLabels,
} from "./connectionsApi";
import type {
  AccountUsage,
  AgentRuntime,
  LoginFlow,
  ResearchPlan,
  UsageWindow,
} from "./connectionsApi";
import "./agentConnections.css";

function percent(value: number | null) {
  return value === null ? "Unavailable" : `${Math.round(value)}%`;
}
function resetTime(value: number | null) {
  if (value === null) return "Reset time unavailable";
  const date = new Date(value * 1000);
  return Number.isNaN(date.valueOf())
    ? "Reset time unavailable"
    : `Resets ${date.toLocaleString()}`;
}
function WindowUsage({
  window,
  label,
}: {
  window: UsageWindow;
  label: string;
}) {
  const duration =
    window.window_minutes === null
      ? "Window length unavailable"
      : window.window_minutes >= 60 && window.window_minutes % 60 === 0
        ? `${window.window_minutes / 60} hours`
        : `${window.window_minutes} minutes`;
  return (
    <div className="agent-usage-window">
      <div>
        <strong>{label}</strong>
        <span>{percent(window.remaining_percent)} remaining</span>
      </div>
      {window.remaining_percent !== null && (
        <progress
          value={window.remaining_percent}
          max={100}
          aria-label={`${label} remaining allowance`}
        />
      )}
      <small>
        {duration} · {resetTime(window.resets_at)}
      </small>
    </div>
  );
}
function TokenActivity({ values }: { values: Record<string, unknown> | null }) {
  const fields = [
    ["input_tokens", "Input tokens"],
    ["output_tokens", "Output tokens"],
    ["total_tokens", "Total tokens"],
    ["cache_read_input_tokens", "Cache read tokens"],
    ["cache_write_input_tokens", "Cache write tokens"],
    ["lifetimeTokens", "Lifetime tokens"],
  ] as const;
  const available = fields.filter(
    ([field]) =>
      typeof values?.[field] === "number" &&
      Number.isFinite(values[field]) &&
      Number(values[field]) >= 0,
  );
  return available.length ? (
    <dl className="agent-token-counts">
      {available.map(([field, label]) => (
        <div key={field}>
          <dt>{label}</dt>
          <dd>{Number(values?.[field]).toLocaleString()}</dd>
        </div>
      ))}
    </dl>
  ) : (
    <p className="field-help">
      Token counts are unavailable for this connection or run.
    </p>
  );
}

export function AccountUsageView({ compact = false }: { compact?: boolean }) {
  const connection = useConnections();
  const [usage, setUsage] = useState<AccountUsage | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(true);
  const epoch = useRef(0);
  const lock = useRef(false);
  const accountId = connection.status?.active_account_id;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      epoch.current++;
    };
  }, []);
  useLayoutEffect(() => {
    setUsage(null);
    setError("");
    epoch.current++;
  }, [connection.status]);
  async function load() {
    if (lock.current || connection.busy || connection.loading) return;
    lock.current = true;
    setBusy(true);
    setError("");
    const expected = ++epoch.current;
    try {
      const next = await connectionsApi.usage();
      if (mounted.current && expected === epoch.current) {
        if (next.account_id !== (accountId ?? null))
          throw new Error("Connection account changed. Reload usage.");
        setUsage(next);
      }
    } catch (error) {
      if (mounted.current && expected === epoch.current)
        setError(connectionError(error));
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <section
      className={`agent-usage ${compact ? "compact" : ""}`}
      aria-label="Model usage and allowance"
    >
      <div className="agent-section-heading">
        <div>
          {!compact && <p className="eyebrow">ACCOUNT INFORMATION</p>}
          <h3>Usage & allowance</h3>
        </div>
        <button
          type="button"
          className="text-action"
          disabled={
            busy ||
            connection.busy ||
            connection.loading ||
            Boolean(connection.error)
          }
          onClick={() => void load()}
        >
          {busy ? "Checking…" : usage ? "Refresh usage" : "Check usage"}
        </button>
      </div>
      {!usage && (
        <p className="field-help">
          View allowance and token activity reported by your provider. No model
          inference is run.
        </p>
      )}
      {error && (
        <p role="alert" className="connection-error-text">
          {error}
        </p>
      )}
      {usage && (
        <div className="agent-usage-details">
          {!usage.rate_limits?.length && (
            <p className="field-help">
              Your provider has not supplied a remaining account allowance.
            </p>
          )}
          {usage.rate_limits?.map((limit) => (
            <div key={limit.id}>
              <strong className="agent-allowance-label">{limit.label}</strong>
              {limit.primary && (
                <WindowUsage window={limit.primary} label="Primary window" />
              )}
              {limit.secondary && (
                <WindowUsage
                  window={limit.secondary}
                  label="Secondary window"
                />
              )}
            </div>
          ))}
          {usage.last_run ? (
            <div className="agent-last-run">
              <h4>Last recorded run</h4>
              <p>
                {providerLabels[usage.last_run.provider]} ·{" "}
                {usage.last_run.model || "Model unavailable"}
              </p>
              <TokenActivity values={usage.last_run.usage} />
            </div>
          ) : (
            <p className="field-help">
              No model run has been recorded for this account.
            </p>
          )}
          {usage.token_activity && (
            <div className="agent-last-run">
              <h4>Provider token activity</h4>
              <TokenActivity values={usage.token_activity} />
            </div>
          )}
          {usage.notices.map((notice, index) => (
            <p className="field-help" key={`${index}-${notice}`}>
              {notice}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}

export function AgentConnectionsCard() {
  const connection = useConnections();
  const [runtime, setRuntime] = useState<AgentRuntime | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    connectionsApi
      .agent(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setRuntime(value);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setError(connectionError(error));
      });
    return () => controller.abort();
  }, [attempt]);
  return (
    <section className="connection-card card agent-connections-card">
      <div className="connection-card-heading">
        <div>
          <p className="eyebrow">RESEARCH AGENT</p>
          <h2>
            {runtime?.engine === "goose"
              ? "Goose research agent."
              : "Your research engine."}
          </h2>
        </div>
        {runtime && (
          <span className="credential-badge">
            {runtime.engine === "goose"
              ? `Goose${runtime.version ? ` ${runtime.version}` : ""}`
              : "Direct planning"}{" "}
            · {runtime.available ? "Available" : "Unavailable"}
          </span>
        )}
      </div>
      <p>
        {runtime?.message ??
          (error
            ? "The research engine status could not be read."
            : "Reading the installed research engine…")}
      </p>
      <p className="field-help">
        The agent can search selected public repositories and references, and
        skim available open-access article text for unscored review leads.
        Coverage is limited to supported sources; Labcat controls evidence
        validation and ranking.
      </p>
      <p>
        <a
          className="text-action"
          href="https://goose-docs.ai/"
          target="_blank"
          rel="noopener noreferrer"
        >
          Learn more about Goose <span aria-hidden="true">↗</span>
        </a>
      </p>
      {error && (
        <button
          className="text-action"
          type="button"
          onClick={() => setAttempt((value) => value + 1)}
          disabled={connection.busy}
        >
          Reload engine status
        </button>
      )}
      <AccountUsageView />
    </section>
  );
}

export function ChatGPTSignIn({
  accountId,
  saved,
  storage,
  disabled,
  onPrepare,
  startRequested = false,
  onStartHandled,
}: {
  accountId: string;
  saved: boolean;
  storage: "session" | "encrypted";
  disabled: boolean;
  onPrepare?: () => void;
  startRequested?: boolean;
  onStartHandled?: () => void;
}) {
  const connection = useConnections();
  const [flow, setFlow] = useState<LoginFlow | null>(null);
  const [flowStorage, setFlowStorage] = useState(storage);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [paused, setPaused] = useState(false);
  const [notice, setNotice] = useState("");
  const mounted = useRef(true);
  const lock = useRef(false);
  const startedAt = useRef(0);
  const account = connection.status?.accounts.find(
    (item) => item.id === accountId,
  );
  const signedIn =
    account?.credential_state === "session" ||
    account?.credential_state === "encrypted";
  const locked = account?.credential_state === "locked";
  const blocked =
    disabled || busy || connection.busy || connection.loading || !saved;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  async function update(operation: () => Promise<LoginFlow>, recover = false) {
    if (lock.current || blocked) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (recover && connection.error) await connection.reload();
      await connection.apply(async () => {
        const next = await operation();
        if (mounted.current) {
          setFlow(next);
          setPaused(false);
          if (next.status === "complete")
            setNotice(
              "ChatGPT account connected. Available models will load automatically below; choose one and save your selection.",
            );
        }
        return next.status === "complete"
          ? await connectionsApi.status()
          : connection.status!;
      });
    } catch (error) {
      if (mounted.current) {
        setError(connectionError(error));
        setPaused(true);
      }
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  useEffect(() => {
    if (flow?.status !== "pending" || paused || blocked || connection.error)
      return;
    if (Date.now() - startedAt.current >= 8 * 60 * 1000) {
      setPaused(true);
      setNotice(
        "Automatic checks have paused. Check the sign-in status when you are ready.",
      );
      return;
    }
    const timer = window.setTimeout(
      () =>
        void update(() => connectionsApi.pollLogin(accountId, flow.flow_id)),
      2000,
    );
    return () => window.clearTimeout(timer);
  }, [flow, paused, blocked, connection.error, accountId]);
  function start() {
    if (blocked || connection.error) return;
    startedAt.current = Date.now();
    setFlowStorage(storage);
    void update(() => connectionsApi.startLogin(accountId, storage));
  }
  useEffect(() => {
    if (!startRequested || blocked || connection.error) return;
    onStartHandled?.();
    start();
  }, [startRequested, blocked, connection.error]);
  function restartSignIn() {
    if (blocked || connection.error || flow?.status !== "pending") return;
    startedAt.current = Date.now();
    setFlowStorage(storage);
    void update(async () => {
      await connectionsApi.cancelLogin(accountId, flow.flow_id);
      return connectionsApi.startLogin(accountId, storage);
    });
  }
  async function logout() {
    if (lock.current || blocked || connection.error) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await connection.apply(() => connectionsApi.logout(accountId));
      if (mounted.current) {
        setFlow(null);
        setNotice("This ChatGPT connection is signed out.");
      }
    } catch (error) {
      if (mounted.current) setError(connectionError(error));
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <section className="agent-sign-in" aria-label="ChatGPT account sign-in">
      <div className="agent-section-heading">
        <h3>Sign in with ChatGPT</h3>
        {signedIn && <span className="credential-badge">Connected</span>}
      </div>
      <p>
        Your provider handles sign-in in your browser. Labcat never asks for
        your ChatGPT password. Account eligibility, available models and usage
        limits are determined by your provider.
      </p>
      {!signedIn && flow?.status === "pending" && flow.method !== "browser" && (
        <div className="agent-device-prerequisite">
          <strong>This connection uses device sign-in</strong>
          <p>
            If ChatGPT says device sign-in is disabled, open ChatGPT Settings →
            Security and enable device-code authorization. Your workspace
            administrator may control this permission.
          </p>
          <a
            href="https://learn.chatgpt.com/docs/auth#login-on-headless-devices"
            target="_blank"
            rel="noopener noreferrer"
          >
            Official device sign-in instructions{" "}
            <span aria-hidden="true">↗</span>
          </a>
          <p className="field-help">
            After changing that setting, request a new code below. This
            application cannot change your account permissions.
          </p>
        </div>
      )}
      {!saved ? (
        <>
          {onPrepare ? (
            <button
              className="quiet-button"
              type="button"
              disabled={
                disabled ||
                busy ||
                connection.busy ||
                connection.loading ||
                Boolean(connection.error)
              }
              onClick={onPrepare}
            >
              Sign in with ChatGPT
            </button>
          ) : (
            <p className="model-needed-note">
              Save this connection first, then return here to sign in.
            </p>
          )}
        </>
      ) : locked ? (
        <p className="model-needed-note">
          Unlock the credential vault to use this saved sign-in.
        </p>
      ) : (
        <>
          {flow?.status === "pending" ? (
            <div className="agent-device-flow">
              <p>
                {flow.method === "browser"
                  ? "Open ChatGPT in your browser to sign in, then return here. Keep Labcat running while you connect."
                  : "Open the provider sign-in page and enter this code:"}
              </p>
              {flow.method !== "browser" && flow.user_code && (
                <code className="agent-device-code">{flow.user_code}</code>
              )}
              {flow.verification_url && (
                <a
                  className="primary-button"
                  href={flow.verification_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Open ChatGPT sign-in <span aria-hidden="true">↗</span>
                </a>
              )}
              <p className="field-help">
                {paused || error
                  ? "Automatic checks paused."
                  : "Waiting for you to finish sign-in…"}
              </p>
              <div className="connection-inline-actions">
                <button
                  className="quiet-button"
                  type="button"
                  disabled={blocked}
                  onClick={() => {
                    startedAt.current = Date.now();
                    void update(
                      () => connectionsApi.pollLogin(accountId, flow.flow_id),
                      true,
                    );
                  }}
                >
                  Check sign-in status
                </button>
                <button
                  className="text-action"
                  type="button"
                  disabled={blocked || Boolean(connection.error)}
                  onClick={restartSignIn}
                >
                  {flow.method === "browser"
                    ? "Start new sign-in"
                    : "Get a new code"}
                </button>
                <button
                  className="text-action"
                  type="button"
                  disabled={blocked || Boolean(connection.error)}
                  onClick={() =>
                    void update(() =>
                      connectionsApi.cancelLogin(accountId, flow.flow_id),
                    )
                  }
                >
                  Cancel sign-in
                </button>
              </div>
            </div>
          ) : (
            <div className="connection-inline-actions">
              <button
                className="quiet-button"
                type="button"
                disabled={blocked || Boolean(connection.error)}
                onClick={start}
              >
                {signedIn ? "Reconnect ChatGPT" : "Sign in with ChatGPT"}
              </button>
              {signedIn && (
                <button
                  className="text-action"
                  type="button"
                  disabled={blocked || Boolean(connection.error)}
                  onClick={() => void logout()}
                >
                  Sign out this account
                </button>
              )}
            </div>
          )}
          {flow?.status !== "pending" && flow?.message && (
            <p className="field-help">{flow.message}</p>
          )}
        </>
      )}
      {error && (
        <p className="connection-error-text" role="alert">
          {error}{" "}
          {!error.startsWith("Connection setup needs attention.") &&
            (flow?.status === "pending"
              ? "Your sign-in challenge is retained. Check its status to resume."
              : "Reload the saved connection before another change. To finish or cancel a pending sign-in on another account, select that connection first.")}
        </p>
      )}
      {notice && (
        <p className="connection-saved" role="status">
          {notice}
        </p>
      )}
      <p className="field-help">
        {(flow?.status === "pending"
          ? flowStorage
          : signedIn
            ? account?.credential_state
            : storage) === "encrypted"
          ? "Sign-in tokens use the encrypted credential vault."
          : "Sign-in tokens are held for this server session only."}{" "}
        Cloud research still requires the consent setting below.
      </p>
    </section>
  );
}

export function ResearchPlanCard() {
  const [plan, setPlan] = useState<ResearchPlan | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    connectionsApi
      .researchPlan(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setPlan(value);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setError(connectionError(error));
      });
    return () => controller.abort();
  }, [attempt]);
  return (
    <section
      className="card agent-build-plan"
      aria-label="Research execution plan"
    >
      <p className="eyebrow">RESEARCH EXECUTION</p>
      <h2>How this workspace builds a report.</h2>
      <p>
        Each request records its selected ranking profile, source filters and
        completed steps in the Technical View. The chat selector may infer or
        override the workspace ranking profile for that request.
      </p>
      {plan ? (
        <ol>
          {plan.steps.map((step, index) => (
            <li key={`${index}-${step}`}>
              <span>{index + 1}</span>
              <p>{step}</p>
            </li>
          ))}
        </ol>
      ) : (
        <p role="status">
          {error
            ? "The configured research plan could not be loaded."
            : "Loading the configured research plan…"}
        </p>
      )}
      {error && (
        <button
          className="quiet-button"
          type="button"
          onClick={() => setAttempt((value) => value + 1)}
        >
          Reload research plan
        </button>
      )}
    </section>
  );
}
