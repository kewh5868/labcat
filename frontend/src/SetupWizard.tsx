import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { LabcatMark } from "./Brand";
import { ConnectionsPanel, useConnections } from "./Connections";
import type { ConnectionFormState } from "./Connections";
import type { ConnectionStatus, ConnectionTest } from "./connectionsApi";
import SetupReviewModel from "./SetupReviewModel";
import { setupApi, setupError } from "./setupApi";
import type { SetupStatus, SetupStep } from "./setupApi";
import "./setupWizard.css";

interface SetupContextValue {
  status: SetupStatus | null;
  loading: boolean;
  busy: boolean;
  error: string;
  refresh: () => Promise<SetupStatus>;
  apply: (operation: () => Promise<SetupStatus>) => Promise<SetupStatus>;
}
const SetupContext = createContext<SetupContextValue | null>(null);
export function useSetup() {
  const context = useContext(SetupContext);
  if (!context) throw new Error("Setup context is unavailable.");
  return context;
}
export function SetupProvider({ children }: { children: ReactNode }) {
  const connection = useConnections();
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(true);
  const epoch = useRef(0);
  const lock = useRef(false);
  const currentConnection = useRef(connection.status);
  currentConnection.current = connection.status;
  const failedMutation = useRef<{
    connection: typeof connection.status;
  } | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      epoch.current++;
    };
  }, []);
  const refresh = useCallback(async () => {
    if (lock.current) throw new Error("Setup change is already in progress.");
    failedMutation.current = null;
    const expected = ++epoch.current;
    setLoading(true);
    setError("");
    try {
      const next = await setupApi.status();
      if (mounted.current && epoch.current === expected) setStatus(next);
      return next;
    } catch (error) {
      if (mounted.current && epoch.current === expected) {
        setStatus(null);
        setError(setupError(error));
      }
      throw error;
    } finally {
      if (mounted.current && epoch.current === expected) setLoading(false);
    }
  }, []);
  useEffect(() => {
    // A rejected check may leave the server's previous verification intact.
    // Keep its error visible until explicit retry/reload or a changed connection.
    if (
      !connection.loading &&
      !connection.busy &&
      !busy &&
      failedMutation.current?.connection !== connection.status
    )
      void refresh().catch(() => undefined);
  }, [connection.status, connection.loading, connection.busy, busy, refresh]);
  const apply = useCallback(async (operation: () => Promise<SetupStatus>) => {
    if (lock.current) throw new Error("Setup change is already in progress.");
    lock.current = true;
    failedMutation.current = null;
    const expected = ++epoch.current;
    setBusy(true);
    setError("");
    try {
      const next = await operation();
      if (mounted.current && epoch.current === expected) setStatus(next);
      return next;
    } catch (error) {
      if (mounted.current && epoch.current === expected) {
        failedMutation.current = { connection: currentConnection.current };
        setStatus(null);
        setError(setupError(error));
      }
      throw error;
    } finally {
      lock.current = false;
      if (mounted.current) {
        setBusy(false);
        setLoading(false);
      }
    }
  }, []);
  // Credential/profile changes invalidate the displayed readiness immediately, before the GET returns.
  const pending = loading || connection.loading || connection.busy;
  return (
    <SetupContext.Provider
      value={{
        status: pending ? null : status,
        loading: pending,
        busy,
        error,
        refresh,
        apply,
      }}
    >
      {children}
    </SetupContext.Provider>
  );
}

const STEPS: { id: SetupStep; label: string; detail: string }[] = [
  { id: "model", label: "Model", detail: "Required" },
  { id: "compute", label: "Compute", detail: "Optional" },
  { id: "sources", label: "Public sources", detail: "Optional" },
  { id: "review", label: "Ready", detail: "Review" },
];
const focusable =
  'button:enabled, a[href], input:enabled, select:enabled, textarea:enabled, summary, [tabindex="0"]';
const modelHeadings: Record<SetupStatus["model"]["status"], string> = {
  not_connected: "Connect your model account",
  model_required: "Choose a model for your account",
  consent_required: "Allow this provider to run research",
  credentials_locked: "Unlock your saved connection",
  verification_required: "Your saved connection is ready to check",
  ready: "Saved model connection verified",
  error: "Your connection check needs attention",
};
export default function SetupWizard({
  open,
  onClose,
  onComplete,
}: {
  open: boolean;
  onClose: () => void;
  onComplete: () => void;
}) {
  const setup = useSetup();
  const connection = useConnections();
  const [step, setStep] = useState<SetupStep>("model");
  const [configureAws, setConfigureAws] = useState(false);
  const [formState, setFormState] = useState<ConnectionFormState>({
    dirty: false,
    busy: false,
  });
  const [verificationRetry, setVerificationRetry] =
    useState<typeof connection.status>(null);
  const [completionError, setCompletionError] = useState("");
  const continueLock = useRef(false);
  const panel = useRef<HTMLDivElement>(null);
  const portal = useRef<HTMLDivElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const opened = useRef(false);
  const close = useRef(onClose);
  close.current = onClose;
  const busy =
    setup.busy ||
    setup.loading ||
    connection.busy ||
    connection.loading ||
    formState.busy;
  const ready = Boolean(setup.status?.can_research);
  // A failed request may leave old readiness on the server. Retry the check
  // explicitly, and only for the unchanged connection that was being checked.
  const canVerify =
    setup.status?.model.status === "verification_required" ||
    setup.status?.model.status === "error" ||
    Boolean(
      setup.error &&
        verificationRetry &&
        verificationRetry === connection.status,
    );
  const modelHeading = setup.status
    ? modelHeadings[setup.status.model.status]
    : setup.error
      ? modelHeadings.error
      : "Reading your saved connection";
  const footerMessage = busy
    ? "Checking the saved connection and available models…"
    : step === "model" && formState.dirty
      ? "Save and test your connection changes above before continuing."
      : step === "review" && formState.dirty
        ? "Resolve the model connection check above before finishing setup."
        : setup.error ||
          (step === "model" && !ready
            ? setup.status?.model.status === "verification_required"
              ? "Check this saved account and model to continue. No inference is run."
              : (setup.status?.model.message ??
                "Reload setup to check this connection.")
            : formState.dirty
              ? "Save optional changes to use them, or skip this step without applying them."
              : "Saved history remains accessible. A verified account and model are required for new research.");
  useEffect(() => {
    if (!open) {
      opened.current = false;
      setCompletionError("");
      return;
    }
    if (!opened.current && setup.status) {
      opened.current = true;
      setStep(setup.status.can_research ? setup.status.current_step : "model");
    }
  }, [open, setup.status]);
  useEffect(() => {
    if (!open) return;
    const previous =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const siblings = [...document.body.children].filter(
      (item) => item !== portal.current && item instanceof HTMLElement,
    ) as HTMLElement[];
    const states = siblings.map((item) => ({ item, inert: item.inert }));
    states.forEach(({ item }) => {
      item.inert = true;
    });
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    heading.current?.focus();
    function keydown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        close.current();
      }
      if (event.key !== "Tab" || !panel.current) return;
      const elements = [
        ...panel.current.querySelectorAll<HTMLElement>(focusable),
      ].filter((element) => !element.closest("[hidden]"));
      const first = elements[0],
        last = elements.at(-1);
      if (!first) {
        event.preventDefault();
        heading.current?.focus();
        return;
      }
      if (
        event.shiftKey &&
        (document.activeElement === first ||
          !panel.current.contains(document.activeElement) ||
          document.activeElement === heading.current)
      ) {
        event.preventDefault();
        last?.focus();
      } else if (
        !event.shiftKey &&
        (document.activeElement === last ||
          !panel.current.contains(document.activeElement))
      ) {
        event.preventDefault();
        first.focus();
      }
    }
    function keepFocus(event: FocusEvent) {
      if (
        event.target instanceof Node &&
        panel.current &&
        !panel.current.contains(event.target)
      )
        heading.current?.focus();
    }
    document.addEventListener("keydown", keydown);
    document.addEventListener("focusin", keepFocus);
    return () => {
      document.removeEventListener("keydown", keydown);
      document.removeEventListener("focusin", keepFocus);
      states.forEach(({ item, inert }) => {
        item.inert = inert;
      });
      document.body.style.overflow = overflow;
      if (previous?.isConnected) previous.focus();
    };
  }, [open]);
  useEffect(() => {
    if (open) {
      heading.current?.focus();
      panel.current?.scrollTo?.({ top: 0 });
    }
  }, [step, open]);
  async function go(next: SetupStep) {
    setCompletionError("");
    try {
      await setup.apply(() => setupApi.progress(next));
      setStep(next);
    } catch {
      /* The provider renders a redacted error. */
    }
  }
  async function verifyModel(): Promise<ConnectionTest> {
    const next = await setup.apply(() => setupApi.verify());
    return {
      target: "model",
      status: next.can_research
        ? "ok"
        : next.model.status === "error"
          ? "error"
          : "not_configured",
      message: next.model.message,
      billable: false,
      inference_tested: false,
    };
  }
  async function verifyReviewModel(
    saved: ConnectionStatus,
  ): Promise<SetupStatus> {
    return setup.apply(async () => {
      const verified = await setupApi.verify();
      if (
        verified.model.account_id !== saved.active_account_id ||
        verified.model.provider !== saved.profile.provider ||
        verified.model.model !== saved.profile.model
      )
        throw new Error("The selected model changed during verification.");
      return verified;
    });
  }
  async function continueModel() {
    if (
      busy ||
      formState.dirty ||
      continueLock.current ||
      (!ready && !canVerify)
    )
      return;
    continueLock.current = true;
    setVerificationRetry(null);
    try {
      // Keep verification and progress under one setup lock so another click or
      // automatic refresh cannot interleave between these dependent operations.
      const next = await setup.apply(async () => {
        if (!ready) {
          const verified = await setupApi.verify();
          if (!verified.can_research) return verified;
        }
        return setupApi.progress("compute");
      });
      if (next.can_research && next.current_step === "compute")
        setStep("compute");
    } catch {
      setVerificationRetry(connection.status);
    } finally {
      continueLock.current = false;
    }
  }
  async function finish() {
    if (busy || formState.dirty || continueLock.current) return;
    continueLock.current = true;
    setCompletionError("");
    function showCompletion(next: SetupStatus) {
      if (next.completed && next.can_research) onComplete();
      else if (!next.can_research) setStep("model");
      else
        setCompletionError(
          "Your model is connected, but setup is not complete. Select Finish setup to try again.",
        );
    }
    try {
      showCompletion(await setup.apply(() => setupApi.complete()));
    } catch {
      // Completion can be saved even if its response is interrupted. Confirm it
      // with a read before deciding whether any setup work remains.
      const recovered = await setup.refresh().catch(() => null);
      if (recovered) showCompletion(recovered);
      else
        setCompletionError(
          "Could not confirm setup completion. Reload setup, then try Finish setup again.",
        );
    } finally {
      continueLock.current = false;
    }
  }
  if (!open) return null;
  return createPortal(
    <div className="setup-overlay" ref={portal}>
      <div
        className="setup-window"
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="setup-heading"
        aria-describedby="setup-description"
      >
        <div className="setup-topline">
          <span className="setup-brand">
            <LabcatMark />
            <span className="setup-brand-copy">
              <strong>LABCAT</strong>
              <small>Curious. Clever. Companionable.</small>
            </span>
          </span>
          <button type="button" className="text-action" onClick={onClose}>
            View workspace <span aria-hidden="true">×</span>
          </button>
        </div>
        <ol className="setup-progress" aria-label="Setup progress">
          {STEPS.map((item, index) => (
            <li
              key={item.id}
              className={item.id === step ? "current" : ""}
              aria-current={item.id === step ? "step" : undefined}
            >
              <span>{index + 1}</span>
              <div>
                <strong>{item.label}</strong>
                <small>{item.detail}</small>
              </div>
            </li>
          ))}
        </ol>
        <header className="setup-intro">
          <p className="eyebrow">
            {setup.status?.completed
              ? "YOUR WORKSPACE SETUP"
              : "WELCOME TO YOUR RESEARCH WORKSPACE"}
          </p>
          <h1 id="setup-heading" ref={heading} tabIndex={-1}>
            {step === "model"
              ? "Connect your research model."
              : step === "compute"
                ? "Choose where the model runs."
                : step === "sources"
                  ? "Give research a wider view."
                  : "Your workspace is ready to connect."}
          </h1>
          <p id="setup-description">
            {step === "model"
              ? "Sign in to a supported account, choose a model, and verify the connection before starting research. Your provider handles account sign-in."
              : step === "compute"
                ? "Your workspace runs locally by default. You can optionally use Amazon Bedrock for model inference in AWS."
                : step === "sources"
                  ? "Supported public APIs add reference discovery and available materials properties. Database accounts are optional."
                  : "Review your connection, then finish setup. Every new research request checks the selected model connection."}
          </p>
        </header>
        {setup.error && (
          <div className="workspace-error" role="alert">
            <p>{setup.error}</p>
            <button
              type="button"
              className="quiet-button"
              disabled={busy}
              onClick={() => void setup.refresh().catch(() => undefined)}
            >
              Reload setup
            </button>
          </div>
        )}
        {completionError && (
          <div className="workspace-error" role="alert">
            <p>{completionError}</p>
          </div>
        )}
        {step === "model" && (
          <>
            <div
              className={`setup-readiness ${ready ? "ready" : ""}`}
              role="status"
            >
              <span aria-hidden="true">{ready ? "✓" : "◌"}</span>
              <div>
                <strong>{modelHeading}</strong>
                <p>
                  {setup.status?.model.message ??
                    (setup.loading
                      ? "Reading saved setup…"
                      : "Reload setup to check this connection.")}
                </p>
                <small>
                  Connection checks inspect account and model access; they do
                  not run paid inference.
                </small>
              </div>
            </div>
            <fieldset className="setup-model-controls" disabled={setup.busy}>
              <ConnectionsPanel
                onboarding
                section="model"
                onStateChange={setFormState}
                onVerifyModel={verifyModel}
              />
            </fieldset>
          </>
        )}
        {step === "compute" && (
          <>
            <div className="setup-local-card">
              <span aria-hidden="true">⌂</span>
              <div>
                <h2>Local workspace</h2>
                <p>
                  Chats, settings and reports stay in this installation. Your
                  selected provider runs the model; choosing AWS does not move
                  the application or deploy cloud infrastructure.
                </p>
              </div>
              <span className="credential-badge">Default</span>
            </div>
            <label className="setup-optional-toggle">
              <input
                type="checkbox"
                checked={configureAws}
                onChange={(event) => setConfigureAws(event.target.checked)}
              />
              <span>
                <strong>Configure Amazon Bedrock</strong>
                <small>
                  Optional · Use an AWS profile provisioned for this
                  installation. Requires AWS access to your chosen Bedrock model
                  and may incur charges.
                </small>
              </span>
            </label>
            {configureAws && (
              <>
                <p className="field-help">
                  Saving a Bedrock connection selects it for research. Verify it
                  before finishing setup. AWS credentials are handled by the
                  configured credential chain; no AWS password is collected
                  here.
                </p>
                <ConnectionsPanel
                  onboarding
                  section="compute"
                  onStateChange={setFormState}
                  onVerifyModel={verifyModel}
                />
              </>
            )}
          </>
        )}
        {step === "sources" && (
          <>
            <div className="setup-source-note">
              <strong>Public APIs work without an extra account.</strong>
              <p>
                NOMAD, HybriD³, Europe PMC and arXiv are supported without
                database keys. A Materials Project key is optional and enables
                its live public API. Availability and coverage are reported with
                each search.
              </p>
            </div>
            <ConnectionsPanel
              onboarding
              section="sources"
              onStateChange={setFormState}
            />
          </>
        )}
        {step === "review" && (
          <div className="setup-review">
            <SetupReviewModel
              disabled={setup.busy || setup.loading}
              onStateChange={setFormState}
              onVerify={verifyReviewModel}
              onManage={() => void go("model")}
            />
            <div>
              <span>Workspace compute</span>
              <strong>Local</strong>
              <p>
                {connection.status?.profile.provider === "bedrock"
                  ? "Selected model inference runs on Amazon Bedrock."
                  : "AWS is optional. No AWS deployment is created."}
              </p>
            </div>
            <div>
              <span>Public data APIs</span>
              <strong>Optional connections</strong>
              <p>
                Your saved public-source preferences apply to new searches.
                Missing evidence stays explicit.
              </p>
            </div>
            <p
              className={`setup-final-readiness ${ready ? "ready" : ""}`}
              role="status"
            >
              {setup.status?.model.message ??
                "Checking the selected model connection…"}
            </p>
          </div>
        )}
        <footer className="setup-footer">
          <p id="setup-footer-status" role="status">
            {footerMessage}
          </p>
          <div>
            {step !== "model" && (
              <button
                type="button"
                className="quiet-button"
                disabled={busy}
                onClick={() =>
                  void go(
                    STEPS[STEPS.findIndex((item) => item.id === step) - 1].id,
                  )
                }
              >
                Back
              </button>
            )}
            {(step === "compute" || step === "sources") && (
              <button
                type="button"
                className="quiet-button"
                disabled={busy}
                onClick={() =>
                  void go(step === "compute" ? "sources" : "review")
                }
              >
                Skip for now
              </button>
            )}
            {step === "review" ? (
              <button
                type="button"
                className="primary-button"
                aria-busy={busy}
                disabled={busy || formState.dirty}
                onClick={() => void finish()}
              >
                {busy ? "Verifying…" : "Finish setup"}
              </button>
            ) : (
              <button
                type="button"
                className="primary-button"
                aria-busy={busy}
                aria-describedby="setup-footer-status"
                disabled={
                  busy ||
                  formState.dirty ||
                  (step === "model" && !ready && !canVerify)
                }
                onClick={() =>
                  void (step === "model"
                    ? continueModel()
                    : go(step === "compute" ? "sources" : "review"))
                }
              >
                {step === "model" && !ready && canVerify
                  ? "Verify and continue"
                  : "Continue"}
              </button>
            )}
          </div>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
