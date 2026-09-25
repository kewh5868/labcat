import { useCallback, useEffect, useId, useRef, useState } from "react";
import type {
  CSSProperties,
  KeyboardEvent,
  PointerEvent,
  ReactNode,
} from "react";

const preferenceKey = "labcat-sidebar-sections-v1";
type Section = "projects" | "chats";
type Preference = { split: number; focused: Section | null };
const bounded = (value: number) =>
  Math.round(Math.min(80, Math.max(20, value)));

function readPreference(): Preference {
  try {
    const saved = JSON.parse(
      window.localStorage.getItem(preferenceKey) || "null",
    );
    if (saved?.version === 1)
      return {
        split:
          typeof saved.split === "number" && Number.isFinite(saved.split)
            ? bounded(saved.split)
            : 50,
        focused:
          saved.focused === "projects" || saved.focused === "chats"
            ? saved.focused
            : null,
      };
  } catch {
    /* Optional layout preferences must not block navigation. */
  }
  return { split: 50, focused: null };
}

export default function SidebarSections({
  projects,
  chats,
  projectAction,
  chatAction,
}: {
  projects: ReactNode;
  chats: ReactNode;
  projectAction: ReactNode;
  chatAction?: ReactNode;
}) {
  const [preference, setPreference] = useState(readPreference);
  const [resizing, setResizing] = useState(false);
  const panels = useRef<HTMLDivElement>(null);
  const resizer = useRef<HTMLDivElement>(null);
  const drag = useRef<{
    pointerId: number;
    startY: number;
    split: number;
    height: number;
  } | null>(null);
  const id = useId();
  const projectsId = `${id}-projects`,
    chatsId = `${id}-chats`;
  const split =
    preference.focused === "projects"
      ? 80
      : preference.focused === "chats"
        ? 20
        : preference.split;
  useEffect(() => {
    try {
      window.localStorage.setItem(
        preferenceKey,
        JSON.stringify({ version: 1, ...preference }),
      );
    } catch {
      /* Keep working when browser storage is unavailable. */
    }
  }, [preference]);
  const cancel = useCallback(() => {
    const active = drag.current;
    drag.current = null;
    setResizing(false);
    if (active && resizer.current?.hasPointerCapture(active.pointerId))
      resizer.current.releasePointerCapture(active.pointerId);
  }, []);
  useEffect(() => {
    window.addEventListener("resize", cancel);
    window.addEventListener("blur", cancel);
    return () => {
      window.removeEventListener("resize", cancel);
      window.removeEventListener("blur", cancel);
      cancel();
    };
  }, [cancel]);
  function focus(section: Section) {
    cancel();
    setPreference((current) => ({
      ...current,
      focused: current.focused === section ? null : section,
    }));
  }
  function resize(value: number) {
    setPreference({ split: bounded(value), focused: null });
  }
  function reset() {
    cancel();
    setPreference({ split: 50, focused: null });
  }
  function start(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || drag.current) return;
    const height =
      (panels.current?.getBoundingClientRect().height ?? 0) -
      event.currentTarget.getBoundingClientRect().height;
    if (height <= 0) return;
    event.preventDefault();
    event.currentTarget.focus();
    const actualSplit =
      (panels.current!.firstElementChild!.getBoundingClientRect().height /
        height) *
      100;
    drag.current = {
      pointerId: event.pointerId,
      startY: event.clientY,
      split: actualSplit,
      height,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    setResizing(true);
  }
  function move(event: PointerEvent<HTMLDivElement>) {
    const active = drag.current;
    if (active?.pointerId === event.pointerId)
      resize(
        active.split + ((event.clientY - active.startY) * 100) / active.height,
      );
  }
  function end(event: PointerEvent<HTMLDivElement>) {
    if (drag.current?.pointerId !== event.pointerId) return;
    cancel();
  }
  function keydown(event: KeyboardEvent<HTMLDivElement>) {
    if (
      !["ArrowUp", "ArrowDown", "Home", "End", "Enter", "Escape"].includes(
        event.key,
      )
    )
      return;
    event.preventDefault();
    cancel();
    if (event.key === "Enter") reset();
    else if (event.key !== "Escape")
      resize(
        event.key === "Home"
          ? 20
          : event.key === "End"
            ? 80
            : split +
              (event.key === "ArrowDown" ? 1 : -1) * (event.shiftKey ? 10 : 5),
      );
  }
  function heading(section: Section, label: string, sectionId: string) {
    const focused = preference.focused === section;
    return (
      <button
        className="sidebar-section-heading small-label"
        id={`${sectionId}-heading`}
        type="button"
        aria-controls={sectionId}
        aria-pressed={focused}
        title={
          focused
            ? "Restore the previous split"
            : `Give ${label.toLowerCase()} more space`
        }
        onClick={() => focus(section)}
      >
        {label}
        <span aria-hidden="true">
          {focused ? "↕" : section === "projects" ? "⌄" : "⌃"}
        </span>
      </button>
    );
  }
  return (
    <div
      ref={panels}
      className={`sidebar-history-panels${resizing ? " is-resizing" : ""}`}
      style={
        {
          "--sidebar-projects-share": `${split}fr`,
          "--sidebar-chats-share": `${100 - split}fr`,
        } as CSSProperties
      }
    >
      <section
        className="sidebar-history-section"
        id={projectsId}
        aria-labelledby={`${projectsId}-heading`}
      >
        <div className="project-list-heading">
          {heading("projects", "Projects", projectsId)}
          {projectAction}
        </div>
        {projects}
      </section>
      <div
        ref={resizer}
        className="sidebar-section-resizer"
        role="separator"
        tabIndex={0}
        aria-label="Resize projects and general chats"
        aria-orientation="horizontal"
        aria-controls={`${projectsId} ${chatsId}`}
        aria-valuemin={20}
        aria-valuemax={80}
        aria-valuenow={split}
        aria-valuetext={`Projects ${split}%, general chats ${100 - split}%`}
        title="Drag to resize. Use up/down arrows, or double-click to split evenly."
        onPointerDown={start}
        onPointerMove={move}
        onPointerUp={end}
        onPointerCancel={end}
        onLostPointerCapture={end}
        onDoubleClick={reset}
        onKeyDown={keydown}
      >
        <span />
      </div>
      <section
        className="sidebar-history-section"
        id={chatsId}
        aria-labelledby={`${chatsId}-heading`}
      >
        <div className="project-list-heading all-chats-heading">
          {heading("chats", "General chats", chatsId)}
          {chatAction}
        </div>
        {chats}
      </section>
    </div>
  );
}
