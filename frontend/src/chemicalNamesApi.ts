import { publicLink } from "./workspaceApi";
import type { Source } from "./workspaceApi";

export interface MaterialName {
  kind: "lead" | "material";
  id: string;
  formula: string;
  name: string;
  url: string;
  source_name: string;
  parent_formula?: string;
  component_index?: number;
}
const symbols = new Set(
  "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr".split(
    " ",
  ),
);
export function chemicalFormulaSignature(value: string): string | undefined {
  if (!value || value.length > 160) return;
  const parts = [...value.matchAll(/([A-Z][a-z]?)([1-9][0-9]*)?/g)];
  if (
    parts.map((part) => part[0]).join("") !== value ||
    new Set(parts.map((part) => part[1])).size !== parts.length ||
    parts.some(
      (part) =>
        !symbols.has(part[1]) || !Number.isSafeInteger(Number(part[2] ?? 1)),
    )
  )
    return;
  return parts
    .map((part) => `${part[1]}:${part[2] ?? "1"}`)
    .sort()
    .join(";");
}
export function chemicalComponentFormulas(value: string): string[] {
  if (!value || value.length > 160) return [];
  const parts = value
    .replace(/[₀₁₂₃₄₅₆₇₈₉]/g, (digit) => String("₀₁₂₃₄₅₆₇₈₉".indexOf(digit)))
    .replace(/[∕⁄]/g, "/")
    .split(/[/@]/);
  if (parts.length < 2 || parts.length > 3) return [];
  const formulas = parts.map((part) =>
    part.trim().replace(/([A-Za-z])\s+(?=\d)/g, "$1"),
  );
  return formulas.every(
    (formula) =>
      (chemicalFormulaSignature(formula)?.split(";").length ?? 0) >= 2 &&
      (/[0-9]/.test(formula) || /[A-Z][a-z]/.test(formula)),
  )
    ? formulas
    : [];
}
export function chemicalNameKey(item: MaterialName): string {
  return `${item.kind}:${item.id}:${item.component_index ?? ""}`;
}
function invalid() {
  return new Error("Chemical names are unavailable.");
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw invalid();
  return value as Record<string, unknown>;
}
function text(value: unknown, max: number): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    value.length <= max &&
    value.trim() === value &&
    !/[\p{Cc}\p{Cf}]/u.test(value)
  );
}
export function parseMaterialNames(value: unknown): MaterialName[] {
  if (!Array.isArray(value) || value.length > 112) throw invalid();
  const names = value.map((entry) => {
    const item = object(entry);
    const component =
      item.component_index !== undefined || item.parent_formula !== undefined;
    if (
      Object.keys(item).length !== (component ? 8 : 6) ||
      !["lead", "material"].includes(String(item.kind)) ||
      !text(item.id, 160) ||
      !text(item.formula, 160) ||
      !chemicalFormulaSignature(item.formula) ||
      !text(item.name, 200) ||
      !text(item.source_name, 120) ||
      !text(item.url, 2048)
    )
      throw invalid();
    if (item.kind === "lead" && !/^lead-[a-f0-9]{24}$/.test(item.id))
      throw invalid();
    if (
      component &&
      (item.kind !== "lead" ||
        !text(item.parent_formula, 160) ||
        typeof item.component_index !== "number" ||
        !Number.isInteger(item.component_index) ||
        item.component_index < 1 ||
        item.component_index > 3 ||
        chemicalFormulaSignature(
          chemicalComponentFormulas(item.parent_formula)[
            item.component_index - 1
          ] ?? "",
        ) !== chemicalFormulaSignature(item.formula))
    )
      throw invalid();
    let url: URL;
    try {
      url = new URL(item.url);
    } catch {
      throw invalid();
    }
    if (
      url.href.length > 2048 ||
      url.protocol !== "https:" ||
      !publicLink({ url: item.url, access_scope: "public" } as Source) ||
      url.port ||
      !url.hostname.includes(".") ||
      /[:\[\]]/.test(url.hostname) ||
      /^[0-9.]+$/.test(url.hostname)
    )
      throw invalid();
    return {
      kind: item.kind,
      id: item.id,
      formula: item.formula,
      name: item.name,
      url: url.href,
      source_name: item.source_name,
      ...(component
        ? {
            parent_formula: item.parent_formula,
            component_index: item.component_index,
          }
        : {}),
    } as MaterialName;
  });
  if (new Set(names.map(chemicalNameKey)).size !== names.length)
    throw invalid();
  return names;
}
export function safeMaterialNames(value: unknown): MaterialName[] {
  try {
    return parseMaterialNames(value);
  } catch {
    return [];
  }
}
export function parseChemicalNamesResponse(
  value: unknown,
  chatId: string,
  reportId: string,
): MaterialName[] {
  const item = object(value);
  if (
    Object.keys(item).length !== 3 ||
    item.chat_id !== chatId ||
    item.report_id !== reportId
  )
    throw invalid();
  return parseMaterialNames(item.material_names);
}
export const chemicalNamesApi = {
  async load(
    chatId: string,
    reportId: string,
    signal: AbortSignal,
  ): Promise<MaterialName[]> {
    const controller = new AbortController(),
      abort = () => controller.abort();
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) controller.abort();
    const timeout = window.setTimeout(abort, 20000);
    const options = {
      signal: controller.signal,
      credentials: "same-origin" as const,
      cache: "no-store" as const,
      redirect: "error" as const,
    };
    try {
      if (controller.signal.aborted) throw invalid();
      const sessionResponse = await fetch("/api/session", {
        ...options,
        headers: { Accept: "application/json" },
      });
      if (!sessionResponse.ok) throw invalid();
      const session = object(await sessionResponse.json());
      if (
        typeof session.csrf_token !== "string" ||
        !/^[A-Za-z0-9_-]{20,200}$/.test(session.csrf_token) ||
        controller.signal.aborted
      )
        throw invalid();
      const response = await fetch(
        `/api/chats/${encodeURIComponent(chatId)}/reports/${encodeURIComponent(reportId)}/chemical-names`,
        {
          ...options,
          method: "POST",
          body: "{}",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-CSRF-Token": session.csrf_token,
          },
        },
      );
      if (!response.ok || controller.signal.aborted) throw invalid();
      return parseChemicalNamesResponse(
        await response.json(),
        chatId,
        reportId,
      );
    } finally {
      window.clearTimeout(timeout);
      signal.removeEventListener("abort", abort);
    }
  },
};
