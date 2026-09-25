import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { Chat, Project } from "./workspaceApi";
import { errorMessage } from "./workspaceApi";
import ChatIdentity from "./ChatIdentity";

export default function MoveChatDialog({
  chat,
  projects,
  forPin = false,
  blocked = false,
  onCancel,
  onMove,
  onCreateAndMove,
}: {
  chat: Chat;
  projects: Project[];
  forPin?: boolean;
  blocked?: boolean;
  onCancel: () => void;
  onMove: (chat: Chat, projectId: string | null) => Promise<void>;
  onCreateAndMove: (
    chat: Chat,
    name: string,
    description: string,
  ) => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const lock = useRef(false);
  const mounted = useRef(true);
  const [target, setTarget] = useState(chat.project_id ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  useEffect(() => {
    mounted.current = true;
    dialog.current?.showModal();
    return () => {
      mounted.current = false;
    };
  }, []);
  const changed = creating || target !== (chat.project_id ?? "");
  const available = creating
    ? Boolean(name.trim()) &&
      name.trim().length <= 120 &&
      description.trim().length <= 2000
    : !target || projects.some((project) => project.id === target);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (lock.current || blocked || !changed || !available || error) return;
    lock.current = true;
    setBusy(true);
    try {
      if (creating)
        await onCreateAndMove(chat, name.trim(), description.trim());
      else await onMove(chat, target || null);
    } catch (error) {
      if (mounted.current)
        setError(
          `${errorMessage(error)} Close this dialog and check the saved project before trying again.`,
        );
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="workspace-dialog move-chat-dialog"
      aria-labelledby="move-chat-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onCancel();
      }}
    >
      <form onSubmit={submit}>
        <p className="eyebrow">ORGANIZE CONVERSATION</p>
        <h2 id="move-chat-title">Move chat</h2>
        <p>
          <ChatIdentity title={chat.title} number={chat.chat_number} />
        </p>
        <p>
          {forPin
            ? "Choose an existing project or create a new one for this chat so you can pin its reports and resources. After moving, select Pin on the item you want to keep."
            : "Choose an existing project or create a new one. Your conversation and reports move with this chat."}
        </p>
        <fieldset
          className="move-chat-destinations"
          disabled={busy || blocked || Boolean(error)}
        >
          <legend>Destination</legend>
          <label>
            <input
              type="radio"
              name="chat-destination"
              value=""
              checked={!creating && target === ""}
              onChange={() => {
                setCreating(false);
                setTarget("");
              }}
            />
            <span>
              <strong>General Chats</strong>
              <small>No project</small>
            </span>
          </label>
          {projects.map((project) => (
            <label key={project.id}>
              <input
                type="radio"
                name="chat-destination"
                value={project.id}
                checked={!creating && target === project.id}
                onChange={() => {
                  setCreating(false);
                  setTarget(project.id);
                }}
              />
              <span>
                <strong>{project.name}</strong>
                {project.id === chat.project_id && (
                  <small>Current project</small>
                )}
              </span>
            </label>
          ))}
          <label>
            <input
              type="radio"
              name="chat-destination"
              value="new-project"
              checked={creating}
              onChange={() => setCreating(true)}
            />
            <span>
              <strong>Create new project</strong>
              <small>Name a project and move this chat into it</small>
            </span>
          </label>
        </fieldset>
        {creating && (
          <fieldset
            className="move-chat-new-project"
            disabled={busy || blocked || Boolean(error)}
          >
            <legend className="sr-only">New project details</legend>
            <label htmlFor="move-project-name">Project name</label>
            <input
              id="move-project-name"
              autoComplete="off"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="e.g. Quantum-dot research"
              maxLength={120}
              required
            />
            <label htmlFor="move-project-description">
              Description <span className="optional-label">optional</span>
            </label>
            <textarea
              id="move-project-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              maxLength={2000}
              rows={2}
            />
          </fieldset>
        )}
        {chat.project_id && changed && (
          <p className="move-chat-note">
            Existing report pins are cleared from the previous project.
            Resources already pinned there remain available there.
          </p>
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
            className="primary-button"
            disabled={
              busy || blocked || !changed || !available || Boolean(error)
            }
          >
            {busy
              ? creating
                ? "Creating and moving…"
                : "Moving…"
              : creating
                ? "Create project and move chat"
                : "Move chat"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
