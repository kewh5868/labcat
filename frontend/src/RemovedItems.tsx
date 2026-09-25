import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import ChatIdentity, { chatLabel } from "./ChatIdentity";
import {
  errorMessage,
  RemovedItemsChangedError,
  workspaceApi,
} from "./workspaceApi";
import type {
  Project,
  RemovedItems,
  WorkspacePreferences,
} from "./workspaceApi";

export type ManagedItem = {
  kind: "project" | "chat";
  id: string;
  name: string;
  chatNumber?: number;
};
export type ItemAction = ManagedItem & { action: "rename" | "remove" };
type BulkDeletion = {
  snapshot: string;
  projectCount: number;
  chatCount: number;
};

function removalCount(projectCount: number, chatCount: number) {
  return `${projectCount} ${projectCount === 1 ? "project" : "projects"} · ${chatCount} individually removed ${chatCount === 1 ? "chat" : "chats"}`;
}

function ExpiryDate({ expiresAt }: { expiresAt: string | null }) {
  return (
    <p className="removed-expiry">
      {expiresAt ? (
        <>
          Scheduled for permanent deletion:{" "}
          <time dateTime={expiresAt}>
            {new Date(expiresAt).toLocaleString(undefined, {
              dateStyle: "medium",
              timeStyle: "short",
            })}
          </time>
        </>
      ) : (
        "Automatic deletion date unavailable."
      )}
    </p>
  );
}

function useMounted() {
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  return mounted;
}

export function ItemActionDialog({
  item,
  onCancel,
  onSave,
}: {
  item: ItemAction;
  onCancel: () => void;
  onSave: (
    item: ItemAction,
    name: string,
    skipConfirmation: boolean,
  ) => Promise<void>;
}) {
  const [name, setName] = useState(item.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [skipConfirmation, setSkipConfirmation] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const mounted = useMounted();
  const lock = useRef(false);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (lock.current || !name.trim() || error) return;
    lock.current = true;
    setBusy(true);
    try {
      await onSave(
        item,
        name.trim(),
        item.action === "remove" && skipConfirmation,
      );
    } catch (error) {
      if (mounted.current)
        setError(
          `${errorMessage(error)} Close this dialog and check the workspace before trying again.`,
        );
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="workspace-dialog"
      aria-labelledby="item-action-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onCancel();
      }}
    >
      <form onSubmit={submit}>
        <p className="eyebrow">
          {item.kind === "project" ? "RESEARCH PROJECT" : "CONVERSATION"}
        </p>
        <h2 id="item-action-title">
          {item.action === "rename" ? "Rename" : "Remove"} {item.kind}
        </h2>
        {item.action === "rename" ? (
          <>
            <label htmlFor="item-name">
              {item.kind === "project" ? "Project name" : "Chat name"}
            </label>
            <input
              autoFocus
              id="item-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={120}
              disabled={busy}
              required
            />
            <p>
              {item.chatNumber
                ? `Chat #${item.chatNumber} keeps this number when renamed or moved. `
                : ""}
              A name you choose will stay as written.
            </p>
          </>
        ) : (
          <>
            <p>
              Move{" "}
              <strong>
                <ChatIdentity title={item.name} number={item.chatNumber} />
              </strong>{" "}
              to Removed items?
            </p>
            <p>
              {item.kind === "project"
                ? "Its chats, pinned reports and resources will leave the active workspace together. You can restore the project from Removed items before it expires after 30 days."
                : "Its history and reports will be kept in Removed items so you can restore this chat before it expires after 30 days."}
            </p>
            <label className="removal-checkbox">
              <input
                type="checkbox"
                checked={skipConfirmation}
                disabled={busy}
                onChange={(event) => setSkipConfirmation(event.target.checked)}
              />
              <span>Don’t show this again for recoverable removals</span>
            </label>
            <p className="removal-preference-note">
              You can turn confirmations back on in Removed items. Manual
              permanent deletion requires confirmation; expired items are
              deleted automatically.
            </p>
          </>
        )}
        {error && (
          <p className="dialog-error" role="alert">
            {error}
          </p>
        )}
        <div className="form-actions">
          <button
            type="button"
            className="quiet-button"
            disabled={busy}
            onClick={onCancel}
          >
            {error ? "Close" : "Cancel"}
          </button>
          <button
            type="submit"
            className={
              item.action === "remove" ? "danger-button" : "primary-button"
            }
            disabled={busy || !name.trim() || Boolean(error)}
          >
            {busy
              ? "Saving…"
              : item.action === "rename"
                ? "Save name"
                : `Remove ${item.kind}`}
          </button>
        </div>
      </form>
    </dialog>
  );
}

function PermanentDeleteDialog({
  item,
  onCancel,
  onDelete,
}: {
  item: ManagedItem;
  onCancel: () => void;
  onDelete: (item: ManagedItem) => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const lock = useRef(false);
  const mounted = useMounted();
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!confirmed || lock.current || error) return;
    lock.current = true;
    setBusy(true);
    try {
      await onDelete(item);
    } catch (error) {
      if (mounted.current)
        setError(
          `${errorMessage(error)} Close this dialog to check the saved list before taking another action.`,
        );
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="workspace-dialog permanent-delete-dialog"
      aria-labelledby="permanent-delete-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onCancel();
      }}
    >
      <form onSubmit={submit}>
        <p className="eyebrow">PERMANENT DELETION</p>
        <h2 id="permanent-delete-title">Permanently delete {item.kind}?</h2>
        <p>
          <strong>
            <ChatIdentity title={item.name} number={item.chatNumber} />
          </strong>{" "}
          will be deleted from this workspace. This cannot be undone.
        </p>
        <p>
          {item.kind === "project"
            ? "This also deletes all chats, reports, pins and resources still in this project, including individually removed chats."
            : "This deletes the chat history and reports. Sources still used or pinned elsewhere in its project will be kept."}
        </p>
        <label className="removal-checkbox">
          <input
            type="checkbox"
            checked={confirmed}
            disabled={busy || Boolean(error)}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          <span>I understand this cannot be undone.</span>
        </label>
        {error && (
          <p className="dialog-error" role="alert">
            {error}
          </p>
        )}
        <div className="form-actions">
          <button
            type="button"
            className="quiet-button"
            disabled={busy}
            onClick={onCancel}
          >
            {error ? "Close" : "Cancel"}
          </button>
          <button
            type="submit"
            className="danger-button"
            disabled={!confirmed || busy || Boolean(error)}
          >
            {busy ? "Deleting…" : `Permanently delete ${item.kind}`}
          </button>
        </div>
      </form>
    </dialog>
  );
}

function BulkPermanentDeleteDialog({
  reviewed,
  onCancel,
  onDelete,
}: {
  reviewed: BulkDeletion;
  onCancel: () => void;
  onDelete: (reviewed: BulkDeletion) => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const lock = useRef(false);
  const mounted = useMounted();
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!confirmed || lock.current || error) return;
    lock.current = true;
    setBusy(true);
    try {
      await onDelete(reviewed);
    } catch (error) {
      if (mounted.current)
        setError(
          `${errorMessage(error)} Close this dialog to check the saved list before taking another action.`,
        );
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="workspace-dialog permanent-delete-dialog bulk-permanent-delete-dialog"
      aria-labelledby="bulk-permanent-delete-title"
      aria-describedby="bulk-permanent-delete-scope"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onCancel();
      }}
    >
      <form onSubmit={submit}>
        <p className="eyebrow">PERMANENT DELETION</p>
        <h2 id="bulk-permanent-delete-title">
          Permanently delete all removed items?
        </h2>
        <p className="bulk-deletion-count">
          {removalCount(reviewed.projectCount, reviewed.chatCount)}
        </p>
        <p id="bulk-permanent-delete-scope">
          This deletes every item in the reviewed list. It also deletes all
          chats, reports, pins and resources still in those removed projects,
          including individually removed chats. Deleted chat histories and
          reports cannot be restored.
        </p>
        <p>
          <strong>This cannot be undone.</strong> Items in the active workspace
          stay available.
        </p>
        <label className="removal-checkbox">
          <input
            type="checkbox"
            checked={confirmed}
            disabled={busy || Boolean(error)}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          <span>
            I understand all these removed items will be permanently deleted.
          </span>
        </label>
        {error && (
          <p className="dialog-error" role="alert">
            {error}
          </p>
        )}
        <div className="form-actions">
          <button
            type="button"
            className="quiet-button"
            disabled={busy}
            onClick={onCancel}
          >
            {error ? "Close" : "Cancel"}
          </button>
          <button
            type="submit"
            className="danger-button"
            disabled={!confirmed || busy || Boolean(error)}
          >
            {busy ? "Deleting…" : "Permanently delete all"}
          </button>
        </div>
      </form>
    </dialog>
  );
}

export default function RemovedItemsPanel({
  projects,
  revision,
  workspaceBusy,
  onRestore,
  onPermanentlyDelete,
  onPermanentlyDeleteAll,
}: {
  projects: Project[];
  revision: number;
  workspaceBusy: boolean;
  onRestore: (item: ManagedItem) => Promise<void>;
  onPermanentlyDelete: (item: ManagedItem) => Promise<void>;
  onPermanentlyDeleteAll: (snapshot: string) => Promise<void>;
}) {
  const [items, setItems] = useState<RemovedItems | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [pendingDelete, setPendingDelete] = useState<ManagedItem | null>(null);
  const [pendingBulkDelete, setPendingBulkDelete] =
    useState<BulkDeletion | null>(null);
  const [preferences, setPreferences] = useState<WorkspacePreferences | null>(
    null,
  );
  const [preferenceError, setPreferenceError] = useState("");
  const [savingPreference, setSavingPreference] = useState(false);
  const [loadingPreference, setLoadingPreference] = useState(true);
  const mounted = useMounted();
  const lock = useRef(false);
  const preferenceLock = useRef(false);
  const preferenceEpoch = useRef(0);
  const confirmationOpen = Boolean(pendingDelete || pendingBulkDelete);
  const refreshState = useRef({ busy: false, blocked: false });
  refreshState.current = {
    busy: Boolean(busy) || workspaceBusy || loading || savingPreference,
    blocked: confirmationOpen || Boolean(error) || Boolean(preferenceError),
  };
  useEffect(() => {
    if (lock.current || workspaceBusy || busy || confirmationOpen || error)
      return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    workspaceApi
      .removed(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setItems(value);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [revision, retry, workspaceBusy, busy, confirmationOpen]);
  useEffect(() => {
    const refresh = () => {
      if (
        document.visibilityState === "hidden" ||
        lock.current ||
        preferenceLock.current ||
        refreshState.current.busy ||
        refreshState.current.blocked
      )
        return;
      setRetry((value) => value + 1);
    };
    const interval = window.setInterval(refresh, 60_000);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);
  useEffect(() => {
    if (preferenceLock.current) return;
    const controller = new AbortController();
    const epoch = ++preferenceEpoch.current;
    setLoadingPreference(true);
    const current = () =>
      !controller.signal.aborted &&
      epoch === preferenceEpoch.current &&
      !preferenceLock.current;
    workspaceApi
      .workspacePreferences(controller.signal)
      .then((value) => {
        if (current()) {
          setPreferences(value);
          setPreferenceError("");
        }
      })
      .catch((error: unknown) => {
        if (current()) setPreferenceError(errorMessage(error));
      })
      .finally(() => {
        if (current()) setLoadingPreference(false);
      });
    return () => controller.abort();
  }, [revision, retry]);
  async function savePreference(confirm_removal: boolean) {
    if (preferenceLock.current) return;
    preferenceLock.current = true;
    preferenceEpoch.current++;
    setLoadingPreference(false);
    setSavingPreference(true);
    setPreferenceError("");
    try {
      const next = await workspaceApi.saveWorkspacePreferences({
        confirm_removal,
      });
      if (mounted.current) setPreferences(next);
    } catch (error) {
      if (mounted.current) setPreferenceError(errorMessage(error));
    } finally {
      preferenceLock.current = false;
      if (mounted.current) setSavingPreference(false);
    }
  }
  async function restore(item: ManagedItem) {
    if (lock.current || workspaceBusy || loading || confirmationOpen || error)
      return;
    lock.current = true;
    setBusy(item.id);
    setError("");
    setNotice("");
    try {
      await onRestore(item);
      if (mounted.current) {
        setNotice(`“${chatLabel(item.name, item.chatNumber)}” restored.`);
        setRetry((value) => value + 1);
      }
    } catch (error) {
      if (mounted.current)
        setError(
          `${errorMessage(error)} Check the saved list before trying again.`,
        );
    } finally {
      lock.current = false;
      if (mounted.current) setBusy("");
    }
  }
  async function permanentlyDelete(item: ManagedItem) {
    if (lock.current || workspaceBusy)
      throw new Error(
        "The workspace is already updating an item. Please wait.",
      );
    lock.current = true;
    setBusy(item.id);
    setNotice("");
    try {
      await onPermanentlyDelete(item);
      if (mounted.current) {
        setPendingDelete(null);
        setNotice(
          `“${chatLabel(item.name, item.chatNumber)}” permanently deleted.`,
        );
        setRetry((value) => value + 1);
      }
    } finally {
      lock.current = false;
      if (mounted.current) setBusy("");
    }
  }
  async function permanentlyDeleteAll(reviewed: BulkDeletion) {
    if (lock.current || workspaceBusy)
      throw new Error(
        "The workspace is already updating an item. Please wait.",
      );
    lock.current = true;
    setBusy("all");
    setNotice("");
    try {
      await onPermanentlyDeleteAll(reviewed.snapshot);
      if (mounted.current) {
        setPendingBulkDelete(null);
        setNotice("All reviewed removed items were permanently deleted.");
        setRetry((value) => value + 1);
      }
    } catch (error) {
      if (!(error instanceof RemovedItemsChangedError)) throw error;
      if (mounted.current) {
        setPendingBulkDelete(null);
        setNotice(error.message);
        setRetry((value) => value + 1);
      }
    } finally {
      lock.current = false;
      if (mounted.current) setBusy("");
    }
  }
  const disabled =
    Boolean(busy) ||
    workspaceBusy ||
    loading ||
    savingPreference ||
    Boolean(error) ||
    confirmationOpen;
  function actions(item: ManagedItem, parentRemoved = false) {
    return (
      <div className="removed-item-actions">
        <button
          type="button"
          className="quiet-button"
          disabled={disabled || parentRemoved}
          onClick={() => void restore(item)}
        >
          {busy === item.id && !pendingDelete ? "Restoring…" : "Restore"}
        </button>
        <button
          type="button"
          className="danger-button"
          disabled={disabled}
          onClick={() => setPendingDelete(item)}
        >
          Permanently delete
        </button>
      </div>
    );
  }
  return (
    <section className="removed-items-page">
      <header className="settings-intro">
        <p className="eyebrow">SAVED, OUT OF THE WAY</p>
        <h1>Removed items</h1>
        <p>
          Restore a project or chat, or permanently delete it from this
          workspace. Removed items are excluded from active research context.
        </p>
        <p>
          Removed items are kept for {items?.retention_days ?? 30} days, then
          permanently deleted automatically while the application is running. If
          it is closed, overdue items are deleted the next time it starts. A
          chat in a removed project can expire sooner with its project.
        </p>
      </header>
      <div className="removed-items-toolbar">
        <p className="removed-count" aria-live="polite">
          {items
            ? removalCount(items.projects.length, items.chats.length)
            : "Loading saved items…"}
        </p>
        <button
          type="button"
          className="danger-button removed-delete-all"
          disabled={
            disabled ||
            Boolean(preferenceError) ||
            !items ||
            items.projects.length + items.chats.length === 0
          }
          onClick={() => {
            if (items && !disabled)
              setPendingBulkDelete({
                snapshot: items.snapshot,
                projectCount: items.projects.length,
                chatCount: items.chats.length,
              });
          }}
        >
          Permanently delete all
        </button>
      </div>
      <section
        className="removal-preferences card"
        aria-label="Removal preferences"
      >
        <label className="removal-checkbox">
          <input
            type="checkbox"
            checked={preferences?.confirm_removal ?? true}
            disabled={
              !preferences ||
              loadingPreference ||
              savingPreference ||
              workspaceBusy ||
              confirmationOpen
            }
            onChange={(event) => void savePreference(event.target.checked)}
          />
          <span>Ask before moving projects and chats to Removed items</span>
        </label>
        <p>
          Saved for this workspace between sessions. Manual permanent deletion
          requires a separate confirmation; the 30-day automatic deletion
          happens without another prompt.
        </p>
        {savingPreference && <p role="status">Saving preference…</p>}
        {preferenceError && <p role="alert">{preferenceError}</p>}
      </section>
      {(error || preferenceError) && (
        <div className="workspace-error" role={error ? "alert" : undefined}>
          {error && <p>{error}</p>}
          <button
            type="button"
            className="quiet-button"
            disabled={
              Boolean(busy) ||
              workspaceBusy ||
              savingPreference ||
              confirmationOpen
            }
            onClick={() => {
              setNotice("");
              setError("");
              setRetry((value) => value + 1);
            }}
          >
            Check removed items
          </button>
        </div>
      )}
      {notice && (
        <p className="removed-operation-notice" role="status">
          {notice}
        </p>
      )}
      {loading && (
        <p role="status">
          {items ? "Updating removed items…" : "Loading removed items…"}
        </p>
      )}
      {items && (
        <>
          <section className="removed-items-group card">
            <h2>Projects</h2>
            {items.projects.length ? (
              items.projects.map((project) => (
                <div className="removed-item" key={project.id}>
                  <div>
                    <strong>{project.name}</strong>
                    <p>
                      {project.chat_count}{" "}
                      {project.chat_count === 1 ? "chat" : "chats"} ·{" "}
                      {project.pin_counts.reports} reports ·{" "}
                      {project.pin_counts.sources} sources pinned
                    </p>
                    <p>
                      Restoring also returns chats removed with this project.
                    </p>
                    <ExpiryDate expiresAt={project.expires_at} />
                  </div>
                  {actions({
                    kind: "project",
                    id: project.id,
                    name: project.name,
                  })}
                </div>
              ))
            ) : (
              <p className="empty-removal-list">No removed projects.</p>
            )}
          </section>
          <section className="removed-items-group card">
            <h2>Chats</h2>
            {items.chats.length ? (
              items.chats.map((chat) => {
                const parentRemoved = Boolean(
                  chat.project_id &&
                    (items.projects.some(
                      (project) => project.id === chat.project_id,
                    ) ||
                      !projects.some(
                        (project) => project.id === chat.project_id,
                      )),
                );
                return (
                  <div className="removed-item" key={chat.id}>
                    <div>
                      <strong>
                        <ChatIdentity
                          title={chat.title}
                          number={chat.chat_number}
                        />
                      </strong>
                      <p>
                        {parentRemoved
                          ? "Restore its project first to restore this chat."
                          : chat.project_id
                            ? projects.find(
                                (project) => project.id === chat.project_id,
                              )?.name
                            : "General chat"}
                      </p>
                      <ExpiryDate expiresAt={chat.expires_at} />
                    </div>
                    {actions(
                      {
                        kind: "chat",
                        id: chat.id,
                        name: chat.title,
                        chatNumber: chat.chat_number,
                      },
                      parentRemoved,
                    )}
                  </div>
                );
              })
            ) : (
              <p className="empty-removal-list">
                No individually removed chats.
              </p>
            )}
          </section>
        </>
      )}
      {pendingDelete && (
        <PermanentDeleteDialog
          key={`${pendingDelete.kind}-${pendingDelete.id}`}
          item={pendingDelete}
          onCancel={() => {
            setPendingDelete(null);
            setRetry((value) => value + 1);
          }}
          onDelete={permanentlyDelete}
        />
      )}
      {pendingBulkDelete && (
        <BulkPermanentDeleteDialog
          reviewed={pendingBulkDelete}
          onCancel={() => {
            setPendingBulkDelete(null);
            setRetry((value) => value + 1);
          }}
          onDelete={permanentlyDeleteAll}
        />
      )}
    </section>
  );
}
