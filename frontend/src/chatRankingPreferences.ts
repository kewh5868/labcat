import { useCallback, useEffect, useState } from "react";
import type { ResearchReport } from "./workspaceApi";

const preferenceKey = "labcat-chat-ranking-v1";
const limit = 200;
const validId = (value: unknown): value is string =>
  typeof value === "string" && /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$/.test(value);
type Choices = Record<string, string>;

function readChoices(): Choices {
  try {
    const raw = window.localStorage.getItem(preferenceKey);
    if (!raw || raw.length > 60_000) return {};
    const saved: unknown = JSON.parse(raw);
    if (!saved || typeof saved !== "object" || Array.isArray(saved)) return {};
    return Object.fromEntries(
      Object.entries(saved)
        .filter(([chatId, profileId]) => validId(chatId) && validId(profileId))
        .slice(-limit),
    );
  } catch {
    return {};
  }
}

// Store only UI choices, never report evidence or credentials. Chat UUIDs keep
// different workspaces on the same origin separate. Storage is optional.
export function useChatRankingPreferences() {
  const [choices, setChoices] = useState(readChoices);
  useEffect(() => {
    try {
      window.localStorage.setItem(preferenceKey, JSON.stringify(choices));
    } catch {
      /* Restricted webviews still retain choices for this session. */
    }
  }, [choices]);
  const select = useCallback(
    (chatId: string, profileId: string, restore = false) => {
      if (!validId(chatId) || !validId(profileId)) return;
      setChoices((current) => {
        if (restore && Object.hasOwn(current, chatId)) return current;
        if (current[chatId] === profileId) return current;
        return Object.fromEntries(
          [
            ...Object.entries(current).filter(([id]) => id !== chatId),
            [chatId, profileId],
          ].slice(-limit),
        );
      });
    },
    [],
  );
  return { choices, select };
}

function object(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function recordedRankingChoice(
  reports: ResearchReport[],
): string | null {
  const latest = [...reports].sort(
    (a, b) =>
      b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id),
  )[0];
  const execution = object(object(latest?.result)?.execution);
  const selection = object(execution?.ranking_selection);
  if (!selection) return null;
  if (
    selection.requested_profile_id === "infer" ||
    ["inferred", "semantic_inferred", "fallback", "continued"].includes(
      String(selection.mode),
    )
  )
    return "infer";
  if (selection.mode === "explicit" && validId(selection.requested_profile_id))
    return selection.requested_profile_id;
  // An inferred/continued snapshot is evidence of a past choice, not a request
  // to make that saved profile an explicit preference on the next question.
  return null;
}
