import { useEffect, useId, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, PointerEvent } from "react";

const preferenceKey = "labcat-workspace-view-v1";
const defaultWidth = 238;
const minWidth = 220;
const maxWidth = 480;

function readPreference() {
  try {
    const saved: unknown = JSON.parse(
      window.localStorage.getItem(preferenceKey) || "null",
    );
    if (
      saved &&
      typeof saved === "object" &&
      "version" in saved &&
      saved.version === 1
    ) {
      const width =
        "sidebar_width" in saved ? saved.sidebar_width : defaultWidth;
      return {
        width:
          typeof width === "number" && Number.isFinite(width)
            ? Math.min(maxWidth, Math.max(minWidth, Math.round(width)))
            : defaultWidth,
        hidden: "sidebar_hidden" in saved && saved.sidebar_hidden === true,
      };
    }
  } catch {
    /* Layout preferences are optional, including in restricted webviews. */
  }
  return { width: defaultWidth, hidden: false };
}

export function useSidebarView() {
  const [preference, setPreference] = useState(readPreference);
  const [viewport, setViewport] = useState(() => window.innerWidth);
  const [resizing, setResizing] = useState(false);
  const drag = useRef<{
    pointerId: number;
    startX: number;
    startWidth: number;
  } | null>(null);
  const limit = Math.min(
    maxWidth,
    Math.max(minWidth, Math.floor(viewport * 0.42)),
  );
  const width = Math.min(preference.width, limit);
  useEffect(() => {
    try {
      window.localStorage.setItem(
        preferenceKey,
        JSON.stringify({
          version: 1,
          sidebar_width: preference.width,
          sidebar_hidden: preference.hidden,
        }),
      );
    } catch {
      /* Keep the current session usable if storage is unavailable. */
    }
  }, [preference]);
  useEffect(() => {
    const resize = () => {
      setViewport(window.innerWidth);
      drag.current = null;
      setResizing(false);
    };
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  const reset = () =>
    setPreference((current) => ({ ...current, width: defaultWidth }));
  const toggle = () => {
    drag.current = null;
    setResizing(false);
    setPreference((current) => ({ ...current, hidden: !current.hidden }));
  };
  const resizeTo = (value: number) =>
    setPreference((current) => ({
      ...current,
      width: Math.round(Math.min(limit, Math.max(minWidth, value))),
    }));
  function keydown(event: KeyboardEvent<HTMLDivElement>) {
    if (
      !["ArrowLeft", "ArrowRight", "Home", "End", "Enter"].includes(event.key)
    )
      return;
    event.preventDefault();
    if (event.key === "Enter") reset();
    else
      resizeTo(
        event.key === "Home"
          ? minWidth
          : event.key === "End"
            ? limit
            : width +
              (event.key === "ArrowRight" ? 1 : -1) *
                (event.shiftKey ? 50 : 10),
      );
  }
  function start(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || viewport <= 850) return;
    event.preventDefault();
    event.currentTarget.focus();
    drag.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth: width,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    setResizing(true);
  }
  function move(event: PointerEvent<HTMLDivElement>) {
    const active = drag.current;
    if (active?.pointerId === event.pointerId)
      resizeTo(active.startWidth + event.clientX - active.startX);
  }
  function end() {
    drag.current = null;
    setResizing(false);
  }
  return {
    hidden: preference.hidden,
    resizing,
    reset,
    toggle,
    style: { "--workspace-sidebar-width": `${width}px` } as CSSProperties,
    resizer: (
      <div
        className="sidebar-resizer"
        role="separator"
        tabIndex={0}
        aria-label="Resize sidebar"
        aria-orientation="vertical"
        aria-controls="workspace-sidebar"
        aria-valuemin={minWidth}
        aria-valuemax={limit}
        aria-valuenow={width}
        aria-valuetext={`${width} pixels`}
        title="Drag to resize. Use arrow keys, or double-click to reset."
        onPointerDown={start}
        onPointerMove={move}
        onPointerUp={end}
        onPointerCancel={end}
        onLostPointerCapture={end}
        onDoubleClick={reset}
        onKeyDown={keydown}
      />
    ),
  };
}

export function SidebarViewControls({
  hidden,
  onToggle,
  onReset,
}: {
  hidden: boolean;
  onToggle: () => void;
  onReset: () => void;
}) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const outside = (event: globalThis.PointerEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    const close = () => setOpen(false);
    document.addEventListener("pointerdown", outside, true);
    window.addEventListener("blur", close);
    return () => {
      document.removeEventListener("pointerdown", outside, true);
      window.removeEventListener("blur", close);
    };
  }, [open]);
  function choose(action: () => void) {
    action();
    setOpen(false);
    trigger.current?.focus();
  }
  return (
    <div
      className="workspace-view-control"
      ref={container}
      onBlur={(event) => {
        if (
          event.relatedTarget &&
          !event.currentTarget.contains(event.relatedTarget)
        )
          setOpen(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.preventDefault();
          event.stopPropagation();
          setOpen(false);
          trigger.current?.focus();
        }
      }}
    >
      <button
        className="workspace-view-trigger"
        ref={trigger}
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((value) => !value)}
      >
        <span aria-hidden="true">▥</span>View<span aria-hidden="true">⌄</span>
      </button>
      {open && (
        <div
          id={id}
          className="workspace-view-options"
          role="group"
          aria-label="View options"
        >
          <button type="button" onClick={() => choose(onToggle)}>
            {hidden ? "Show sidebar" : "Hide sidebar"}
          </button>
          <button type="button" onClick={() => choose(onReset)}>
            Reset sidebar width
          </button>
        </div>
      )}
    </div>
  );
}
