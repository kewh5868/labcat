export type ReportStyle = "pi" | "audit";

export const rankingFields = [
  ["stability", "Thermodynamic stability"],
  ["band_gap", "Band gap"],
  ["element_screen", "Element screen"],
  ["simplicity", "Composition simplicity"],
  ["evidence_quality", "Evidence quality"],
] as const;

type RankingKey = (typeof rankingFields)[number][0];

export interface StatusReport {
  application: string;
  version: string;
  stage: string;
  style: ReportStyle;
  message: string;
  compute: string;
  provider: string;
  constraints: string[];
  candidates: unknown[];
  limitations: string[];
  implemented?: string[];
  next_steps?: string[];
  configuration?: {
    ranking: Record<RankingKey, number>;
    presentation: { style: string; format: string; terminology: string };
    provider: string;
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isTextList(value: unknown): value is string[] {
  return (
    Array.isArray(value) && value.every((item) => typeof item === "string")
  );
}

function parseStatus(value: unknown): StatusReport {
  const invalid = () =>
    new Error("The application returned an unsupported status response.");
  if (!isRecord(value)) throw invalid();
  for (const field of [
    "application",
    "version",
    "stage",
    "message",
    "compute",
    "provider",
  ]) {
    if (typeof value[field] !== "string") throw invalid();
  }
  if (value.style !== "pi" && value.style !== "audit") throw invalid();
  if (!isTextList(value.constraints) || !isTextList(value.limitations))
    throw invalid();
  if (!Array.isArray(value.candidates)) throw invalid();
  for (const field of ["implemented", "next_steps"]) {
    if (value[field] !== undefined && !isTextList(value[field]))
      throw invalid();
  }
  if (value.configuration !== undefined) {
    const config = value.configuration;
    if (
      !isRecord(config) ||
      !isRecord(config.ranking) ||
      !isRecord(config.presentation)
    ) {
      throw invalid();
    }
    for (const [key] of rankingFields) {
      const weight = config.ranking[key];
      if (
        typeof weight !== "number" ||
        !Number.isFinite(weight) ||
        weight < 0 ||
        weight > 1
      ) {
        throw invalid();
      }
    }
    for (const field of ["style", "format", "terminology"]) {
      if (typeof config.presentation[field] !== "string") throw invalid();
    }
    if (typeof config.provider !== "string") throw invalid();
  }
  return value as unknown as StatusReport;
}

export async function fetchStatus(
  style: ReportStyle,
  signal: AbortSignal,
): Promise<StatusReport> {
  const response = await fetch(`/api/status?style=${style}`, {
    signal,
    headers: { Accept: "application/json" },
    cache: "no-store",
    redirect: "error",
  });
  if (!response.ok)
    throw new Error(
      `The status service returned an error (${response.status}).`,
    );
  const report = parseStatus(await response.json());
  if (report.style !== style)
    throw new Error("The status service returned a different report style.");
  return report;
}
