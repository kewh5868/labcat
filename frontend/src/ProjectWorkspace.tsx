import type { DragEvent, FormEvent, KeyboardEvent, ReactNode } from "react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { brandName, brandTagline, LabcatMark } from "./Brand";
import ChatIdentity, { chatLabel } from "./ChatIdentity";
import ClearGeneralChatsDialog from "./ClearGeneralChatsDialog";
import ComposerControls from "./ComposerControls";
import {
  ConnectionNotice,
  ConnectionsPanel,
  useConnections,
} from "./Connections";
import MoveChatDialog from "./MoveChatDialog";
import PublicSourcesPanel from "./PublicSources";
import QueryHistory, { queryHistory, QueryTime } from "./QueryHistory";
import RankingProfilesPanel from "./RankingProfiles";
import type { ItemAction, ManagedItem } from "./RemovedItems";
import RemovedItemsPanel, { ItemActionDialog } from "./RemovedItems";
import ReportContent from "./ReportContent";
import ReportFormat from "./ReportFormat";
import type { ReportPinAction } from "./ReportPinControls";
import ReportPinControls from "./ReportPinControls";
import type { ResearchSubmission } from "./ResearchProgress";
import ResearchProgress, { beginResearchSubmission } from "./ResearchProgress";
import RunningResearchIndicator from "./RunningResearchIndicator";
import SetupWizard, { useSetup } from "./SetupWizard";
import SidebarSections from "./SidebarSections";
import { SidebarViewControls, useSidebarView } from "./SidebarView";
import WorkspaceSearch from "./WorkspaceSearch";
import type { MaterialName } from "./chemicalNamesApi";
import { chemicalNamesApi } from "./chemicalNamesApi";
import type { PresentedReport } from "./reportPresentationApi";
import { reportPresentationApi } from "./reportPresentationApi";
import type { ProfileSnapshot, ReportTable } from "./reportTables";
import {
  savedProfileSnapshot,
  savedReportPresentation,
  savedReportTables,
} from "./reportTables";
import "./settingsLayout.css";
import { canSubmitResearch } from "./setupApi";
import type { WorkspaceResearch } from "./useResearchRuns";
import { completedResearchKey, useResearchRuns } from "./useResearchRuns";
import "./workspace.css";
import type {
  About,
  Chat,
  ChatDetail,
  ChatSearchMatch,
  ExportFormat,
  PinKind,
  Project,
  ProjectContents,
  ReportExportSection,
  ReportPin,
  ReportPresentation,
  ReportView,
  ResearchReport,
  SearchSettings,
  Source,
} from "./workspaceApi";
import {
  defaultSettings,
  errorMessage,
  GeneralChatsChangedError,
  publicLink,
  reportExportUrl,
  ResearchRequestError,
  workspaceApi,
} from "./workspaceApi";

type ComposerLinks = {
  onOpenSettings: () => void;
  onOpenConnections: () => void;
  onRequireSetup: () => void;
};
type PinAction = (kind: PinKind, id: string, pinned: boolean) => Promise<void>;
type ReportPinChange = (action: ReportPinAction) => Promise<void>;
const chatDragType = "application/x-labcat-chat-id";

async function applyReportPin(projectId: string, action: ReportPinAction) {
  if (action.type === "tracking")
    await workspaceApi.trackReport(projectId, action.chatId, action.tracking);
  else
    await workspaceApi.updateReportSnapshot(
      projectId,
      action.pin,
      action.reportId,
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
function SavedTime({ value }: { value: string }) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? null : (
    <time dateTime={value}>
      {date.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })}
    </time>
  );
}
function Notice({
  error,
  onRetry,
  label = "Reload",
}: {
  error: string;
  onRetry?: () => void;
  label?: string;
}) {
  return (
    <div className="workspace-error" role="alert">
      <p>{error}</p>
      {onRetry && (
        <button type="button" className="quiet-button" onClick={onRetry}>
          {label} <span aria-hidden="true">↻</span>
        </button>
      )}
    </div>
  );
}
function Loading({ label }: { label: string }) {
  return (
    <div className="workspace-loading" role="status">
      <span className="loading-ring" />
      <span>{label}</span>
    </div>
  );
}

function SidebarActions({
  item,
  onAction,
  onMove,
  disabled = false,
}: {
  item: ManagedItem;
  onAction: (action: ItemAction) => void;
  onMove?: () => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open) menu.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    const close = () => setOpen(false);
    const scroll = (event: Event) => {
      if (!menu.current?.contains(event.target as Node)) close();
    };
    document.addEventListener("pointerdown", outside, true);
    window.addEventListener("blur", close);
    document.addEventListener("scroll", scroll, true);
    return () => {
      document.removeEventListener("pointerdown", outside, true);
      window.removeEventListener("blur", close);
      document.removeEventListener("scroll", scroll, true);
    };
  }, [open]);
  function keydown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      trigger.current?.focus();
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const buttons = [
      ...(menu.current?.querySelectorAll<HTMLButtonElement>("button") ?? []),
    ];
    const current = buttons.indexOf(
      document.activeElement as HTMLButtonElement,
    );
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? buttons.length - 1
          : (current + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) %
            buttons.length;
    buttons[next]?.focus();
  }
  function choose(action: "rename" | "remove") {
    setOpen(false);
    trigger.current?.focus();
    onAction({ ...item, action });
  }
  // WebKit may blur a focused item without focusing a mouse-clicked button.
  // Null destinations are handled by outside pointer/window events, so the
  // intended Remove/Rename/Move click is not discarded before it can run.
  return (
    <div
      ref={container}
      className="sidebar-item-actions"
      onBlur={(event) => {
        if (
          event.relatedTarget &&
          !event.currentTarget.contains(event.relatedTarget)
        )
          setOpen(false);
      }}
    >
      <button
        ref={trigger}
        className="sidebar-menu-trigger"
        type="button"
        disabled={disabled}
        aria-label={`Actions for ${item.kind} ${chatLabel(item.name, item.chatNumber)}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={`actions-${item.id}`}
        onClick={() => {
          const box = trigger.current?.getBoundingClientRect();
          if (box)
            setPosition({
              top: Math.min(
                box.bottom + 3,
                window.innerHeight - (onMove ? 135 : 95),
              ),
              left: Math.max(8, box.right - 175),
            });
          setOpen((current) => !current);
        }}
      >
        <span aria-hidden="true">⋯</span>
      </button>
      {open && (
        <div
          ref={menu}
          id={`actions-${item.id}`}
          role="menu"
          className="sidebar-item-menu"
          style={position}
          aria-label={`${item.kind === "project" ? "Project" : "Chat"} actions`}
          onKeyDown={keydown}
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => choose("rename")}
          >
            Rename {item.kind}
          </button>
          {onMove && (
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                trigger.current?.focus();
                onMove();
              }}
            >
              Move chat
            </button>
          )}
          <button
            type="button"
            role="menuitem"
            className="remove-menu-item"
            onClick={() => choose("remove")}
          >
            Remove {item.kind}
          </button>
        </div>
      )}
    </div>
  );
}

export default function ProjectWorkspace({
  connectionOverview,
  developerSettings,
}: {
  connectionOverview?: ReactNode;
  developerSettings?: ReactNode;
}) {
  const sidebar = useSidebarView();
  const [projects, setProjects] = useState<Project[]>([]);
  const [chats, setChats] = useState<Chat[]>([]);
  const [settings, setSettings] = useState<SearchSettings>(defaultSettings);
  const [clearGeneralSnapshot, setClearGeneralSnapshot] = useState<
    string[] | null
  >(null);
  const [clearGeneralNotice, setClearGeneralNotice] = useState(""),
    [clearGeneralError, setClearGeneralError] = useState("");
  const [generalChatsNeedRefresh, setGeneralChatsNeedRefresh] = useState(false);
  const [itemAction, setItemAction] = useState<ItemAction | null>(null);
  const [moveTarget, setMoveTarget] = useState<{
    chat: Chat;
    forPin: boolean;
  } | null>(null);
  const [mode, setMode] = useState<
    | "chat"
    | "project"
    | "createProject"
    | "settings"
    | "connections"
    | "format"
    | "removed"
    | "about"
    | "developer"
  >("chat");
  const [lastRemoved, setLastRemoved] = useState<ManagedItem | null>(null);
  const [restoring, setRestoring] = useState(false);
  const [mutating, setMutating] = useState(false);
  const [checkingRemoval, setCheckingRemoval] = useState(false);
  const mutationLock = useRef(false);
  const removalLookupLock = useRef(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [projectId, setProjectId] = useState("");
  const [chatId, setChatId] = useState("");
  const [searchMatch, setSearchMatch] = useState<ChatSearchMatch | null>(null);
  const [draftProject, setDraftProject] = useState<string | null>(null);
  const [draftSeed, setDraftSeed] = useState(0);
  const [recoveredDraft, setRecoveredDraft] = useState("");
  const [recoveredResearchError, setRecoveredResearchError] = useState("");
  const [recoveredCompletionKey, setRecoveredCompletionKey] = useState("");
  const consumeCompletion = useCallback(
    () => setRecoveredCompletionKey(""),
    [],
  );
  const [recoveredRankingProfileId, setRecoveredRankingProfileId] =
    useState("infer");
  const [composerSettings, setComposerSettings] = useState<
    "ranking" | "connections" | null
  >(null);
  const [setupOpen, setSetupOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [contentsRevision, setContentsRevision] = useState(0);
  const [draggedChatId, setDraggedChatId] = useState("");
  const [dropProjectId, setDropProjectId] = useState("");
  const [movingChatId, setMovingChatId] = useState("");
  const [moveNotice, setMoveNotice] = useState("");
  const [moveError, setMoveError] = useState("");
  const [failedMoveChatId, setFailedMoveChatId] = useState("");
  const workspaceBusy = mutating || checkingRemoval || Boolean(movingChatId);
  const [sidebarMoveRevisions, setSidebarMoveRevisions] = useState<
    Record<string, number>
  >({});
  const [busyChats, setBusyChats] = useState<Set<string>>(new Set());
  const research = useResearchRuns(rememberChat);
  const runningChats = new Set(
    Object.entries(research.runs)
      .filter(([, run]) => run.status === "running")
      .map(([id]) => id),
  );
  const busyOwners = useRef(new Map<string, Set<symbol>>());
  const dragChat = useRef("");
  const moveLock = useRef(false);
  const mounted = useMounted();
  const listEpoch = useRef(0);
  const connection = useConnections();
  const setup = useSetup();
  const clearDrag = useCallback(() => {
    dragChat.current = "";
    setDraggedChatId("");
    setDropProjectId("");
  }, []);
  const chatBusyChanged = useCallback(
    (id: string, busy: boolean, owner: symbol) => {
      const owners = busyOwners.current.get(id) ?? new Set<symbol>();
      if (busy) owners.add(owner);
      else owners.delete(owner);
      if (owners.size) busyOwners.current.set(id, owners);
      else busyOwners.current.delete(id);
      const nextBusy = owners.size > 0;
      setBusyChats((current) => {
        if (current.has(id) === nextBusy) return current;
        const next = new Set(current);
        if (nextBusy) next.add(id);
        else next.delete(id);
        return next;
      });
    },
    [],
  );
  useEffect(() => {
    const cancelOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") clearDrag();
    };
    window.addEventListener("dragend", clearDrag);
    window.addEventListener("drop", clearDrag);
    window.addEventListener("blur", clearDrag);
    window.addEventListener("keydown", cancelOnEscape);
    return () => {
      window.removeEventListener("dragend", clearDrag);
      window.removeEventListener("drop", clearDrag);
      window.removeEventListener("blur", clearDrag);
      window.removeEventListener("keydown", cancelOnEscape);
    };
  }, [clearDrag]);
  const firstSetup = useRef(true);
  useEffect(() => {
    if (firstSetup.current && setup.status && !setup.loading) {
      firstSetup.current = false;
      if (!setup.status.completed || !canSubmitResearch(setup.status))
        setSetupOpen(true);
    }
  }, [setup.status, setup.loading]);
  function openSetup() {
    setComposerSettings(null);
    setSetupOpen(true);
  }
  useEffect(() => {
    const controller = new AbortController();
    const epoch = listEpoch.current;
    setLoading(true);
    setError("");
    Promise.all([
      workspaceApi.projects(controller.signal),
      workspaceApi.allChats(controller.signal),
      workspaceApi.settings(controller.signal),
    ])
      .then(([nextProjects, nextChats, nextSettings]) => {
        if (controller.signal.aborted) return;
        if (epoch === listEpoch.current) {
          setProjects(nextProjects);
          setChats(nextChats);
        }
        setSettings(nextSettings);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [revision]);
  useEffect(() => {
    if (!contentsRevision) return;
    const controller = new AbortController();
    const epoch = listEpoch.current;
    Promise.all([
      workspaceApi.projects(controller.signal),
      workspaceApi.allChats(controller.signal),
    ])
      .then(([nextProjects, nextChats]) => {
        if (!controller.signal.aborted && epoch === listEpoch.current) {
          setProjects(nextProjects);
          setChats(nextChats);
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(error));
      });
    return () => controller.abort();
  }, [contentsRevision]);
  function newChat(project: string | null = null) {
    setSearchMatch(null);
    setChatId("");
    setRecoveredDraft("");
    setRecoveredRankingProfileId("infer");
    setDraftProject(project);
    setDraftSeed((value) => value + 1);
    setMode("chat");
  }
  function openChat(
    id: string,
    draft = "",
    rankingProfileId = "infer",
    researchError = "",
    completionKey = "",
  ) {
    setRecoveredCompletionKey(completionKey);
    setSearchMatch(null);
    setChatId(id);
    setRecoveredDraft(draft);
    setRecoveredResearchError(researchError);
    setRecoveredRankingProfileId(rankingProfileId);
    setMode("chat");
  }
  function rememberChat(chat: Chat) {
    if (!mounted.current) return;
    listEpoch.current += 1;
    setChats((items) => [chat, ...items.filter((item) => item.id !== chat.id)]);
    if (chat.project_id)
      setExpanded((current) => new Set(current).add(chat.project_id!));
    setContentsRevision((value) => value + 1);
  }
  function startChatDrag(event: DragEvent<HTMLButtonElement>, chat: Chat) {
    if (
      workspaceBusy ||
      chat.project_id !== null ||
      moveLock.current ||
      failedMoveChatId ||
      busyChats.has(chat.id) ||
      runningChats.has(chat.id)
    ) {
      event.preventDefault();
      return;
    }
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData(chatDragType, chat.id);
    dragChat.current = chat.id;
    setDraggedChatId(chat.id);
    setMoveNotice("");
    setMoveError("");
  }
  function acceptsChatDrag(event: DragEvent<HTMLDivElement>) {
    return (
      !workspaceBusy &&
      !moveLock.current &&
      !failedMoveChatId &&
      Boolean(dragChat.current) &&
      !(
        busyChats.has(dragChat.current) || runningChats.has(dragChat.current)
      ) &&
      chats.some(
        (chat) => chat.id === dragChat.current && chat.project_id === null,
      ) &&
      Array.from(event.dataTransfer.types).includes(chatDragType)
    );
  }
  function overProject(event: DragEvent<HTMLDivElement>, id: string) {
    if (!acceptsChatDrag(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    setDropProjectId(id);
  }
  async function dropChat(event: DragEvent<HTMLDivElement>, project: Project) {
    if (!acceptsChatDrag(event)) return;
    event.preventDefault();
    const id = dragChat.current;
    if (event.dataTransfer.getData(chatDragType) !== id) {
      clearDrag();
      return;
    }
    const chat = chats.find((item) => item.id === id);
    if (!chat) {
      clearDrag();
      return;
    }
    try {
      await moveChatToScope(chat, project.id);
    } catch {
      /* Recovery is shown in the sidebar. */
    }
  }
  function requestMove(chat: Chat, forPin = false) {
    if (
      workspaceBusy ||
      moveLock.current ||
      failedMoveChatId ||
      busyChats.has(chat.id) ||
      runningChats.has(chat.id)
    )
      return;
    setMoveTarget({ chat, forPin });
  }
  async function moveChatToScope(
    chat: Chat,
    target: string | null,
    newProject?: { name: string; description: string },
  ) {
    if (
      workspaceBusy ||
      moveLock.current ||
      failedMoveChatId ||
      busyChats.has(chat.id) ||
      runningChats.has(chat.id)
    )
      throw new Error("The workspace is busy with this chat. Please wait.");
    if (
      !newProject &&
      target !== null &&
      !projects.some((project) => project.id === target)
    )
      throw new Error(
        "The workspace destination is no longer available. Please reload.",
      );
    const id = chat.id;
    let destination =
      newProject?.name ??
      projects.find((project) => project.id === target)?.name ??
      "General Chats";
    let createdProject: Project | null = null;
    moveLock.current = true;
    setMovingChatId(id);
    clearDrag();
    setMoveError("");
    setMoveNotice(
      newProject
        ? `Creating “${destination}” and moving this chat…`
        : `Moving “${chatLabel(chat.title, chat.chat_number)}” to ${destination}…`,
    );
    try {
      if (newProject) {
        createdProject = await workspaceApi.createProject(
          newProject.name,
          newProject.description,
        );
        target = createdProject.id;
        destination = createdProject.name;
        if (mounted.current) {
          const project = createdProject;
          listEpoch.current += 1;
          setProjects((items) => [
            project,
            ...items.filter((item) => item.id !== project.id),
          ]);
          setExpanded((current) => new Set(current).add(project.id));
        }
      }
      const next = await workspaceApi.moveChat(id, target);
      if (mounted.current) {
        rememberChat(next.chat);
        setSidebarMoveRevisions((current) => ({
          ...current,
          [id]: (current[id] ?? 0) + 1,
        }));
        setMoveNotice(
          `“${chatLabel(next.chat.title, next.chat.chat_number)}” moved to ${destination}.`,
        );
        setMoveTarget(null);
      }
    } catch (error) {
      if (mounted.current) {
        setMoveNotice("");
        setFailedMoveChatId(id);
        setMoveError(
          `${createdProject ? `Project “${createdProject.name}” was created. ` : ""}${errorMessage(error)} Check the saved chat’s project before trying again.`,
        );
      }
      if (createdProject)
        throw new Error(
          `The workspace created “${createdProject.name}”, but could not confirm the chat’s move.`,
        );
      throw error;
    } finally {
      moveLock.current = false;
      if (mounted.current) setMovingChatId("");
    }
  }
  async function checkMovedChat() {
    if (!failedMoveChatId || moveLock.current) return;
    const id = failedMoveChatId;
    moveLock.current = true;
    setMovingChatId(id);
    try {
      const [next, savedProjects] = await Promise.all([
        workspaceApi.chat(id),
        workspaceApi.projects(),
      ]);
      if (mounted.current) {
        setProjects(savedProjects);
        rememberChat(next.chat);
        setSidebarMoveRevisions((current) => ({
          ...current,
          [id]: (current[id] ?? 0) + 1,
        }));
        setFailedMoveChatId("");
        setMoveError("");
        setMoveNotice(
          "Saved project checked. You can continue organizing your chats.",
        );
      }
    } catch (error) {
      if (mounted.current)
        setMoveError(
          `${errorMessage(error)} The saved project could not be checked. Try checking again when the connection is available.`,
        );
    } finally {
      moveLock.current = false;
      if (mounted.current) setMovingChatId("");
    }
  }
  useEffect(() => {
    if (
      failedMoveChatId &&
      !chats.some((chat) => chat.id === failedMoveChatId)
    ) {
      setFailedMoveChatId("");
      setMoveError("");
    }
  }, [chats, failedMoveChatId]);
  async function projectPin(kind: PinKind, id: string, pinned: boolean) {
    await changeWorkspace(async () => {
      await workspaceApi.pin(projectId, kind, id, pinned);
      if (mounted.current) setContentsRevision((value) => value + 1);
    });
  }
  async function projectReportPin(action: ReportPinAction) {
    await changeWorkspace(async () => {
      await applyReportPin(projectId, action);
      if (mounted.current) setContentsRevision((value) => value + 1);
    });
  }
  async function changeWorkspace(action: () => Promise<void>) {
    if (mutationLock.current || moveLock.current)
      throw new Error(
        "The workspace is already updating an item. Please wait.",
      );
    mutationLock.current = true;
    setMutating(true);
    try {
      await action();
    } finally {
      mutationLock.current = false;
      if (mounted.current) setMutating(false);
    }
  }
  async function requestItemAction(item: ItemAction) {
    if (mutationLock.current || moveLock.current || removalLookupLock.current)
      return;
    if (item.action === "rename") {
      setItemAction(item);
      return;
    }
    removalLookupLock.current = true;
    setCheckingRemoval(true);
    try {
      // Read the server preference each time, including after a restart or a
      // preference change in another window. Unavailable preferences confirm.
      const preferences = await workspaceApi
        .workspacePreferences()
        .catch(() => ({ confirm_removal: true }));
      if (!mounted.current) return;
      if (preferences.confirm_removal) setItemAction(item);
      else await manageItem(item, item.name);
    } catch (error) {
      if (mounted.current) setError(errorMessage(error));
    } finally {
      removalLookupLock.current = false;
      if (mounted.current) setCheckingRemoval(false);
    }
  }
  async function manageItem(
    item: ItemAction,
    name: string,
    skipConfirmation = false,
  ) {
    await changeWorkspace(async () => {
      if (item.action === "rename") {
        if (item.kind === "project") {
          const next = await workspaceApi.renameProject(item.id, name);
          if (mounted.current)
            setProjects((items) =>
              items.map((project) => (project.id === next.id ? next : project)),
            );
        } else {
          const next = await workspaceApi.renameChat(item.id, name);
          rememberChat(next.chat);
        }
      } else {
        if (skipConfirmation)
          await workspaceApi.saveWorkspacePreferences({
            confirm_removal: false,
          });
        if (item.kind === "project") await workspaceApi.removeProject(item.id);
        else await workspaceApi.removeChat(item.id);
        if (!mounted.current) return;
        if (item.kind === "project") {
          setProjects((items) =>
            items.filter((project) => project.id !== item.id),
          );
          setChats((items) =>
            items.filter((chat) => chat.project_id !== item.id),
          );
          if (activeProjectId === item.id) newChat();
        } else {
          setChats((items) => items.filter((chat) => chat.id !== item.id));
          if (mode === "chat" && chatId === item.id) newChat();
        }
        setLastRemoved(item);
      }
      if (!mounted.current) return;
      listEpoch.current += 1;
      setContentsRevision((value) => value + 1);
      setItemAction(null);
    });
  }
  function acceptGeneralChatRefresh(current: Chat[]) {
    setChats(current);
    // A failed response may still have removed the active general chat, or a
    // different window may have removed it before the snapshot was checked.
    if (
      chats.some((chat) => chat.id === chatId && chat.project_id === null) &&
      !current.some((chat) => chat.id === chatId)
    ) {
      if (mode === "chat") newChat();
      else setChatId("");
    }
  }
  async function refreshGeneralChats() {
    await changeWorkspace(async () => {
      listEpoch.current += 1;
      try {
        const current = await workspaceApi.allChats();
        if (!mounted.current) return;
        acceptGeneralChatRefresh(current);
        setGeneralChatsNeedRefresh(false);
        setClearGeneralError("");
        setClearGeneralNotice(
          "General chats refreshed. Review the list before clearing it.",
        );
        setContentsRevision((value) => value + 1);
      } catch (error) {
        if (mounted.current)
          setClearGeneralError(
            `${errorMessage(error)} Refresh general chats before trying again.`,
          );
      }
    });
  }
  async function clearGeneralChats(snapshot: string[]) {
    await changeWorkspace(async () => {
      try {
        const count = await workspaceApi.clearGeneralChats(snapshot, true);
        if (!mounted.current) return;
        listEpoch.current += 1;
        setChats((items) =>
          items.filter((chat) => !snapshot.includes(chat.id)),
        );
        if (snapshot.includes(chatId)) {
          if (mode === "chat") newChat();
          else setChatId("");
        }
        setClearGeneralSnapshot(null);
        setClearGeneralError("");
        setGeneralChatsNeedRefresh(false);
        setClearGeneralNotice(
          `${count} general ${count === 1 ? "chat" : "chats"} moved to Removed items. You can restore them for 30 days.`,
        );
        setContentsRevision((value) => value + 1);
      } catch (error) {
        if (!mounted.current) return;
        setClearGeneralSnapshot(null);
        setClearGeneralNotice("");
        setGeneralChatsNeedRefresh(true);
        setClearGeneralError(
          `${errorMessage(error)} Refresh general chats and confirm again before retrying.`,
        );
        if (error instanceof GeneralChatsChangedError) {
          listEpoch.current += 1;
          try {
            const current = await workspaceApi.allChats();
            if (mounted.current) {
              acceptGeneralChatRefresh(current);
              setGeneralChatsNeedRefresh(false);
              setClearGeneralError(
                `${error.message} The list has been refreshed. Review it and open Clear all again.`,
              );
            }
          } catch {
            /* Keep the explicit refresh action when the current list is unavailable. */
          }
        }
      }
    });
  }
  async function restoreItem(item: ManagedItem) {
    await changeWorkspace(async () => {
      if (item.kind === "project") await workspaceApi.restoreProject(item.id);
      else await workspaceApi.restoreChat(item.id);
      if (!mounted.current) return;
      setLastRemoved((current) =>
        current?.id === item.id && current.kind === item.kind ? null : current,
      );
      listEpoch.current += 1;
      setContentsRevision((value) => value + 1);
    });
  }
  async function permanentlyDeleteItem(item: ManagedItem) {
    await changeWorkspace(async () => {
      await workspaceApi.permanentlyDelete(item.kind, item.id, true);
      if (!mounted.current) return;
      // A project purge can include the previously removed chat as well.
      setLastRemoved((current) =>
        item.kind === "project" ||
        (current?.id === item.id && current.kind === item.kind)
          ? null
          : current,
      );
      listEpoch.current += 1;
      setContentsRevision((value) => value + 1);
    });
  }
  async function permanentlyDeleteAllItems(snapshot: string) {
    await changeWorkspace(async () => {
      await workspaceApi.permanentlyDeleteAll(snapshot, true);
      if (!mounted.current) return;
      setLastRemoved(null);
      listEpoch.current += 1;
      setContentsRevision((value) => value + 1);
    });
  }
  async function undoRemoval() {
    if (!lastRemoved || restoring || workspaceBusy) return;
    setRestoring(true);
    setError("");
    try {
      await restoreItem(lastRemoved);
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setRestoring(false);
    }
  }
  function toggleProject(id: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  const selectedProject = projects.find((project) => project.id === projectId);
  // Project-page navigation is retained while switching views, so resolve the
  // visible chat's own scope instead of reusing the last project-page ID.
  const activeProjectId =
    mode === "project"
      ? projectId
      : mode === "chat"
        ? chatId
          ? chats.find((chat) => chat.id === chatId)?.project_id
          : draftProject
        : null;
  const activeProject = projects.find(
    (project) => project.id === activeProjectId,
  );
  const projectChatDisabled =
    !activeProject ||
    loading ||
    workspaceBusy ||
    Boolean(chatId && failedMoveChatId === chatId);
  function newProjectChat() {
    if (projectChatDisabled || !activeProject) return;
    setExpanded((current) => new Set(current).add(activeProject.id));
    newChat(activeProject.id);
  }
  const standalone = chats.filter((chat) => chat.project_id === null);
  const generalChatBusy = standalone.some(
    (chat) => busyChats.has(chat.id) || runningChats.has(chat.id),
  );
  const clearGeneralDisabled =
    loading ||
    workspaceBusy ||
    generalChatBusy ||
    generalChatsNeedRefresh ||
    Boolean(failedMoveChatId) ||
    !standalone.length;
  function requestClearGeneralChats() {
    if (clearGeneralDisabled || clearGeneralSnapshot) return;
    setClearGeneralNotice("");
    setClearGeneralError("");
    setClearGeneralSnapshot(standalone.map((chat) => chat.id));
  }
  function chatButton(chat: Chat) {
    const draggable =
      chat.project_id === null &&
      !movingChatId &&
      !failedMoveChatId &&
      !(busyChats.has(chat.id) || runningChats.has(chat.id));
    return (
      <div
        className={`sidebar-chat-row ${draggedChatId === chat.id ? "is-dragging" : ""}`}
        key={chat.id}
      >
        <button
          className={`global-chat-item ${mode === "chat" && chat.id === chatId ? "selected" : ""}`}
          aria-current={
            mode === "chat" && chat.id === chatId ? "page" : undefined
          }
          type="button"
          draggable={draggable}
          title={`${chat.display_title}${chat.project_id === null ? " — Drag into a project or use Move chat." : ""}`}
          onDragStart={(event) => startChatDrag(event, chat)}
          onDragEnd={clearDrag}
          onClick={() => openChat(chat.id)}
        >
          <span className="sidebar-chat-identity-line">
            <ChatIdentity title={chat.title} number={chat.chat_number} />
            {runningChats.has(chat.id) && <RunningResearchIndicator />}
          </span>
          <PinTotals counts={chat.pin_counts} />
        </button>
        <SidebarActions
          item={{
            kind: "chat",
            id: chat.id,
            name: chat.title,
            chatNumber: chat.chat_number,
          }}
          onAction={(item) => void requestItemAction(item)}
          onMove={() => requestMove(chat)}
          disabled={
            workspaceBusy ||
            Boolean(movingChatId) ||
            busyChats.has(chat.id) ||
            runningChats.has(chat.id)
          }
        />
      </div>
    );
  }
  const composerLinks: ComposerLinks = {
    onOpenSettings: () => setComposerSettings("ranking"),
    onOpenConnections: () =>
      canSubmitResearch(setup.status)
        ? setComposerSettings("connections")
        : openSetup(),
    onRequireSetup: openSetup,
  };
  return (
    <div
      className={`app-shell project-app prompt-first-app${sidebar.hidden ? " sidebar-hidden" : ""}${sidebar.resizing ? " sidebar-resizing" : ""}`}
      style={sidebar.style}
    >
      <a className="skip-link" href="#project-main">
        Skip to content
      </a>
      {!sidebar.hidden && (
        <aside
          id="workspace-sidebar"
          className="sidebar project-sidebar"
          aria-label="Workspace navigation"
        >
          <button
            className="brand brand-button"
            onClick={() => newChat()}
            type="button"
            aria-label="Labcat new chat"
          >
            <LabcatMark />
            <span className="brand-copy">
              {brandName}
              <span className="brand-subtitle">{brandTagline}</span>
            </span>
          </button>
          <div className="sidebar-create-actions">
            <button
              className="sidebar-new-chat"
              type="button"
              onClick={() => newChat()}
            >
              <span aria-hidden="true">+</span>New chat
            </button>
            <button
              className="sidebar-create-project"
              type="button"
              onClick={() => setMode("createProject")}
            >
              <span aria-hidden="true">▱</span>Create project
            </button>
          </div>
          <WorkspaceSearch
            revision={revision + contentsRevision}
            onProject={(project) => {
              setProjectId(project.id);
              setExpanded((current) => new Set(current).add(project.id));
              setMode("project");
            }}
            onChat={(match) => {
              openChat(match.chat.id);
              setSearchMatch({ ...match });
            }}
          >
            <div className="sidebar-history">
              <SidebarSections
                projectAction={
                  <button
                    className="icon-button project-new-chat"
                    type="button"
                    aria-label={
                      activeProject
                        ? `New chat in ${activeProject.name}`
                        : "Select a project to start a chat"
                    }
                    title={
                      activeProject
                        ? `New chat in ${activeProject.name}`
                        : "Select a project to start a chat"
                    }
                    disabled={projectChatDisabled}
                    onClick={newProjectChat}
                  >
                    <span aria-hidden="true">+</span>
                  </button>
                }
                chatAction={
                  <button
                    type="button"
                    className="general-chats-clear"
                    aria-label="Clear all general chats"
                    title="Clear all general chats"
                    disabled={
                      clearGeneralDisabled || Boolean(clearGeneralSnapshot)
                    }
                    onClick={requestClearGeneralChats}
                  >
                    Clear all
                  </button>
                }
                projects={
                  <nav
                    className="project-list sidebar-section-list"
                    aria-label="Projects"
                    tabIndex={0}
                  >
                    {projects.map((project) => (
                      <div className="sidebar-project-group" key={project.id}>
                        <div
                          className={`sidebar-project-row ${dropProjectId === project.id ? "is-drop-target" : ""}`}
                          onDragEnter={(event) =>
                            overProject(event, project.id)
                          }
                          onDragOver={(event) => overProject(event, project.id)}
                          onDragLeave={(event) => {
                            if (
                              !event.currentTarget.contains(
                                event.relatedTarget as Node | null,
                              )
                            )
                              setDropProjectId((current) =>
                                current === project.id ? "" : current,
                              );
                          }}
                          onDrop={(event) => void dropChat(event, project)}
                        >
                          <button
                            type="button"
                            className="project-expand"
                            aria-label={`${expanded.has(project.id) ? "Collapse" : "Expand"} ${project.name}`}
                            aria-expanded={expanded.has(project.id)}
                            aria-controls={`project-chats-${project.id}`}
                            onClick={() => toggleProject(project.id)}
                          >
                            {expanded.has(project.id) ? "⌄" : "›"}
                          </button>
                          <button
                            type="button"
                            className={`project-nav-item ${project.id === activeProject?.id ? "selected" : ""}`}
                            aria-current={
                              mode === "project" && project.id === projectId
                                ? "page"
                                : undefined
                            }
                            onClick={() => {
                              setProjectId(project.id);
                              setExpanded((current) =>
                                new Set(current).add(project.id),
                              );
                              setMode("project");
                            }}
                          >
                            <span
                              className="project-initial"
                              aria-hidden="true"
                            >
                              {project.name.slice(0, 1).toUpperCase()}
                            </span>
                            <span className="project-nav-copy">
                              <span title={project.name}>{project.name}</span>
                            </span>
                            {dropProjectId === project.id ? (
                              <small className="project-counts">
                                Drop chat here
                              </small>
                            ) : (
                              <ProjectCounts project={project} />
                            )}
                          </button>
                          <SidebarActions
                            item={{
                              kind: "project",
                              id: project.id,
                              name: project.name,
                            }}
                            onAction={(item) => void requestItemAction(item)}
                            disabled={workspaceBusy}
                          />
                        </div>
                        {expanded.has(project.id) && (
                          <div
                            className="nested-chat-list"
                            id={`project-chats-${project.id}`}
                          >
                            {chats
                              .filter((chat) => chat.project_id === project.id)
                              .map(chatButton)}
                            {!chats.some(
                              (chat) => chat.project_id === project.id,
                            ) && <p className="sidebar-empty">No chats yet.</p>}
                          </div>
                        )}
                      </div>
                    ))}
                    {!projects.length && (
                      <p className="sidebar-empty">
                        Group related chats into a project.
                      </p>
                    )}
                  </nav>
                }
                chats={
                  <nav
                    className="all-chat-list sidebar-section-list"
                    aria-label="General chats"
                    tabIndex={0}
                  >
                    {standalone.map(chatButton)}
                    {!standalone.length && (
                      <p className="sidebar-empty">
                        Chats without a project appear here.
                      </p>
                    )}
                  </nav>
                }
              />
              <div className="sidebar-history-actions">
                {standalone.length > 0 && projects.length > 0 && (
                  <p className="sidebar-drag-hint">
                    Drag a general chat into a project.
                  </p>
                )}
                <p
                  className="chat-move-status"
                  role="status"
                  aria-live="polite"
                >
                  {moveNotice ||
                    (draggedChatId ? "Drop this chat onto a project." : "")}
                </p>
                {moveError && (
                  <div className="chat-move-error" role="alert">
                    <p>{moveError}</p>
                    <button
                      className="text-button"
                      type="button"
                      disabled={Boolean(movingChatId)}
                      onClick={() => void checkMovedChat()}
                    >
                      {movingChatId ? "Checking…" : "Check saved project"}
                    </button>
                  </div>
                )}
                <button
                  className="sidebar-removed-link"
                  type="button"
                  aria-current={mode === "removed" ? "page" : undefined}
                  onClick={() => setMode("removed")}
                >
                  Removed items
                </button>
              </div>
            </div>
          </WorkspaceSearch>
          <nav className="sidebar-bottom-nav" aria-label="Application">
            <button
              type="button"
              aria-current={mode === "chat" ? "page" : undefined}
              onClick={() => setMode("chat")}
            >
              <span aria-hidden="true">◌</span>Chat
            </button>
            <button
              type="button"
              aria-current={mode === "format" ? "page" : undefined}
              onClick={() => setMode("format")}
            >
              <span aria-hidden="true">⌁</span>Report Format
            </button>
            <button
              type="button"
              aria-current={mode === "settings" ? "page" : undefined}
              onClick={() => setMode("settings")}
            >
              <span aria-hidden="true">☷</span>Search Criterion
            </button>
            <button
              type="button"
              aria-current={mode === "connections" ? "page" : undefined}
              onClick={() => setMode("connections")}
            >
              <span aria-hidden="true">◈</span>Connections
            </button>
            {developerSettings && (
              <button
                type="button"
                aria-current={mode === "developer" ? "page" : undefined}
                onClick={() => setMode("developer")}
              >
                <span aria-hidden="true">⚙</span>Developer Settings
              </button>
            )}
          </nav>
          <div className="sidebar-footer">
            <span className="connection-dot is-connected" />
            <span>Local workspace</span>
          </div>
          <button
            className="sidebar-about-link"
            type="button"
            aria-current={mode === "about" ? "page" : undefined}
            onClick={() => setMode("about")}
          >
            Help &amp; about
          </button>
          {sidebar.resizer}
        </aside>
      )}
      <div className="workspace project-area">
        <header className="topbar">
          <div className="workspace-topbar-start">
            <SidebarViewControls
              hidden={sidebar.hidden}
              onToggle={sidebar.toggle}
              onReset={sidebar.reset}
            />
            <span className="workspace-breadcrumb">
              Research workspace <span className="breadcrumb-slash">/</span>
              <strong>
                {mode === "format"
                  ? "Report Format"
                  : mode === "settings"
                    ? "Search Criterion"
                    : mode === "connections"
                      ? "Connections"
                      : mode === "developer"
                        ? "Developer Settings"
                        : mode === "project"
                          ? "Project Contents"
                          : mode === "createProject"
                            ? "Create project"
                            : mode === "removed"
                              ? "Removed items"
                              : mode === "about"
                                ? "Help & about"
                                : "Chat"}
              </strong>
            </span>
          </div>
          <span className="preview-badge">Interview Prototype</span>
        </header>
        <main
          id="project-main"
          className={`project-main ${mode === "chat" ? "chat-main" : ""}`}
          tabIndex={-1}
        >
          {error && (
            <Notice
              error={error}
              onRetry={() => setRevision((value) => value + 1)}
              label="Reload workspace"
            />
          )}
          {clearGeneralNotice && (
            <div className="removal-notice general-chats-notice" role="status">
              <span>{clearGeneralNotice}</span>
              <button
                type="button"
                className="notice-dismiss"
                aria-label="Dismiss general chats notice"
                onClick={() => setClearGeneralNotice("")}
              >
                ×
              </button>
            </div>
          )}
          {clearGeneralError && (
            <div className="workspace-error general-chats-error" role="alert">
              <p>{clearGeneralError}</p>
              {generalChatsNeedRefresh && (
                <button
                  type="button"
                  className="quiet-button"
                  disabled={workspaceBusy}
                  onClick={() => void refreshGeneralChats()}
                >
                  Refresh general chats
                </button>
              )}
            </div>
          )}
          {lastRemoved && (
            <div className="removal-notice" role="status">
              <span>
                {lastRemoved.kind === "project" ? "Project" : "Chat"} “
                {chatLabel(lastRemoved.name, lastRemoved.chatNumber)}” moved to
                Removed items.
              </span>
              <button
                className="text-button"
                type="button"
                disabled={restoring || workspaceBusy}
                onClick={() => void undoRemoval()}
              >
                {restoring ? "Restoring…" : "Undo"}
              </button>
              <button
                className="notice-dismiss"
                type="button"
                aria-label="Dismiss removal notice"
                onClick={() => setLastRemoved(null)}
              >
                ×
              </button>
            </div>
          )}
          {(mode === "chat" || mode === "project") &&
            (canSubmitResearch(setup.status) && !setup.error ? (
              <ConnectionNotice
                onConfigure={() => setMode("connections")}
                readiness={setup.status}
                checking={setup.loading || setup.busy}
                unavailable={Boolean(setup.error)}
              />
            ) : (
              <aside
                className="connection-notice"
                aria-label="Required model connection"
              >
                <div>
                  <strong>
                    {setup.loading
                      ? "Checking your model connection…"
                      : "Connect a language model to begin research"}
                  </strong>
                  <p>
                    {setup.error ||
                      setup.status?.model.message ||
                      "Select a model and verify its account connection. Your saved workspace remains available."}
                  </p>
                </div>
                <div className="connection-notice-actions">
                  <button
                    type="button"
                    className="quiet-button"
                    disabled={connection.busy || setup.busy}
                    onClick={openSetup}
                  >
                    Open setup
                  </button>
                </div>
              </aside>
            ))}
          {mode === "connections" ? (
            setupOpen ? null : (
              <ConnectionsPanel
                overview={connectionOverview}
                onSetup={openSetup}
                onDone={() => setMode("chat")}
              />
            )
          ) : mode === "about" ? (
            <AboutPanel />
          ) : mode === "removed" ? (
            <RemovedItemsPanel
              revision={contentsRevision}
              projects={projects}
              workspaceBusy={workspaceBusy}
              onRestore={restoreItem}
              onPermanentlyDelete={permanentlyDeleteItem}
              onPermanentlyDeleteAll={permanentlyDeleteAllItems}
            />
          ) : mode === "developer" ? (
            developerSettings
          ) : mode === "format" ? (
            loading ? (
              <Loading label="Loading saved format…" />
            ) : (
              !error && (
                <ReportFormat
                  key={revision}
                  initial={settings}
                  onSaved={setSettings}
                />
              )
            )
          ) : mode === "createProject" ? (
            <NewProject
              onCancel={() => setMode("chat")}
              onReload={() => {
                setMode("chat");
                setRevision((value) => value + 1);
              }}
              onCreated={(project) => {
                listEpoch.current += 1;
                setProjects((items) => [project, ...items]);
                setProjectId(project.id);
                setExpanded((current) => new Set(current).add(project.id));
                setContentsRevision((value) => value + 1);
                setMode("project");
              }}
            />
          ) : mode === "settings" ? (
            loading ? (
              <Loading label="Loading saved preferences…" />
            ) : (
              !error && (
                <SearchCriterionPanel
                  onConnections={() => setMode("connections")}
                />
              )
            )
          ) : mode === "project" && selectedProject ? (
            <>
              <section className="project-heading">
                <div>
                  <p className="eyebrow">RESEARCH PROJECT</p>
                  <h1>{selectedProject.name}</h1>
                  {selectedProject.description && (
                    <p className="project-description">
                      {selectedProject.description}
                    </p>
                  )}
                  <PinTotals counts={selectedProject.pin_counts} />
                </div>
              </section>
              <DraftChat
                research={research}
                {...composerLinks}
                key={`project-composer-${selectedProject.id}`}
                project={selectedProject}
                onCreated={rememberChat}
                onOpen={openChat}
                onReload={() => setRevision((value) => value + 1)}
                loadingHistory={false}
                compact
              />
              <Contents
                key={`project-contents-${selectedProject.id}`}
                project={selectedProject}
                revision={contentsRevision}
                presentation={settings.presentation}
                onPin={projectPin}
                onReportPin={projectReportPin}
                disabled={workspaceBusy}
                onOpenChat={openChat}
              />
            </>
          ) : mode === "chat" && chatId ? (
            <ChatView
              research={research}
              {...composerLinks}
              initialRankingProfileId={recoveredRankingProfileId}
              key={chatId}
              chatId={chatId}
              identity={chats.find((chat) => chat.id === chatId)}
              projects={projects}
              presentation={settings.presentation}
              initialDraft={recoveredDraft}
              initialResearchError={recoveredResearchError}
              initialCompletionKey={recoveredCompletionKey}
              onCompletionConsumed={consumeCompletion}
              onChanged={rememberChat}
              onMoveRequested={requestMove}
              sidebarMoving={
                movingChatId === chatId || failedMoveChatId === chatId
              }
              sidebarMoveRevision={sidebarMoveRevisions[chatId] ?? 0}
              onBusyChange={chatBusyChanged}
              searchMatch={searchMatch?.chat.id === chatId ? searchMatch : null}
            />
          ) : mode === "chat" ? (
            <DraftChat
              research={research}
              {...composerLinks}
              key={draftSeed}
              project={
                projects.find((item) => item.id === draftProject) ?? null
              }
              onCreated={rememberChat}
              onOpen={openChat}
              onReload={() => setRevision((value) => value + 1)}
              loadingHistory={loading}
            />
          ) : (
            <Loading label="Loading project…" />
          )}
        </main>
      </div>
      {moveTarget && (
        <MoveChatDialog
          chat={moveTarget.chat}
          forPin={moveTarget.forPin}
          projects={projects}
          blocked={
            workspaceBusy ||
            busyChats.has(moveTarget.chat.id) ||
            runningChats.has(moveTarget.chat.id)
          }
          onCancel={() => setMoveTarget(null)}
          onMove={moveChatToScope}
          onCreateAndMove={(chat, name, description) =>
            moveChatToScope(chat, null, { name, description })
          }
        />
      )}
      {composerSettings && (
        <ComposerSettingsDialog
          section={composerSettings}
          onClose={() => setComposerSettings(null)}
        />
      )}
      <SetupWizard
        open={setupOpen}
        onClose={() => setSetupOpen(false)}
        onComplete={() => {
          setSetupOpen(false);
          setComposerSettings(null);
          setMode("chat");
        }}
      />
      {clearGeneralSnapshot && (
        <ClearGeneralChatsDialog
          snapshot={clearGeneralSnapshot}
          blocked={workspaceBusy || generalChatBusy}
          onCancel={() => setClearGeneralSnapshot(null)}
          onClear={clearGeneralChats}
        />
      )}
      {itemAction && (
        <ItemActionDialog
          key={`${itemAction.action}-${itemAction.id}`}
          item={itemAction}
          onCancel={() => setItemAction(null)}
          onSave={manageItem}
        />
      )}
    </div>
  );
}
// Abbreviate only the sidebar display; exact counts remain available on hover
// and to assistive technology, including beyond the usual K/M/B ranges.
function compactProjectCount(value: number) {
  const units = ["", "k", "M", "B", "T", "Q"];
  let scaled = value;
  let unit = 0;
  while (scaled >= 1000 && unit < units.length - 1) {
    scaled /= 1000;
    unit += 1;
  }
  let rounded =
    unit && scaled < 10 ? Math.round(scaled * 10) / 10 : Math.round(scaled);
  if (rounded >= 1000 && unit < units.length - 1) {
    rounded /= 1000;
    unit += 1;
  }
  return `${rounded}${units[unit]}`;
}

function ProjectCounts({ project }: { project: Project }) {
  const items = [
    [project.chat_count, "chat"],
    [project.pin_counts.reports, "report"],
    [project.pin_counts.sources, "source"],
  ] as const;
  const exact = items
    .map(
      ([count, label]) =>
        `${count.toLocaleString("en-US")} ${label}${count === 1 ? "" : "s"}`,
    )
    .join(" · ");
  return (
    <small className="project-counts" title={exact} aria-label={exact}>
      {items.flatMap(([count, label], index) => [
        ...(index
          ? [
              <span key={`${label}-separator`} aria-hidden="true">
                ·
              </span>,
            ]
          : []),
        <span key={label}>
          {compactProjectCount(count)} {label}
          {count === 1 ? "" : "s"}
        </span>,
      ])}
    </small>
  );
}

function PinTotals({
  counts,
}: {
  counts: { reports: number; sources: number };
}) {
  return (
    <small
      className="pin-totals"
      aria-label={`${counts.reports} pinned reports, ${counts.sources} pinned sources`}
    >
      {counts.reports} reports · {counts.sources} sources pinned
    </small>
  );
}

function ComposerSettingsDialog({
  section,
  onClose,
}: {
  section: "ranking" | "connections";
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const { busy } = useConnections();
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="composer-settings-dialog"
      aria-labelledby="composer-settings-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
    >
      <header className="composer-settings-header">
        <div>
          <p className="eyebrow">
            {section === "ranking" ? "SEARCH CRITERION" : "CONNECTIONS"}
          </p>
          <h2 id="composer-settings-title">
            {section === "ranking" ? "Ranking profiles" : "Model connections"}
          </h2>
        </div>
        <button
          type="button"
          className="quiet-button"
          disabled={busy}
          onClick={onClose}
        >
          Back to chat
        </button>
      </header>
      <div className="composer-settings-body">
        {section === "ranking" ? (
          <RankingProfilesPanel />
        ) : (
          <ConnectionsPanel />
        )}
      </div>
    </dialog>
  );
}

function AboutPanel() {
  const [about, setAbout] = useState<About | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    workspaceApi
      .about(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setAbout(value);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(error));
      });
    return () => controller.abort();
  }, []);
  return (
    <section className="about-page">
      <header className="settings-intro">
        <p className="eyebrow">HELP &amp; ABOUT</p>
        <h1>{brandName}</h1>
        <p className="about-brand-tagline">{brandTagline}</p>
        <p>A local workspace for public materials research.</p>
      </header>
      {error ? (
        <Notice error={error} />
      ) : !about ? (
        <Loading label="Loading application information…" />
      ) : (
        <section className="about-details card">
          <dl>
            <div>
              <dt>Version</dt>
              <dd>{about.version}</dd>
            </div>
            <div>
              <dt>Developer</dt>
              <dd>{about.developer}</dd>
            </div>
            <div>
              <dt>License</dt>
              <dd>{about.license}</dd>
            </div>
          </dl>
          {about.github_url && (
            <a
              href={about.github_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              View the project on GitHub
            </a>
          )}
        </section>
      )}
      <section className="about-help card">
        <h2>Your workspace</h2>
        <p>
          Start a chat directly, or create a project to keep related questions
          and pinned research together. Use each item’s three-dot menu to rename
          or remove it. Removed items can be restored from the sidebar.
        </p>
        <p>
          Search Criterion controls ranking priorities and source selection.
          Report Format controls report presentation and previews. Connections
          manages model accounts, compute choices and source credentials.
        </p>
      </section>
    </section>
  );
}

function NewProject({
  onCreated,
  onCancel,
  onReload,
}: {
  onCreated: (project: Project) => void;
  onCancel: () => void;
  onReload: () => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);
  const mounted = useMounted();
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim() || lock.current || error) return;
    lock.current = true;
    setSaving(true);
    setError("");
    try {
      const project = await workspaceApi.createProject(
        name.trim(),
        description.trim(),
      );
      if (mounted.current) onCreated(project);
    } catch (error) {
      if (mounted.current)
        setError(
          `${errorMessage(error)} Reload before retrying an interrupted save.`,
        );
    } finally {
      lock.current = false;
      if (mounted.current) setSaving(false);
    }
  }
  return (
    <section className="project-welcome">
      <span className="welcome-symbol" aria-hidden="true">
        ▱
      </span>
      <p className="eyebrow">RELATED QUESTIONS, TOGETHER</p>
      <h1>Create a research project.</h1>
      <p className="welcome-description">
        Projects organize chats and the reports or sources you pin.
        <br className="desktop-break" /> You can add existing chats at any time.
      </p>
      <form
        className="new-project-form card"
        onSubmit={submit}
        aria-label="Create project"
      >
        <h2>Project details</h2>
        <label htmlFor="project-name">Project name</label>
        <input
          id="project-name"
          autoFocus
          autoComplete="off"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="e.g. Oxide Materials"
          maxLength={120}
          required
          disabled={saving}
        />
        <label htmlFor="project-description">
          Description <span className="optional-label">optional</span>
        </label>
        <textarea
          id="project-description"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="What would you like to explore?"
          maxLength={2000}
          rows={3}
          disabled={saving}
        />
        {error && (
          <Notice error={error} onRetry={onReload} label="Reload projects" />
        )}
        <div className="form-actions">
          <button
            className="quiet-button"
            type="button"
            onClick={onCancel}
            disabled={saving}
          >
            Cancel
          </button>
          <button
            className="primary-button"
            type="submit"
            disabled={saving || Boolean(error) || !name.trim()}
          >
            {saving ? "Creating…" : "Create project"}
          </button>
        </div>
      </form>
    </section>
  );
}

function PromptComposer({
  searchStructures,
  onSearchStructuresChange,
  draft,
  onDraft,
  onSubmit,
  disabled,
  busy,
  id,
  welcome = false,
  rankingProfileId,
  onRankingProfileChange,
  onOpenSettings,
  onOpenConnections,
}: ComposerLinks & {
  searchStructures: boolean;
  onSearchStructuresChange: (value: boolean) => void;
  draft: string;
  onDraft: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  disabled: boolean;
  busy: boolean;
  id: string;
  welcome?: boolean;
  rankingProfileId: string;
  onRankingProfileChange: (id: string) => void;
}) {
  const connection = useConnections();
  const setup = useSetup();
  const blocked =
    !canSubmitResearch(setup.status) ||
    setup.loading ||
    setup.busy ||
    Boolean(setup.error) ||
    connection.loading ||
    connection.busy ||
    Boolean(connection.error);
  return (
    <>
      <form
        className={`message-composer ${welcome ? "welcome-composer" : ""}`}
        onSubmit={(event) => {
          if (blocked) {
            event.preventDefault();
            return;
          }
          onSubmit(event);
        }}
      >
        <label htmlFor={id} className="sr-only">
          Research question
        </label>
        <textarea
          id={id}
          autoFocus={welcome}
          rows={welcome ? 4 : 3}
          value={draft}
          onChange={(event) => onDraft(event.target.value)}
          placeholder="What would you like to explore?"
          maxLength={20000}
          disabled={busy}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
        />
        <div className="composer-actions">
          <ComposerControls
            rankingProfileId={rankingProfileId}
            onRankingProfileChange={onRankingProfileChange}
            disabled={busy || disabled}
            onOpenSettings={onOpenSettings}
            onOpenConnections={onOpenConnections}
          >
            <label className="composer-structure-option">
              <input
                type="checkbox"
                checked={searchStructures}
                disabled={busy || disabled}
                onChange={(event) =>
                  onSearchStructuresChange(event.target.checked)
                }
              />
              <span>Find reference structures</span>
              <span className="sr-only">
                Search selected public databases for available structures while
                preparing this report. Matching composition does not confirm the
                same phase.
              </span>
            </label>
          </ComposerControls>
          <button
            className="send-button"
            type="submit"
            disabled={!draft.trim() || disabled || busy || blocked}
            aria-label={busy ? "Research request in progress" : "Send message"}
          >
            {busy ? "Researching…" : "Send"}
            <span aria-hidden="true">↑</span>
          </button>
        </div>
      </form>
      <p className="composer-hint">Ctrl / ⌘ + Enter to send · Saved locally</p>
    </>
  );
}

function DraftChat({
  research,
  project,
  onCreated,
  onOpen,
  onReload,
  loadingHistory,
  compact = false,
  ...composerLinks
}: ComposerLinks & {
  research: WorkspaceResearch;
  project: Project | null;
  onCreated: (chat: Chat) => void;
  onOpen: (
    id: string,
    draft?: string,
    rankingProfileId?: string,
    researchError?: string,
    completionKey?: string,
  ) => void;
  onReload: () => void;
  loadingHistory: boolean;
  compact?: boolean;
}) {
  const setup = useSetup();
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [rankingProfileId, setRankingProfileId] = useState("infer");
  const [searchStructures, setSearchStructures] = useState(true);
  const [submission, setSubmission] = useState<ResearchSubmission | null>(null);
  const [progressChatId, setProgressChatId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const lock = useRef(false);
  const mounted = useMounted();
  async function send(event: FormEvent) {
    event.preventDefault();
    const content = draft.trim();
    if (
      !content ||
      lock.current ||
      uncertain ||
      !canSubmitResearch(setup.status) ||
      setup.loading ||
      setup.busy ||
      setup.error
    )
      return;
    lock.current = true;
    const currentSubmission = beginResearchSubmission();
    setSubmission(currentSubmission);
    setProgressChatId(null);
    setSaving(true);
    setError("");
    let created: Chat | null = null;
    try {
      created = project
        ? await workspaceApi.projectDraft(project.id)
        : await workspaceApi.startChat();
      onCreated(created);
      const pending = research.start(
        created.id,
        content,
        rankingProfileId,
        currentSubmission,
        searchStructures,
      );
      // Transfer to the saved chat immediately. The workspace keeps ownership
      // even when this draft or the new chat view is no longer mounted.
      if (mounted.current) {
        setProgressChatId(created.id);
        onOpen(created.id, "", rankingProfileId);
      }
      await pending;
    } catch (error) {
      if (mounted.current) {
        if (error instanceof ResearchRequestError) {
          setError(errorMessage(error));
          void setup.refresh().catch(() => undefined);
          if (error.setupRequired) composerLinks.onRequireSetup();
        }
        if (created) setError(errorMessage(error));
        else {
          setUncertain(true);
          setError(
            `${errorMessage(error)} A chat may have been created. Reload history before starting another.`,
          );
        }
      }
    } finally {
      lock.current = false;
      if (mounted.current) setSaving(false);
    }
  }
  return (
    <section
      className={compact ? "project-inline-composer" : "prompt-welcome"}
      aria-label={compact ? "Project research question" : undefined}
    >
      {!compact && (
        <>
          <LabcatMark className="welcome-brand-mark" />
          <p className="eyebrow">LABCAT</p>
          <h1>{brandTagline}</h1>
          <p className="welcome-description">
            Your companion for materials research.
            <br />
            Ask a question to start exploring.
          </p>
        </>
      )}
      {!compact && project && (
        <p className="draft-project-badge">
          This chat will be added to <strong>{project.name}</strong>.
        </p>
      )}
      <PromptComposer
        {...composerLinks}
        searchStructures={searchStructures}
        onSearchStructuresChange={setSearchStructures}
        rankingProfileId={rankingProfileId}
        onRankingProfileChange={setRankingProfileId}
        draft={draft}
        onDraft={setDraft}
        onSubmit={send}
        disabled={uncertain}
        busy={saving}
        id={compact ? `project-prompt-${project?.id}` : "first-prompt"}
        welcome
      />
      {saving && submission && (
        <ResearchProgress
          key={submission.runId}
          chatId={progressChatId}
          submission={submission}
        />
      )}
      {loadingHistory && (
        <p className="history-loading-label" role="status">
          Loading saved history…
        </p>
      )}
      {error && (
        <Notice error={error} onRetry={onReload} label="Reload chat history" />
      )}
    </section>
  );
}

function ChatView({
  research,
  chatId,
  identity,
  projects,
  presentation,
  initialDraft,
  initialResearchError,
  initialCompletionKey,
  onCompletionConsumed,
  onChanged,
  onMoveRequested,
  sidebarMoving,
  sidebarMoveRevision,
  onBusyChange,
  initialRankingProfileId,
  searchMatch,
  ...composerLinks
}: ComposerLinks & {
  research: WorkspaceResearch;
  initialRankingProfileId: string;
  chatId: string;
  identity?: Chat;
  projects: Project[];
  presentation: ReportPresentation;
  initialDraft: string;
  initialResearchError: string;
  initialCompletionKey: string;
  onCompletionConsumed: () => void;
  onChanged: (chat: Chat) => void;
  onMoveRequested: (chat: Chat, forPin?: boolean) => void;
  sidebarMoving: boolean;
  sidebarMoveRevision: number;
  onBusyChange: (id: string, busy: boolean, owner: symbol) => void;
  searchMatch: ChatSearchMatch | null;
}) {
  const setup = useSetup();
  const [failureNotice, setFailureNotice] = useState(initialResearchError);
  const [, setCompletionKey] = useState(initialCompletionKey);
  useEffect(() => {
    if (initialCompletionKey) onCompletionConsumed();
  }, [initialCompletionKey, onCompletionConsumed]);
  const [data, setData] = useState<ChatDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [draft, setDraft] = useState(initialDraft);
  const run = research.runs[chatId];
  const sending = run?.status === "running";
  const submission = run?.submission ?? null;
  const [rankingProfileId, setRankingProfileId] = useState(
    initialRankingProfileId,
  );
  const [searchStructures, setSearchStructures] = useState(true);
  const [uncertain, setUncertain] = useState(Boolean(initialDraft));
  const [mutating, setMutating] = useState(false);
  const mutationLock = useRef(false);
  const failedDraft = useRef(initialDraft);
  const mounted = useMounted();
  const busyOwner = useRef(Symbol("chat-view")).current;
  const history = useRef<HTMLDivElement>(null);
  const appliedSearchMatch = useRef<ChatSearchMatch | null>(null);
  useEffect(() => {
    if (!searchMatch) {
      appliedSearchMatch.current = null;
      return;
    }
    if (loading || !data || appliedSearchMatch.current === searchMatch) return;
    const target = [
      ...(history.current?.querySelectorAll<HTMLElement>(
        "[data-search-message], [data-search-report]",
      ) ?? []),
    ].find((element) =>
      searchMatch.match_field === "report"
        ? element.dataset.searchReport === searchMatch.report_id
        : element.dataset.searchMessage === searchMatch.message_id,
    );
    if (!target) return;
    appliedSearchMatch.current = searchMatch;
    for (
      let parent: HTMLElement | null = target;
      parent && parent !== history.current;
      parent = parent.parentElement
    ) {
      if (parent.tagName === "DETAILS")
        (parent as HTMLDetailsElement).open = true;
    }
    target.classList.add("is-search-match");
    target.tabIndex = -1;
    target.scrollIntoView?.({ block: "center" });
    target.focus({ preventScroll: true });
    return () => target.classList.remove("is-search-match");
  }, [searchMatch, loading, data]);
  useEffect(() => {
    onBusyChange(
      chatId,
      loading || sending || mutating || uncertain,
      busyOwner,
    );
    return () => {
      if (!mutationLock.current) onBusyChange(chatId, false, busyOwner);
    };
  }, [chatId, loading, sending, mutating, uncertain, onBusyChange, busyOwner]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    workspaceApi
      .chat(chatId, controller.signal)
      .then((next) => {
        if (controller.signal.aborted) return;
        setData(next);
        setUncertain(false);
        onChanged(next.chat);
        const lastUser = [...next.messages]
          .reverse()
          .find((message) => message.role === "user");
        if (failedDraft.current && lastUser?.content === failedDraft.current)
          setDraft("");
        failedDraft.current = "";
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setUncertain(true);
          setError(errorMessage(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [chatId, revision, sidebarMoveRevision, run?.revision]);
  useEffect(() => {
    if (run?.status === "completed") {
      setDraft("");
      setFailureNotice("");
    }
    if (run?.status === "failed") {
      setFailureNotice(run.error || "Research could not finish.");
      if (run.prompt) setDraft(run.prompt);
      if (run.setupRequired !== undefined) {
        void setup.refresh().catch(() => undefined);
        if (run.setupRequired) composerLinks.onRequireSetup();
      }
    }
  }, [run?.status, run?.error, run?.prompt, run?.submission.runId]);
  useEffect(() => {
    if (run?.status === "completed" && run.completionKey) {
      setCompletionKey(run.completionKey);
      research.consumeCompletion(chatId, run.submission.runId);
    }
  }, [
    chatId,
    run?.status,
    run?.completionKey,
    run?.submission.runId,
    research.consumeCompletion,
  ]);
  async function send(event: FormEvent) {
    event.preventDefault();
    const content = draft.trim();
    if (
      !content ||
      sending ||
      mutationLock.current ||
      uncertain ||
      loading ||
      sidebarMoving ||
      !data ||
      !canSubmitResearch(setup.status) ||
      setup.loading ||
      setup.busy ||
      setup.error
    )
      return;
    mutationLock.current = true;
    const currentSubmission = beginResearchSubmission();
    setCompletionKey("");
    setError("");
    setFailureNotice("");
    try {
      const next = await research.start(
        chatId,
        content,
        rankingProfileId,
        currentSubmission,
        searchStructures,
        data.reports,
      );
      if (mounted.current) {
        setCompletionKey(completedResearchKey(next, data.reports));
        setData(next);
        setDraft("");
        onChanged(next.chat);
      }
    } catch {
      /* Workspace-owned status preserves errors and reconciles transport failures. */
    } finally {
      mutationLock.current = false;
      if (!mounted.current) onBusyChange(chatId, false, busyOwner);
    }
  }
  async function pin(kind: PinKind, id: string, pinned: boolean) {
    if (mutationLock.current || sidebarMoving || !data) return;
    if (!data.chat.project_id) {
      onMoveRequested(data.chat, true);
      return;
    }
    mutationLock.current = true;
    setMutating(true);
    try {
      await workspaceApi.pin(data.chat.project_id, kind, id, pinned);
      const next = await workspaceApi.chat(chatId);
      if (mounted.current) {
        setData(next);
        onChanged(next.chat);
      }
    } finally {
      mutationLock.current = false;
      if (mounted.current) setMutating(false);
      else onBusyChange(chatId, false, busyOwner);
    }
  }
  async function reportPin(action: ReportPinAction) {
    if (mutationLock.current || sidebarMoving || !data) return;
    if (!data.chat.project_id) {
      onMoveRequested(data.chat, true);
      return;
    }
    mutationLock.current = true;
    setMutating(true);
    try {
      await applyReportPin(data.chat.project_id, action);
      const next = await workspaceApi.chat(chatId);
      if (mounted.current) {
        setData(next);
        onChanged(next.chat);
      }
    } finally {
      mutationLock.current = false;
      if (mounted.current) setMutating(false);
      else onBusyChange(chatId, false, busyOwner);
    }
  }
  const latestReport =
    data?.reports
      .filter((report) => ["complete", "partial"].includes(report.stage))
      .at(-1) ?? data?.reports.at(-1);
  const snapshotPins =
    data?.reports.flatMap((report) =>
      report.snapshot_pin ? [report.snapshot_pin] : [],
    ) ?? [];
  const latestMessage = latestReport
    ? data?.messages.find((message) => message.id === latestReport.message_id)
    : null;
  const latestRequest = latestMessage
    ? data?.messages
        .slice(0, data.messages.indexOf(latestMessage))
        .filter((message) => message.role === "user")
        .at(-1)
    : null;
  const latestMessageIndex =
    latestMessage && data ? data.messages.indexOf(latestMessage) : -1;
  const olderMessages =
    latestMessageIndex >= 0
      ? data!.messages
          .slice(0, latestMessageIndex)
          .filter((message) => message.id !== latestRequest?.id)
      : [];
  const currentMessages = data?.messages.slice(latestMessageIndex + 1) ?? [];
  const pastQueries = queryHistory(olderMessages, data?.reports ?? []);
  const groupedMessageIds = new Set(
    pastQueries.flatMap((turn) => [
      turn.question.id,
      ...turn.responses.map((message) => message.id),
    ]),
  );
  const ungroupedMessages = olderMessages.filter(
    (message) => !groupedMessageIds.has(message.id),
  );
  function renderMessage(
    message: ChatDetail["messages"][number],
    includeReport = true,
  ) {
    if (!data) return null;
    const report = includeReport
      ? data.reports.find((item) => item.id === message.report_id)
      : undefined;
    return (
      <article
        className={`message message-${message.role}`}
        key={message.id}
        data-search-message={message.id}
        data-search-report={message.report_id ?? undefined}
      >
        <div className="message-meta">
          <span className={`message-avatar ${message.role}`} aria-hidden="true">
            {message.role === "user" ? "Y" : <LabcatMark />}
          </span>
          <strong>{message.role === "user" ? "You" : brandName}</strong>
          {message.intake?.status === "clarification_required" && (
            <span className="intake-label">A little more detail</span>
          )}
          <SavedTime value={message.created_at} />
        </div>
        <div className="message-text">{message.content}</div>
        {report && (
          <ReportCard
            report={report}
            sources={data.sources}
            onPin={pin}
            onReportPin={reportPin}
            trackingPin={data.report_tracking}
            snapshotPins={snapshotPins}
            disabled={sending || mutating || uncertain || sidebarMoving}
            presentation={presentation}
            requiresProject={!data.chat.project_id}
          />
        )}
      </article>
    );
  }
  return (
    <div className="chat-view standalone-chat-view">
      <header className="conversation-header">
        <div>
          <span className="small-label">CONVERSATION</span>
          <h1>
            <ChatIdentity
              title={
                identity?.title ?? data?.chat.title ?? "Loading conversation…"
              }
              number={identity?.chat_number ?? data?.chat.chat_number}
            />
          </h1>
          {data && (
            <>
              <p className="chat-scope-label">
                {projects.find((project) => project.id === data.chat.project_id)
                  ?.name ??
                  (data.chat.project_id ? "Project chat" : "General Chats")}
              </p>
              <PinTotals counts={data.chat.pin_counts} />
            </>
          )}
        </div>
        <div className="mascot-conversation-meta">
          <span className="neutral-badge">Saved history</span>
          {pastQueries.length > 0 && (
            <button
              type="button"
              className="query-history-link"
              onClick={() => {
                const target =
                  history.current?.querySelector<HTMLElement>(".query-history");
                target?.scrollIntoView?.({ block: "start" });
                target?.focus({ preventScroll: true });
              }}
            >
              Earlier questions ({pastQueries.length})
            </button>
          )}
        </div>
      </header>
      <div
        ref={history}
        className="message-history"
        aria-label="Chat history"
        aria-busy={loading || sending}
      >
        {failureNotice && <Notice error={failureNotice} />}
        {searchMatch && searchMatch.match_field !== "title" && (
          <p className="chat-search-match-note">
            Found in saved{" "}
            {searchMatch.match_field === "message" ? "message" : "report"}:{" "}
            {searchMatch.snippet}
          </p>
        )}
        {loading && <Loading label="Loading conversation…" />}
        {!loading && !sending && data && !data.messages.length && (
          <div className="first-message">
            <h3>Continue with your question.</h3>
            <p>
              This chat is saved. Your report will identify the evidence used
              and any gaps.
            </p>
          </div>
        )}
        {!loading && latestReport && (
          <section
            className="latest-report-section"
            aria-label="Latest research report"
            data-search-report={latestReport.id}
            data-search-message={latestMessage?.id}
          >
            <div className="latest-report-label">
              <span className="status-square" />
              <span>LATEST RESEARCH REPORT</span>
            </div>
            {latestRequest && (
              <details
                key={`question-${latestReport.id}`}
                className="latest-question"
                open
                data-search-message={latestRequest.id}
              >
                <summary>
                  Research question{" "}
                  <QueryTime value={latestRequest.created_at} />
                </summary>
                <p>{latestRequest.content}</p>
              </details>
            )}
            <ReportCard
              key={latestReport.id}
              report={latestReport}
              sources={data?.sources ?? []}
              onPin={pin}
              onReportPin={reportPin}
              trackingPin={data?.report_tracking}
              snapshotPins={snapshotPins}
              disabled={sending || mutating || uncertain || sidebarMoving}
              presentation={presentation}
              requiresProject={!data?.chat.project_id}
            />
            {latestMessage &&
              !["complete", "partial"].includes(latestReport.stage) && (
                <p className="latest-response-note">{latestMessage.content}</p>
              )}
          </section>
        )}
        {!loading && (
          <QueryHistory
            turns={pastQueries}
            searchReportId={
              searchMatch?.match_field === "report"
                ? searchMatch.report_id
                : null
            }
            renderMessage={(message) => renderMessage(message, false)}
            renderReport={(report) => (
              <ReportCard
                savedFormat
                report={report}
                sources={data?.sources ?? []}
                onPin={pin}
                onReportPin={reportPin}
                trackingPin={data?.report_tracking}
                snapshotPins={snapshotPins}
                disabled={sending || mutating || uncertain || sidebarMoving}
                requiresProject={!data?.chat.project_id}
              />
            )}
          />
        )}
        {!loading && ungroupedMessages.length > 0 && (
          <details className="earlier-history">
            <summary>Other saved messages</summary>
            {ungroupedMessages.map((message) => renderMessage(message))}
          </details>
        )}
        {!loading && currentMessages.map((message) => renderMessage(message))}
        {sending && run?.prompt && (
          <div className="message message-user pending-research-question">
            <strong>Research question</strong>
            <p>{run.prompt}</p>
          </div>
        )}
        {sending && submission && (
          <ResearchProgress
            key={submission.runId}
            chatId={chatId}
            submission={submission}
          />
        )}
        {error && (
          <Notice
            error={error}
            onRetry={() => setRevision((value) => value + 1)}
            label="Reload chat"
          />
        )}
      </div>
      <PromptComposer
        {...composerLinks}
        searchStructures={searchStructures}
        onSearchStructuresChange={setSearchStructures}
        rankingProfileId={rankingProfileId}
        onRankingProfileChange={setRankingProfileId}
        draft={draft}
        onDraft={setDraft}
        onSubmit={send}
        disabled={loading || uncertain || mutating || sidebarMoving || !data}
        busy={sending}
        id={`prompt-${chatId}`}
      />
    </div>
  );
}

function SearchCriterionPanel({
  onConnections,
}: {
  onConnections: () => void;
}) {
  return (
    <section className="search-settings">
      <header className="settings-intro mascot-settings-header">
        <p className="eyebrow">RESEARCH PRIORITIES</p>
        <h1>Search Criterion</h1>
        <p>
          Choose a ranking profile and the public sources available to your
          research.
        </p>
      </header>
      <RankingProfilesPanel />
      <PublicSourcesPanel onConnections={onConnections} />
    </section>
  );
}

function PinButton({
  kind,
  id,
  pinned,
  onPin,
  disabled = false,
  requiresProject = false,
}: {
  kind: PinKind;
  id: string;
  pinned: boolean;
  onPin: PinAction;
  disabled?: boolean;
  requiresProject?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);
  const mounted = useMounted();
  async function toggle() {
    if (lock.current || disabled) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await onPin(kind, id, pinned);
    } catch (error) {
      if (mounted.current) setError(errorMessage(error));
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <div className="pin-control">
      <button
        type="button"
        className={`pin-button ${pinned ? "is-pinned" : ""}`}
        aria-pressed={pinned}
        disabled={busy || disabled}
        onClick={toggle}
      >
        <span aria-hidden="true">⌑</span>
        {busy
          ? "Saving…"
          : requiresProject
            ? "Choose project to pin"
            : pinned
              ? `Unpin ${kind}`
              : `Pin ${kind}`}
      </button>
      {error && (
        <p className="pin-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

const reportSections: { id: ReportExportSection; label: string }[] = [
  { id: "pi", label: "Summary" },
  { id: "audit", label: "Technical View" },
  { id: "sources", label: "Sources" },
];

export function ReportCard({
  report,
  sources,
  onPin,
  onReportPin,
  trackingPin,
  snapshotPins,
  disabled,
  chatTitle,
  chatNumber,
  onOpenChat,
  loadSources,
  presentation = defaultSettings.presentation,
  requiresProject = false,
  savedFormat = false,
}: {
  report: ResearchReport;
  sources: Source[];
  onPin: PinAction;
  onReportPin?: ReportPinChange;
  trackingPin?: ReportPin | null;
  snapshotPins?: ReportPin[];
  disabled?: boolean;
  chatTitle?: string;
  chatNumber?: number;
  onOpenChat?: () => void;
  loadSources?: (signal: AbortSignal) => Promise<Source[]>;
  presentation?: ReportPresentation;
  requiresProject?: boolean;
  savedFormat?: boolean;
}) {
  const cardId = useId();
  const card = useRef<HTMLElement>(null);
  const [nameLookupVisible, setNameLookupVisible] = useState(false);
  useEffect(() => {
    const check = () =>
      setNameLookupVisible(
        Boolean(card.current && !card.current.closest("details:not([open])")),
      );
    check();
    document.addEventListener("toggle", check, true);
    return () => document.removeEventListener("toggle", check, true);
  }, []);
  const recordedPresentation =
    savedReportPresentation(report.result) ?? presentation;
  const formatSource =
    savedFormat || report.pin?.mode === "snapshot" ? "saved" : "current";
  const preferredPresentation =
    formatSource === "saved" ? recordedPresentation : presentation;
  const presentationKey =
    formatSource === "current" ? JSON.stringify(presentation) : "";
  const [presented, setPresented] = useState<PresentedReport | null>(null);
  const [presentationBusy, setPresentationBusy] = useState(false);
  const [presentationError, setPresentationError] = useState("");
  const [presentationRetry, setPresentationRetry] = useState(0);
  const display =
    presented?.chat_id === report.chat_id &&
    presented.report_id === report.id &&
    presented.format_source === formatSource
      ? presented
      : null;
  const activePresentation = display?.presentation ?? recordedPresentation;
  const nameScope = `${report.chat_id}:${report.id}`;
  const [enabledNameScope, setEnabledNameScope] = useState("");
  const [lookedUpNames, setLookedUpNames] = useState<{
    scope: string;
    names: MaterialName[];
  } | null>(null);
  const namesSupported = display?.material_names !== undefined;
  useEffect(() => {
    if (namesSupported && nameLookupVisible) setEnabledNameScope(nameScope);
  }, [namesSupported, nameScope, nameLookupVisible]);
  useEffect(() => {
    if (enabledNameScope !== nameScope) return;
    const controller = new AbortController();
    chemicalNamesApi
      .load(report.chat_id, report.id, controller.signal)
      .then((names) => {
        if (!controller.signal.aborted)
          setLookedUpNames({ scope: nameScope, names });
      })
      .catch(() => {
        /* Names are optional; retained names and the report stay visible. */
      });
    return () => controller.abort();
  }, [enabledNameScope, nameScope, report.chat_id, report.id]);
  const materialNames = [
    ...new Map(
      [
        ...(display?.material_names ?? []),
        ...(lookedUpNames?.scope === nameScope ? lookedUpNames.names : []),
      ].map((item) => [
        `${item.kind}:${item.id}:${item.component_index ?? ""}`,
        item,
      ]),
    ).values(),
  ];
  const tables = savedReportTables(
      display ? { report_tables: display.report_tables } : report.result,
    ),
    snapshot = savedProfileSnapshot(report.result);
  const [outputs, setOutputs] = useState<ReportExportSection[]>(() => [
    ...preferredPresentation.outputs,
    "sources",
  ]);
  const [format, setFormat] = useState<ExportFormat>(
    preferredPresentation.format,
  );
  const [style, setStyle] = useState<ReportView | "sources">(() =>
    preferredPresentation.outputs.includes(preferredPresentation.style)
      ? preferredPresentation.style
      : preferredPresentation.outputs[0],
  );
  const [loadedSources, setLoadedSources] = useState<Source[] | null>(null);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [sourceError, setSourceError] = useState("");
  const [sourceRetry, setSourceRetry] = useState(0);
  useEffect(() => {
    if (!report.result && formatSource === "saved") {
      setPresented(null);
      setPresentationBusy(false);
      setPresentationError("");
      return;
    }
    const controller = new AbortController();
    setPresented(null);
    setPresentationBusy(true);
    setPresentationError("");
    reportPresentationApi
      .load(report.chat_id, report.id, formatSource, controller.signal)
      .then((next) => {
        if (controller.signal.aborted) return;
        setPresented(next);
        setFormat(next.presentation.format);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setPresentationError(
            "The updated layout is unavailable. The original saved report remains visible below.",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setPresentationBusy(false);
      });
    return () => controller.abort();
  }, [
    report.chat_id,
    report.id,
    Boolean(report.result),
    formatSource,
    presentationKey,
    presentationRetry,
  ]);
  useEffect(() => {
    if (style !== "sources" || !loadSources || !report.source_ids.length)
      return;
    const controller = new AbortController();
    setSourceLoading(true);
    setSourceError("");
    loadSources(controller.signal)
      .then((items) => {
        if (!controller.signal.aborted) setLoadedSources(items);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setSourceError(errorMessage(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setSourceLoading(false);
      });
    return () => controller.abort();
  }, [style, report.id, report.source_ids.length, loadSources, sourceRetry]);
  function toggleOutput(view: ReportExportSection) {
    setOutputs((current) =>
      current.includes(view)
        ? current.filter((item) => item !== view)
        : [...current, view],
    );
  }
  const selectedSources = (loadedSources ?? sources).filter((source) =>
    report.source_ids.includes(source.id),
  );
  const exportUrl = outputs.length
    ? reportExportUrl(report.chat_id, report.id, format, outputs) +
      (display?.format_source === "current" ? "&format_source=current" : "")
    : undefined;
  const downloadDisabled = presentationBusy || !outputs.length;
  const selectedSectionNames = reportSections
    .filter(({ id }) => outputs.includes(id))
    .map(({ label }) => label)
    .join(", ");
  const result =
    report.result && typeof report.result === "object"
      ? (report.result as Record<string, unknown>)
      : null;
  const hasCandidates = [result?.candidates, result?.candidate_leads].some(
    (items) => Array.isArray(items) && items.length > 0,
  );
  return (
    <section ref={card} className="research-report" aria-label={report.title}>
      <header className="report-heading">
        <div>
          <p className="eyebrow">
            SAVED REPORT <span className="report-stage">{report.stage}</span>
          </p>
          <h3>{report.title}</h3>
          {onOpenChat && (
            <button
              type="button"
              className="report-chat-link"
              onClick={onOpenChat}
            >
              From{" "}
              <ChatIdentity
                title={chatTitle ?? "conversation"}
                number={chatNumber}
              />{" "}
              <span aria-hidden="true">↗</span>
            </button>
          )}
        </div>
        <ReportPinControls
          report={report}
          trackingPin={trackingPin}
          snapshots={snapshotPins}
          onSnapshot={() => onPin("report", report.id, report.pinned)}
          onAction={onReportPin}
          disabled={disabled}
          requiresProject={requiresProject}
        />
      </header>
      {presentationBusy && (
        <p className="report-reformat-note" role="status">
          Formatting the saved evidence…
        </p>
      )}
      {presentationError && (
        <div className="report-appearance-toolbar">
          <span role="status">{presentationError}</span>
          <button
            type="button"
            disabled={presentationBusy}
            onClick={() => setPresentationRetry((value) => value + 1)}
          >
            Retry report layout
          </button>
        </div>
      )}
      <div className="report-output-toolbar">
        <div
          className="report-tabs"
          role="group"
          aria-label={`View and download sections for ${report.title}`}
        >
          {reportSections.map(({ id, label }) => (
            <div
              className={`report-tab${style === id ? " is-active" : ""}`}
              key={id}
            >
              <input
                type="checkbox"
                checked={outputs.includes(id)}
                onChange={() => toggleOutput(id)}
                aria-label={`Include ${label} in download`}
                title={`Include ${label} in download`}
              />
              <button
                type="button"
                aria-pressed={style === id}
                onClick={() => setStyle(id)}
              >
                {label}
                {id === "sources" && (
                  <>
                    {" "}
                    <span>{report.source_ids.length}</span>
                  </>
                )}
              </button>
            </div>
          ))}
        </div>
        <div className="report-download-controls">
          <label className="sr-only" htmlFor={`download-format-${cardId}`}>
            Download format for {report.title}
          </label>
          <select
            id={`download-format-${cardId}`}
            value={format}
            onChange={(event) => setFormat(event.target.value as ExportFormat)}
          >
            <option value="text">Plain text</option>
            <option value="json">JSON</option>
            <option value="pdf">PDF</option>
            <option value="docx">Word (.docx)</option>
          </select>
          <a
            className="report-download-link"
            href={exportUrl}
            aria-disabled={downloadDisabled}
            title={
              !outputs.length
                ? "Select at least one section to download"
                : undefined
            }
            onClick={(event) => {
              if (downloadDisabled) event.preventDefault();
            }}
            download
          >
            Download <span aria-hidden="true">↓</span>
            <span className="sr-only">
              {selectedSectionNames} as {format}
            </span>
          </a>
        </div>
      </div>
      <div className="report-body">
        {style === "sources" ? (
          sourceLoading ? (
            <Loading label="Loading source records…" />
          ) : sourceError ? (
            <Notice
              error={sourceError}
              onRetry={() => setSourceRetry((value) => value + 1)}
            />
          ) : (
            <>
              <SourceTable
                sources={selectedSources}
                onPin={onPin}
                disabled={disabled}
                requiresProject={requiresProject}
              />
              {selectedSources.length !== report.source_ids.length && (
                <p className="missing-sources">
                  Some source records are missing. Those references cannot be
                  verified.
                </p>
              )}
            </>
          )
        ) : (
          <>
            <ReportContent
              content={
                style === "pi"
                  ? (display?.pi_summary ?? report.pi_summary)
                  : (display?.technical_audit ?? report.technical_audit)
              }
              view={style}
              table={style === "pi" ? tables?.summary : tables?.technical}
              candidateLeads={result?.candidate_leads}
              materialNames={materialNames}
              references={display?.references}
              presentation={activePresentation}
              structureScope={
                hasCandidates
                  ? { chatId: report.chat_id, reportId: report.id }
                  : undefined
              }
            />
          </>
        )}
      </div>
      <div className="report-disclosures">
        {style !== "sources" && (
          <details className="report-audit-disclosure">
            <summary>Full saved audit & original report</summary>
            <div>
              <p>
                Original evidence, identifiers, ranking inputs and generated
                report text. Reformatting does not change this archive.
              </p>
              <details>
                <summary>Original Summary</summary>
                <pre>{report.pi_summary}</pre>
              </details>
              <details>
                <summary>Original Technical View</summary>
                <pre>{report.technical_audit}</pre>
              </details>
              <details>
                <summary>Evidence and execution data (JSON)</summary>
                <pre tabIndex={0}>
                  {JSON.stringify(
                    report.result ?? {
                      note: "Structured evidence data is unavailable for this historical report.",
                    },
                    null,
                    activePresentation.layout?.json_indent ?? 2,
                  )}
                </pre>
              </details>
            </div>
          </details>
        )}
        <ReportProfile snapshot={snapshot} table={tables?.technical} />
      </div>
      <footer className="report-footer">
        <span>
          {report.source_ids.length === 0
            ? "No cited sources · No verified material recommendations"
            : "Downloads preserve source references and caveats"}{" "}
          ·{" "}
          {outputs.length
            ? `${selectedSectionNames} selected for download`
            : "Select at least one section to download"}
        </span>
        <SavedTime value={report.created_at} />
      </footer>
    </section>
  );
}

function ReportProfile({
  snapshot,
  table,
}: {
  snapshot: ProfileSnapshot | null;
  table?: ReportTable;
}) {
  if (!snapshot)
    return (
      <p className="report-profile-unavailable">
        Ranking profile snapshot unavailable for this saved report. Its recorded
        report text is preserved.
      </p>
    );
  const selected = Object.entries(snapshot.importance).filter(
    ([, weight]) => weight > 0,
  );
  return (
    <details className="report-profile-snapshot">
      <summary>
        <span>Ranking profile used</span>
        <strong>{snapshot.name}</strong>
        <small>Saved with this report</small>
      </summary>
      <div>
        <p>
          These are the criteria submitted for this report. Changes in Search
          Criterion apply to future research.
        </p>
        {snapshot.selection_reason && <p>{snapshot.selection_reason}</p>}
        {snapshot.minimum_band_gap_ev !== undefined && (
          <p>
            Minimum band gap:{" "}
            {snapshot.minimum_band_gap_ev === null ? (
              "Not set"
            ) : (
              <>
                {snapshot.minimum_band_gap_ev} eV ·{" "}
                {(snapshot.importance.band_gap ?? 0) > 0
                  ? "Screening preference"
                  : "Inactive; Band gap importance is zero or unselected"}
              </>
            )}
            . Only validated source values are compared; unknown values remain
            unknown.
          </p>
        )}
        {snapshot.target_band_gap_ev != null && (
          <p className="report-target-preference">
            Target band gap: {snapshot.target_band_gap_ev} eV · Ranking
            preference for this report.{" "}
            {snapshot.band_gap_tolerance_ev != null && (
              <>
                Preference tolerance: {snapshot.band_gap_tolerance_ev} eV, used
                as a soft ranking scale.{" "}
              </>
            )}
            These preferences are separate from measured material properties.
            {(snapshot.importance.band_gap ?? 0) <= 0 &&
              " Inactive; Band gap importance is zero or unselected."}
          </p>
        )}
        <dl>
          {selected.map(([id, weight]) => (
            <div key={id}>
              <dt>
                {table?.columns.find((column) => column.id === id)?.label ??
                  id.replaceAll("_", " ")}
              </dt>
              <dd>
                Importance {weight.toFixed(2)}
                {snapshot.normalized_weights?.[id] !== undefined && (
                  <>
                    {" "}
                    · {(snapshot.normalized_weights[id] * 100).toFixed(1)}% of
                    ranking weight
                  </>
                )}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </details>
  );
}

function SourceTable({
  sources,
  onPin,
  disabled,
  requiresProject,
}: {
  sources: Source[];
  onPin: PinAction;
  disabled?: boolean;
  requiresProject?: boolean;
}) {
  return (
    <div className="source-table-wrap">
      <table className="source-table">
        <caption className="sr-only">Source records and provenance</caption>
        <thead>
          <tr>
            <th scope="col">Source</th>
            <th scope="col">Access & provenance</th>
            <th scope="col">Project pin</th>
          </tr>
        </thead>
        <tbody>
          {sources.length ? (
            sources.map((source) => {
              const url = publicLink(source);
              return (
                <tr key={source.id}>
                  <td>
                    {url ? (
                      <a href={url} target="_blank" rel="noopener noreferrer">
                        {source.title}
                        <span className="sr-only"> (opens a new tab)</span>{" "}
                        <span aria-hidden="true">↗</span>
                      </a>
                    ) : (
                      <strong>{source.title}</strong>
                    )}
                    <small>{source.source_name}</small>
                  </td>
                  <td>
                    <span>{source.access_scope}</span>
                    <small>
                      {source.kind === "discovery_reference"
                        ? "Public reference · review required"
                        : source.provenance_status}
                    </small>
                    {source.kind === "discovery_reference" && (
                      <small>Not used as material property evidence.</small>
                    )}
                    {!url && <small>Public link unavailable</small>}
                  </td>
                  <td>
                    <PinButton
                      kind="source"
                      id={source.id}
                      pinned={source.pinned}
                      onPin={onPin}
                      disabled={disabled}
                      requiresProject={requiresProject}
                    />
                  </td>
                </tr>
              );
            })
          ) : (
            <tr>
              <td colSpan={3}>
                <div className="no-sources">
                  <span aria-hidden="true">▤</span>
                  <strong>No source records yet</strong>
                  <p>
                    No approved public evidence records are attached to this
                    view. Review the report for retrieval limits or missing
                    data.
                  </p>
                </div>
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export function Contents({
  project,
  revision,
  onPin,
  onReportPin,
  onOpenChat,
  presentation,
  disabled = false,
}: {
  project: Project;
  revision: number;
  presentation: ReportPresentation;
  onPin: PinAction;
  onReportPin?: ReportPinChange;
  onOpenChat: (id: string) => void;
  disabled?: boolean;
}) {
  const [data, setData] = useState<ProjectContents | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    workspaceApi
      .contents(project.id, controller.signal)
      .then((next) => {
        if (!controller.signal.aborted) setData(next);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [project.id, revision, retry]);
  if (loading) return <Loading label="Loading Project Contents…" />;
  if (error)
    return (
      <Notice error={error} onRetry={() => setRetry((value) => value + 1)} />
    );
  if (!data) return null;
  return (
    <section className="project-contents">
      <header className="contents-heading">
        <div>
          <p className="eyebrow">PINNED ACROSS CONVERSATIONS</p>
          <h2>Project Contents</h2>
          <p>Reports and resources you have pinned in {project.name}.</p>
        </div>
        <span className="contents-mark" aria-hidden="true">
          ⌑
        </span>
      </header>
      <section aria-labelledby="pinned-reports-title">
        <div className="contents-section-heading">
          <h3 id="pinned-reports-title">Pinned reports</h3>
          <span>{data.reports.length}</span>
        </div>
        {data.reports.length ? (
          <div className="pinned-reports">
            {data.reports.map((report) => (
              <ReportCard
                key={report.pin?.id ?? report.id}
                report={report}
                presentation={presentation}
                sources={data.sources}
                onPin={onPin}
                onReportPin={onReportPin}
                disabled={disabled}
                trackingPin={
                  data.reports.find(
                    (item) =>
                      item.chat_id === report.chat_id &&
                      item.pin?.mode === "latest",
                  )?.pin
                }
                snapshotPins={data.reports.flatMap((item) =>
                  item.pin?.mode === "snapshot" ? [item.pin] : [],
                )}
                chatTitle={
                  data.chats.find((chat) => chat.id === report.chat_id)?.title
                }
                chatNumber={
                  data.chats.find((chat) => chat.id === report.chat_id)
                    ?.chat_number
                }
                onOpenChat={() => onOpenChat(report.chat_id)}
                loadSources={async (signal) =>
                  (
                    await workspaceApi.detail(
                      project.id,
                      report.chat_id,
                      signal,
                    )
                  ).sources
                }
              />
            ))}
          </div>
        ) : (
          <div className="contents-empty">
            <span aria-hidden="true">⌑</span>
            <div>
              <h3>Keep a useful report close.</h3>
              <p>
                Pin a response in any chat. It will appear here, with a link
                back to its conversation.
              </p>
            </div>
          </div>
        )}
      </section>
      <section
        className="pinned-sources"
        aria-labelledby="pinned-sources-title"
      >
        <div className="contents-section-heading">
          <h3 id="pinned-sources-title">Pinned resources</h3>
          <span>{data.sources.length}</span>
        </div>
        <SourceTable sources={data.sources} onPin={onPin} disabled={disabled} />
      </section>
    </section>
  );
}
