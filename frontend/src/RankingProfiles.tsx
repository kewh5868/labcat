import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  matchingPreset,
  rankingProfilesApi,
  relativeWeights,
  validBandGapTarget,
  validMinimumBandGap,
} from "./rankingProfilesApi";
import type {
  Attribute,
  ProfileInput,
  RankingProfile,
  RankingProfiles,
} from "./rankingProfilesApi";
import RankingProfileHelp from "./RankingProfileHelp";
import "./rankingProfiles.css";
const copy = (profile: RankingProfile): ProfileInput => ({
  name: profile.name,
  material_class: profile.material_class,
  application: profile.application,
  importance: { ...profile.importance },
  ...(profile.minimum_band_gap_ev !== undefined
    ? { minimum_band_gap_ev: profile.minimum_band_gap_ev }
    : {}),
  ...(profile.target_band_gap_ev !== undefined
    ? { target_band_gap_ev: profile.target_band_gap_ev }
    : {}),
  ...(profile.band_gap_tolerance_ev !== undefined
    ? { band_gap_tolerance_ev: profile.band_gap_tolerance_ev }
    : {}),
});
const selectedCategories = (
  attributes: Attribute[],
  importance: Record<string, number>,
): string[] => [
  ...new Set(
    attributes
      .filter((attribute) => attribute.id in importance)
      .map((attribute) => attribute.category),
  ),
];
export default function RankingProfilesPanel() {
  const [data, setData] = useState<RankingProfiles | null>(null);
  const [selected, setSelected] = useState("");
  const [draft, setDraft] = useState<ProfileInput | null>(null);
  const [expandedCategories, setExpandedCategories] = useState<string[]>([]);
  const categoryListId = useId();
  const categories = [
    ...new Set(
      data?.catalog.attributes.map((attribute) => attribute.category) ?? [],
    ),
  ];
  const anyCategoryExpanded = categories.some((category) =>
    expandedCategories.includes(category),
  );
  const [targetMode, setTargetMode] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const [customContext, setCustomContext] = useState(false);
  const lock = useRef(false),
    mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    rankingProfilesApi
      .list(controller.signal)
      .then((next) => {
        if (!controller.signal.aborted) {
          setData(next);
          setSelected(next.active_profile_id);
          const activeProfile = next.profiles.find(
            (profile) => profile.id === next.active_profile_id,
          )!;
          setDraft(copy(activeProfile));
          setTargetMode(activeProfile.target_band_gap_ev != null);
          setExpandedCategories(
            selectedCategories(
              next.catalog.attributes,
              activeProfile.importance,
            ),
          );
          setCustomContext(
            !activeProfile.preset &&
              (!next.catalog.material_classes.some(
                (item) => item.id === activeProfile.material_class,
              ) ||
                !next.catalog.applications.some(
                  (item) => item.id === activeProfile.application,
                )),
          );
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setError(
            error instanceof Error
              ? error.message
              : "Could not load ranking profiles.",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [revision]);
  const saved = data?.profiles.find((profile) => profile.id === selected);
  const changed = Boolean(
    draft && (!saved || JSON.stringify(copy(saved)) !== JSON.stringify(draft)),
  );
  const relative = relativeWeights(draft?.importance ?? {});
  const active = data?.profiles.find(
    (profile) => profile.id === data.active_profile_id,
  );
  const validProfile =
    draft &&
    draft.name.trim() &&
    draft.material_class.trim() &&
    draft.application.trim() &&
    Object.values(draft.importance).some((value) => value > 0) &&
    Object.values(draft.importance).every(
      (value) => Number.isFinite(value) && value >= 0 && value <= 1,
    );
  const validMinimum = validMinimumBandGap(draft?.minimum_band_gap_ev);
  const validTarget =
    validBandGapTarget(
      draft?.target_band_gap_ev,
      draft?.band_gap_tolerance_ev,
    ) &&
    (!targetMode || draft?.target_band_gap_ev != null);
  const valid = validProfile && validMinimum && validTarget;
  const bandGapActive = (draft?.importance.band_gap ?? 0) > 0;
  function update<K extends keyof ProfileInput>(
    key: K,
    value: ProfileInput[K],
  ) {
    setDraft((current) => (current ? { ...current, [key]: value } : current));
    setNotice("");
  }
  function choose(id: string) {
    const profile = data?.profiles.find((item) => item.id === id);
    if (profile && data) {
      setSelected(id);
      setDraft(copy(profile));
      setTargetMode(profile.target_band_gap_ev != null);
      setExpandedCategories(
        selectedCategories(data.catalog.attributes, profile.importance),
      );
      setCustomContext(
        !profile.preset &&
          (!data.catalog.material_classes.some(
            (item) => item.id === profile.material_class,
          ) ||
            !data.catalog.applications.some(
              (item) => item.id === profile.application,
            )),
      );
      setNotice(
        "Ranking profile loaded. Choose “Use ranking profile” to set the workspace default.",
      );
    }
  }
  function chooseBandGapMode(target: boolean) {
    setTargetMode(target);
    setDraft((current) =>
      current
        ? { ...current, target_band_gap_ev: null, band_gap_tolerance_ev: null }
        : current,
    );
    setNotice("");
  }
  function changeTarget(value: number | null) {
    setDraft((current) =>
      current
        ? {
            ...current,
            target_band_gap_ev: value,
            band_gap_tolerance_ev:
              value === null ? null : (current.band_gap_tolerance_ev ?? 0.2),
          }
        : current,
    );
    setNotice("");
  }
  function newProfile() {
    if (!data || !draft || busy) return;
    let name = "New ranking profile";
    let suffix = 2;
    while (data.profiles.some((profile) => profile.name === name))
      name = `New ranking profile ${suffix++}`;
    setSelected("");
    setDraft({ ...draft, name, importance: { ...draft.importance } });
    setNotice(
      "New ranking profile started with the current priorities. Give it a name, customize it, then save it for later.",
    );
  }
  function chooseContext(materialClass: string, application?: string) {
    if (!data) return;
    if (materialClass === "__custom__" || application === "__custom__") {
      setCustomContext(true);
      setNotice(
        "Enter custom context labels and adjust the selected priorities. Retrieval remains limited to supported adapters.",
      );
      return;
    }
    const matching = matchingPreset(data.profiles, materialClass, application);
    if (matching) {
      setDraft((current) =>
        current
          ? {
              ...current,
              material_class: matching.material_class,
              application: matching.application,
              importance: { ...matching.importance },
              minimum_band_gap_ev: matching.minimum_band_gap_ev ?? null,
              target_band_gap_ev: matching.target_band_gap_ev ?? null,
              band_gap_tolerance_ev: matching.band_gap_tolerance_ev ?? null,
            }
          : current,
      );
      setTargetMode(matching.target_band_gap_ev != null);
      setExpandedCategories(
        selectedCategories(data.catalog.attributes, matching.importance),
      );
      setCustomContext(false);
      setNotice(
        "Matching preset priorities loaded into this ranking profile. Your profile name is kept; save when ready.",
      );
    }
  }
  function attributeRow(attribute: Attribute) {
    if (!draft) return null;
    const enabled = attribute.id in draft.importance;
    return (
      <div
        className={`attribute-row ${enabled ? "enabled" : ""}`}
        key={attribute.id}
      >
        <div className="attribute-description">
          <label>
            <input
              type="checkbox"
              checked={enabled}
              disabled={busy}
              onChange={(event) => {
                const importance = { ...draft.importance };
                if (event.target.checked) importance[attribute.id] = 0.5;
                else delete importance[attribute.id];
                update("importance", importance);
              }}
            />
            <strong>{attribute.label}</strong>
          </label>
          <p>{attribute.description}</p>
          <span
            className={`attribute-availability ${attribute.supported ? "supported" : ""}`}
          >
            {attribute.supported
              ? "Numeric and literature assessment"
              : "Literature assessment"}
          </span>
          <p className="attribute-note">{attribute.availability_note}</p>
        </div>
        <div className="attribute-importance">
          <label className="sr-only" htmlFor={`importance-${attribute.id}`}>
            {attribute.label} importance
          </label>
          <input
            id={`importance-${attribute.id}`}
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={
              Number.isFinite(draft.importance[attribute.id])
                ? draft.importance[attribute.id]
                : 0
            }
            disabled={busy || !enabled}
            onChange={(event) =>
              update("importance", {
                ...draft.importance,
                [attribute.id]: Number(event.target.value),
              })
            }
          />
          <label
            className="sr-only"
            htmlFor={`importance-number-${attribute.id}`}
          >
            {attribute.label} importance value
          </label>
          <input
            id={`importance-number-${attribute.id}`}
            type="number"
            min="0"
            max="1"
            step="0.01"
            inputMode="decimal"
            value={
              !enabled
                ? ""
                : Number.isNaN(draft.importance[attribute.id])
                  ? ""
                  : draft.importance[attribute.id]
            }
            disabled={busy || !enabled}
            onChange={(event) =>
              update("importance", {
                ...draft.importance,
                [attribute.id]:
                  event.target.value === ""
                    ? Number.NaN
                    : Number(event.target.value),
              })
            }
          />
          <small>
            {enabled
              ? `${(relative[attribute.id] * 100).toFixed(1)}% relative`
              : "Not selected"}
          </small>
        </div>
      </div>
    );
  }
  async function activate() {
    if (lock.current || !data || !saved || changed) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await rankingProfilesApi.activate(saved.id);
      if (mounted.current) {
        setData({ ...data, active_profile_id: saved.id });
        setNotice(
          "Workspace default updated. Chats can infer or select a different ranking profile. Previous reports keep their recorded settings.",
        );
      }
    } catch (error) {
      if (mounted.current)
        setError(
          error instanceof Error
            ? error.message
            : "Could not apply ranking profile. Reload saved ranking profiles.",
        );
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function save() {
    if (lock.current || !draft || !valid || !data) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const profile = await rankingProfilesApi.save(
        draft,
        saved && !saved.preset ? saved.id : undefined,
      );
      if (mounted.current) {
        setData({
          ...data,
          profiles: [
            ...data.profiles.filter((item) => item.id !== profile.id),
            profile,
          ],
        });
        setSelected(profile.id);
        setDraft(copy(profile));
        setNotice(
          profile.id === data.active_profile_id
            ? "Workspace default updated. Previous reports keep their recorded settings."
            : "Ranking profile saved. Select it in a chat or choose “Use ranking profile” to make it the workspace default.",
        );
      }
    } catch (error) {
      if (mounted.current)
        setError(
          error instanceof Error
            ? error.message
            : "Could not save ranking profile. Reload saved ranking profiles before retrying.",
        );
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <section
      className="ranking-profile-editor settings-card card"
      aria-labelledby="ranking-profile-heading"
    >
      <header className="settings-card-heading">
        <div>
          <p className="eyebrow">SAVED RESEARCH PRIORITIES</p>
          <RankingProfileHelp>
            <h2 id="ranking-profile-heading">Ranking profiles</h2>
          </RankingProfileHelp>
        </div>
        <span className="neutral-badge">Independent importance</span>
      </header>
      <p className="settings-description">
        Create a ranking profile from a preset or define a custom material
        class, application and set of properties. Save named ranking profiles to
        reuse them later. Set each importance independently from 0 to 1;
        relative contributions are calculated for you. Chats can infer or select
        a profile; the workspace default is used when inference has no clear
        match.
      </p>
      {loading && <p role="status">Loading ranking profiles…</p>}
      {error && (
        <div className="workspace-error" role="alert">
          <p>{error}</p>
          <button
            type="button"
            className="quiet-button"
            disabled={busy}
            onClick={() => setRevision((value) => value + 1)}
          >
            Reload saved ranking profiles
          </button>
        </div>
      )}
      {data && draft && !loading && (
        <>
          <div className="profile-picker">
            <div>
              <label htmlFor="ranking-profile">Ranking profile</label>
              <select
                id="ranking-profile"
                value={selected}
                disabled={busy}
                onChange={(event) => choose(event.target.value)}
              >
                {!saved && (
                  <option value="">New ranking profile · unsaved</option>
                )}
                <optgroup label="Saved ranking profiles">
                  {data.profiles
                    .filter((profile) => !profile.preset)
                    .map((profile) => (
                      <option key={profile.id} value={profile.id}>
                        {profile.name}
                        {profile.id === data.active_profile_id
                          ? " · active"
                          : ""}
                      </option>
                    ))}
                </optgroup>
                <optgroup label="Preset ranking profiles">
                  {data.profiles
                    .filter((profile) => profile.preset)
                    .map((profile) => (
                      <option key={profile.id} value={profile.id}>
                        {profile.name}
                        {profile.id === data.active_profile_id
                          ? " · active"
                          : ""}
                      </option>
                    ))}
                </optgroup>
              </select>
            </div>
            <div className="profile-picker-actions">
              <button
                type="button"
                className="quiet-button"
                disabled={busy || Boolean(error)}
                onClick={newProfile}
              >
                New ranking profile
              </button>
              <p className="active-profile-label">
                Active ranking profile:{" "}
                <strong>
                  {
                    data.profiles.find(
                      (profile) => profile.id === data.active_profile_id,
                    )?.name
                  }
                </strong>
              </p>
            </div>
          </div>
          <div className="profile-fields">
            <div>
              <label htmlFor="profile-name">Ranking profile name</label>
              <input
                id="profile-name"
                maxLength={120}
                disabled={busy}
                value={draft.name}
                onChange={(event) => update("name", event.target.value)}
              />
            </div>
            <div>
              <label htmlFor="material-class">Material class</label>
              <select
                id="material-class"
                value={
                  customContext ||
                  !data.catalog.material_classes.some(
                    (item) => item.id === draft.material_class,
                  )
                    ? "__custom__"
                    : draft.material_class
                }
                disabled={busy}
                onChange={(event) => chooseContext(event.target.value)}
              >
                {data.catalog.material_classes
                  .filter((item) => item.id !== "custom")
                  .map((item) => (
                    <option value={item.id} key={item.id}>
                      {item.label}
                    </option>
                  ))}
                <option value="__custom__">Custom class / application</option>
              </select>
            </div>
            <div>
              <label htmlFor="profile-application">Application</label>
              <select
                id="profile-application"
                value={customContext ? "__custom__" : draft.application}
                disabled={busy || customContext}
                onChange={(event) =>
                  chooseContext(draft.material_class, event.target.value)
                }
              >
                {data.catalog.applications
                  .filter((item) =>
                    data.profiles.some(
                      (profile) =>
                        profile.preset &&
                        profile.material_class === draft.material_class &&
                        profile.application === item.id,
                    ),
                  )
                  .map((item) => (
                    <option value={item.id} key={item.id}>
                      {item.label}
                    </option>
                  ))}
                <option value="__custom__">Custom application</option>
              </select>
            </div>
          </div>
          {customContext && (
            <div className="custom-context-fields">
              <div>
                <label htmlFor="custom-material-class">
                  Custom material class label
                </label>
                <input
                  id="custom-material-class"
                  maxLength={120}
                  disabled={busy}
                  value={draft.material_class}
                  onChange={(event) =>
                    update("material_class", event.target.value)
                  }
                />
              </div>
              <div>
                <label htmlFor="custom-application">
                  Custom application label
                </label>
                <input
                  id="custom-application"
                  maxLength={120}
                  disabled={busy}
                  value={draft.application}
                  onChange={(event) =>
                    update("application", event.target.value)
                  }
                />
              </div>
            </div>
          )}
          <p className="profile-scope-note">
            Research can address any material class. Source coverage and
            available properties vary; a profile does not supply missing
            measurements. Properties marked “Not yet scored” receive no evidence
            credit. Templates are editable starting points, not validated
            application recommendations.
          </p>
          {(bandGapActive || targetMode) && (
            <section
              className="profile-minimum-gap profile-target-gap"
              aria-labelledby="band-gap-preference-label"
            >
              <div className="profile-target-fields">
                <label
                  id="band-gap-preference-label"
                  htmlFor="band-gap-preference"
                >
                  Band gap ranking
                </label>
                <select
                  id="band-gap-preference"
                  value={targetMode ? "target" : "wider"}
                  disabled={busy}
                  onChange={(event) =>
                    chooseBandGapMode(event.target.value === "target")
                  }
                >
                  <option value="wider">Prefer wider band gaps</option>
                  <option value="target">Match a target band gap</option>
                </select>
                {targetMode && (
                  <>
                    <label htmlFor="target-band-gap">
                      Target band gap (eV)
                    </label>
                    <input
                      id="target-band-gap"
                      type="number"
                      min="0"
                      max="100"
                      step="any"
                      inputMode="decimal"
                      placeholder="Choose a target"
                      value={
                        draft.target_band_gap_ev == null ||
                        Number.isNaN(draft.target_band_gap_ev)
                          ? ""
                          : draft.target_band_gap_ev
                      }
                      disabled={busy}
                      aria-describedby="target-band-gap-help"
                      aria-invalid={!validTarget}
                      onChange={(event) =>
                        changeTarget(
                          event.target.value === ""
                            ? null
                            : Number(event.target.value),
                        )
                      }
                    />
                    <label htmlFor="band-gap-tolerance">
                      Preference tolerance (eV)
                    </label>
                    <input
                      id="band-gap-tolerance"
                      type="number"
                      min="0"
                      max="100"
                      step="any"
                      inputMode="decimal"
                      placeholder="Default: 0.2"
                      value={
                        draft.band_gap_tolerance_ev == null ||
                        Number.isNaN(draft.band_gap_tolerance_ev)
                          ? ""
                          : draft.band_gap_tolerance_ev
                      }
                      disabled={busy || draft.target_band_gap_ev == null}
                      aria-describedby="target-band-gap-help"
                      aria-invalid={!validTarget}
                      onChange={(event) =>
                        update(
                          "band_gap_tolerance_ev",
                          event.target.value === ""
                            ? null
                            : Number(event.target.value),
                        )
                      }
                    />
                  </>
                )}
              </div>
              <div>
                <p id="target-band-gap-help">
                  {targetMode
                    ? "Rank validated source values by closeness to your target. Tolerance sets how quickly preference credit decreases: a difference of one tolerance receives half the band-gap credit. The default is 0.2 eV; adjust it for your question. This is a ranking preference, separate from measurement uncertainty."
                    : "Give more band-gap preference credit to wider validated source values. Choose a target when closeness to a particular gap matters."}{" "}
                  Unknown values remain unknown.
                </p>
                {!bandGapActive && (
                  <p className="profile-constraint-inactive">
                    Inactive while Band gap importance is zero or unselected.
                    These preferences are retained.
                  </p>
                )}
                {!validTarget && (
                  <p className="profile-validation" role="alert">
                    Choose a target from 0 to 100 eV and a tolerance greater
                    than 0 up to 100 eV. A blank tolerance uses the application
                    default.
                  </p>
                )}
              </div>
            </section>
          )}
          {(bandGapActive || draft.minimum_band_gap_ev != null) && (
            <section
              className="profile-minimum-gap"
              aria-labelledby="minimum-band-gap-label"
            >
              <div>
                <label id="minimum-band-gap-label" htmlFor="minimum-band-gap">
                  Minimum band gap (eV) <span>Optional</span>
                </label>
                <input
                  id="minimum-band-gap"
                  type="number"
                  min="0"
                  max="100"
                  step="any"
                  inputMode="decimal"
                  placeholder="No minimum"
                  value={
                    draft.minimum_band_gap_ev == null ||
                    Number.isNaN(draft.minimum_band_gap_ev)
                      ? ""
                      : draft.minimum_band_gap_ev
                  }
                  disabled={busy}
                  aria-describedby="minimum-band-gap-help"
                  aria-invalid={!validMinimum}
                  onChange={(event) =>
                    update(
                      "minimum_band_gap_ev",
                      event.target.value === ""
                        ? null
                        : Number(event.target.value),
                    )
                  }
                />
              </div>
              <div>
                <p id="minimum-band-gap-help">
                  Leave blank for no minimum. This is a screening preference,
                  separate from importance weights. Only validated source values
                  are compared; unknown band gaps remain unknown.
                </p>
                {!bandGapActive && (
                  <p className="profile-constraint-inactive">
                    Inactive while Band gap importance is zero or unselected.
                    The value is retained for this profile.
                  </p>
                )}
                {!validMinimum && (
                  <p className="profile-validation" role="alert">
                    Enter a finite minimum from 0 to 100 eV, or leave it blank.
                  </p>
                )}
              </div>
            </section>
          )}
          {!validProfile && (
            <p className="profile-validation" role="status">
              Give the ranking profile a name, class and application, and select
              at least one importance greater than zero. Each value must be
              between 0 and 1.
            </p>
          )}
          {saved?.preset && changed && (
            <p className="profile-help">
              Preset edits are saved as a new ranking profile so the original
              remains available.
            </p>
          )}
          {notice && (
            <p className="settings-saved" role="status">
              {notice}
            </p>
          )}
          <div className="profile-actions">
            <button
              type="button"
              className="primary-button"
              disabled={
                busy ||
                !valid ||
                Boolean(error) ||
                Boolean(saved && !saved.preset && !changed)
              }
              onClick={() => void save()}
            >
              {busy ? "Saving…" : "Save ranking profile"}
            </button>
            <button
              type="button"
              className="quiet-button"
              disabled={
                busy ||
                !valid ||
                !saved ||
                changed ||
                Boolean(error) ||
                selected === data.active_profile_id
              }
              onClick={() => void activate()}
            >
              Use ranking profile
            </button>
          </div>
          <ImportanceComparison
            attributes={data.catalog.attributes}
            active={active}
            draft={draft.importance}
            showPreview={changed || selected !== data.active_profile_id}
          />
          <section
            className="attribute-catalog"
            aria-labelledby="attribute-catalog-heading"
          >
            <header>
              <div className="attribute-catalog-title">
                <h3 id="attribute-catalog-heading">Material properties</h3>
                <button
                  type="button"
                  className="attribute-category-toggle"
                  aria-controls={categoryListId}
                  disabled={!categories.length}
                  onClick={() =>
                    setExpandedCategories(anyCategoryExpanded ? [] : categories)
                  }
                >
                  <svg
                    viewBox="0 0 24 24"
                    width="16"
                    height="16"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.7"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <path
                      d={
                        anyCategoryExpanded
                          ? "m7 10 5-5 5 5M7 17l5-5 5 5"
                          : "m7 7 5 5 5-5M7 14l5 5 5-5"
                      }
                    />
                  </svg>
                  {anyCategoryExpanded ? "Collapse all" : "Expand all"}
                </button>
              </div>
              <p>
                Choose properties from any category. Newly selected properties
                start at 0.5 importance; adjust each value independently.
                Weights guide property searches and refine the shortlist when
                relevant cited evidence supports an assessment. Missing
                properties remain visible as evidence gaps.
              </p>
            </header>
            <div
              id={categoryListId}
              className="attribute-categories"
              aria-label="Material property categories"
            >
              {categories.map((category) => {
                const attributes = data.catalog.attributes.filter(
                  (attribute) => attribute.category === category,
                );
                const selectedCount = attributes.filter(
                  (attribute) => attribute.id in draft.importance,
                ).length;
                return (
                  <details
                    className="attribute-category"
                    key={category}
                    open={expandedCategories.includes(category)}
                  >
                    <summary
                      onClick={(event) => {
                        event.preventDefault();
                        setExpandedCategories((current) =>
                          current.includes(category)
                            ? current.filter((item) => item !== category)
                            : [...current, category],
                        );
                      }}
                    >
                      {category}
                      <span>
                        {selectedCount} selected ·{" "}
                        {attributes.length - selectedCount} available
                      </span>
                    </summary>
                    {attributes.map(attributeRow)}
                  </details>
                );
              })}
            </div>
          </section>
        </>
      )}
    </section>
  );
}

type ImportanceTarget = {
  anchor: HTMLButtonElement;
  chart: "active" | "preview";
  attributeId: string;
};
type ImportanceInteraction = {
  described: ImportanceTarget | null;
  tooltipId: string;
  hover: (target: ImportanceTarget) => void;
  leave: (anchor: HTMLButtonElement) => void;
  focus: (target: ImportanceTarget) => void;
  blur: (anchor: HTMLButtonElement) => void;
};

function ImportanceComparison({
  attributes,
  active,
  draft,
  showPreview,
}: {
  attributes: Attribute[];
  active?: RankingProfile;
  draft: Record<string, number>;
  showPreview: boolean;
}) {
  const [hovered, setHovered] = useState<ImportanceTarget | null>(null),
    [focused, setFocused] = useState<ImportanceTarget | null>(null);
  const leaveTimer = useRef<number | undefined>(undefined),
    tooltipId = useId();
  function cancelLeave() {
    window.clearTimeout(leaveTimer.current);
  }
  function dismiss() {
    cancelLeave();
    setHovered(null);
    setFocused(null);
  }
  function leave(anchor: HTMLButtonElement) {
    cancelLeave();
    leaveTimer.current = window.setTimeout(
      () =>
        setHovered((current) => (current?.anchor === anchor ? null : current)),
      140,
    );
  }
  useEffect(() => () => window.clearTimeout(leaveTimer.current), []);
  const weights = (target: ImportanceTarget) =>
    target.chart === "preview"
      ? showPreview
        ? draft
        : {}
      : (active?.importance ?? {});
  const target =
    [hovered, focused].find(
      (item) =>
        item &&
        weights(item)[item.attributeId] > 0 &&
        attributes.some((attribute) => attribute.id === item.attributeId),
    ) ?? null;
  const attribute = target
    ? attributes.find((item) => item.id === target.attributeId)
    : undefined;
  const interaction: ImportanceInteraction = {
    described: target,
    tooltipId,
    hover: (next) => {
      cancelLeave();
      setHovered(next);
    },
    leave,
    focus: (next) => {
      cancelLeave();
      setHovered(null);
      setFocused(next);
    },
    blur: (anchor) =>
      setFocused((current) => (current?.anchor === anchor ? null : current)),
  };
  return (
    <div className="profile-comparison">
      {active && (
        <ImportanceChart
          attributes={attributes}
          importance={active.importance}
          title="Active ranking profile"
          note={active.name}
          chart="active"
          interaction={interaction}
        />
      )}
      {showPreview && (
        <ImportanceChart
          attributes={attributes}
          importance={draft}
          title="Editing preview"
          note="Relative contribution · automatically normalized"
          chart="preview"
          interaction={interaction}
        />
      )}
      {target && attribute && (
        <ImportanceTooltip
          target={target}
          attribute={attribute}
          importance={weights(target)[attribute.id]}
          relative={relativeWeights(weights(target))[attribute.id]}
          id={tooltipId}
          onDismiss={dismiss}
          onEnter={cancelLeave}
          onLeave={() => leave(target.anchor)}
        />
      )}
    </div>
  );
}

function ImportanceChart({
  attributes,
  importance,
  title,
  note,
  chart,
  interaction,
}: {
  attributes: Attribute[];
  importance: Record<string, number>;
  title: string;
  note: string;
  chart: ImportanceTarget["chart"];
  interaction: ImportanceInteraction;
}) {
  const relative = relativeWeights(importance);
  return (
    <section className="importance-overview" aria-label={title}>
      <div className="importance-overview-title">
        <h3>{title}</h3>
        <span>{note}</span>
      </div>
      <div
        className="importance-chart"
        role="group"
        aria-label={`${title} relative importance`}
      >
        {attributes
          .filter((attribute) => relative[attribute.id] > 0)
          .map((attribute) => {
            const target = (anchor: HTMLButtonElement): ImportanceTarget => ({
              anchor,
              chart,
              attributeId: attribute.id,
            });
            const described =
              interaction.described?.chart === chart &&
              interaction.described.attributeId === attribute.id;
            return (
              <button
                type="button"
                key={attribute.id}
                className={`importance-segment color-${attributes.indexOf(attribute) % 6} ${attribute.supported ? "" : "not-scored"}`}
                style={{ flexGrow: relative[attribute.id] }}
                aria-label={`${attribute.label}: ${(relative[attribute.id] * 100).toFixed(1)}% relative importance${attribute.supported ? "" : " · not yet scored"}`}
                aria-describedby={described ? interaction.tooltipId : undefined}
                onPointerEnter={(event) => {
                  if (event.pointerType !== "touch")
                    interaction.hover(target(event.currentTarget));
                }}
                onPointerLeave={(event) =>
                  interaction.leave(event.currentTarget)
                }
                onFocus={(event) =>
                  interaction.focus(target(event.currentTarget))
                }
                onBlur={(event) => interaction.blur(event.currentTarget)}
                onClick={(event) => {
                  event.currentTarget.focus({ preventScroll: true });
                  interaction.focus(target(event.currentTarget));
                }}
              />
            );
          })}
      </div>
      <div className="importance-legend">
        {attributes
          .filter((attribute) => relative[attribute.id] > 0)
          .map((attribute) => (
            <span key={attribute.id}>
              {attribute.label}{" "}
              <strong>{(relative[attribute.id] * 100).toFixed(1)}%</strong>
              {!attribute.supported && <small> · not yet scored</small>}
            </span>
          ))}
      </div>
    </section>
  );
}

function ImportanceTooltip({
  target,
  attribute,
  importance,
  relative,
  id,
  onDismiss,
  onEnter,
  onLeave,
}: {
  target: ImportanceTarget;
  attribute: Attribute;
  importance: number;
  relative: number;
  id: string;
  onDismiss: () => void;
  onEnter: () => void;
  onLeave: () => void;
}) {
  const tooltip = useRef<HTMLDivElement>(null);
  // The native settings dialog is in the top layer. Keep its tooltip in that
  // layer too, outside the chart and its scrolling/clipping containers.
  const container = target.anchor.closest("dialog[open]") ?? document.body;
  useLayoutEffect(() => {
    const element = tooltip.current;
    if (!element) return;
    const viewport = window.visualViewport;
    function position() {
      if (!element || !target.anchor.isConnected) {
        onDismiss();
        return;
      }
      const anchor = target.anchor.getBoundingClientRect(),
        margin = 12,
        gap = 10;
      const originX = viewport?.offsetLeft ?? 0,
        originY = viewport?.offsetTop ?? 0;
      const width = viewport?.width ?? window.innerWidth,
        height = viewport?.height ?? window.innerHeight;
      if (
        anchor.bottom < originY ||
        anchor.top > originY + height ||
        anchor.right < originX ||
        anchor.left > originX + width
      ) {
        onDismiss();
        return;
      }
      element.style.width = `${Math.max(0, Math.min(300, width - margin * 2))}px`;
      element.style.maxHeight = `${Math.max(0, height - margin * 2)}px`;
      const bounds = element.getBoundingClientRect();
      const above = anchor.top - originY - margin - gap,
        below = originY + height - anchor.bottom - margin - gap;
      const side = above >= bounds.height || above > below ? "above" : "below";
      const left = Math.max(
        originX + margin,
        Math.min(
          anchor.left + anchor.width / 2 - bounds.width / 2,
          originX + width - bounds.width - margin,
        ),
      );
      const top = Math.max(
        originY + margin,
        Math.min(
          side === "above"
            ? anchor.top - bounds.height - gap
            : anchor.bottom + gap,
          originY + height - bounds.height - margin,
        ),
      );
      element.style.left = `${left}px`;
      element.style.top = `${top}px`;
      element.style.visibility = "visible";
      element.dataset.side = side;
    }
    function key(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onDismiss();
      }
    }
    function outside(event: PointerEvent) {
      if (
        event.target instanceof Node &&
        !target.anchor.contains(event.target) &&
        !element?.contains(event.target)
      )
        onDismiss();
    }
    position();
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(position);
    observer?.observe(target.anchor);
    observer?.observe(element);
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, true);
    viewport?.addEventListener("resize", position);
    viewport?.addEventListener("scroll", position);
    document.addEventListener("keydown", key, true);
    document.addEventListener("pointerdown", outside, true);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", position, true);
      viewport?.removeEventListener("resize", position);
      viewport?.removeEventListener("scroll", position);
      document.removeEventListener("keydown", key, true);
      document.removeEventListener("pointerdown", outside, true);
    };
  }, [target, attribute, importance, relative, onDismiss]);
  return createPortal(
    <div
      ref={tooltip}
      id={id}
      role="tooltip"
      className="importance-tooltip"
      onPointerEnter={onEnter}
      onPointerLeave={onLeave}
    >
      <span className="importance-tooltip-context">
        {target.chart === "active"
          ? "Active ranking profile"
          : "Editing preview"}
      </span>
      <strong className="importance-tooltip-label">{attribute.label}</strong>
      <div className="importance-tooltip-share">
        <strong>{(relative * 100).toFixed(1)}%</strong>
        <span>of all selected importance</span>
      </div>
      <p className="importance-tooltip-value">
        Independent importance <strong>{importance} / 1</strong>
      </p>
      <p className="importance-tooltip-note">
        {attribute.supported
          ? "Contributes only when verified evidence is available."
          : "Not yet scored. This share stays in the total as an evidence gap and earns no evidence credit."}
      </p>
    </div>,
    container,
  );
}
