import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent } from "react";
import { errorMessage } from "./workspaceApi";

export default function ClearGeneralChatsDialog({
  snapshot,
  blocked,
  onCancel,
  onClear,
}: {
  snapshot: string[];
  blocked: boolean;
  onCancel: () => void;
  onClear: (snapshot: string[]) => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null),
    cancel = useRef<HTMLButtonElement>(null),
    lock = useRef(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const id = useId();
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    dialog.current?.showModal();
    cancel.current?.focus();
    return () => {
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (lock.current || blocked || error) return;
    lock.current = true;
    setBusy(true);
    try {
      await onClear(snapshot);
    } catch (error) {
      setError(
        `${errorMessage(error)} Close this dialog and review the workspace before trying again.`,
      );
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="workspace-dialog clear-general-chats-dialog"
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-scope`}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onCancel();
      }}
    >
      <form onSubmit={submit}>
        <p className="eyebrow">CLEAR GENERAL CHATS</p>
        <h2 id={`${id}-title`}>Are you sure?</h2>
        <p id={`${id}-scope`}>
          Move all{" "}
          <strong>
            {snapshot.length} general {snapshot.length === 1 ? "chat" : "chats"}
          </strong>{" "}
          to Removed items? Project chats stay in place.
        </p>
        <p>These chats can be restored from Removed items for 30 days.</p>
        {blocked && !busy && (
          <p role="status">
            Wait for the workspace update or research to finish before clearing
            these chats.
          </p>
        )}
        {error && (
          <p className="dialog-error" role="alert">
            {error}
          </p>
        )}
        <div className="form-actions">
          <button
            ref={cancel}
            autoFocus
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
            disabled={busy || blocked || Boolean(error)}
          >
            {busy ? "Clearing…" : "Clear all general chats"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
