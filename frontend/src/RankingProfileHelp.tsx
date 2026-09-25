import { useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import "./rankingProfileHelp.css";

/** Inline help works inside both the composer popup and its settings dialog. */
export default function RankingProfileHelp({
  children,
  compact = false,
}: {
  children: ReactNode;
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const id = useId();
  return (
    <div
      className={`ranking-profile-help${compact ? " ranking-profile-help-compact" : ""}`}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.preventDefault();
          event.stopPropagation();
          setOpen(false);
          button.current?.focus();
        }
      }}
    >
      <div className="ranking-profile-help-heading">
        {children}
        <button
          ref={button}
          className="ranking-profile-help-button"
          type="button"
          aria-label="About ranking profiles"
          aria-expanded={open}
          aria-controls={`${id}-explanation`}
          title="About ranking profiles"
          onClick={() => setOpen((value) => !value)}
        >
          <span aria-hidden="true">?</span>
        </button>
      </div>
      {open && (
        <div
          id={`${id}-explanation`}
          className="ranking-profile-help-content"
          role="note"
          aria-label="How ranking profiles work"
        >
          <p>
            A ranking profile saves a material class, application and set of
            properties for comparing candidates. Start with a preset or create a
            custom profile in Search Criterion.
          </p>
          <p>
            Each importance ranges between <strong>0 and 1</strong>. Higher
            relative values carry more weight; Labcat calculates the relative
            weights for you. Zero excludes a property from scoring. At least one
            value must be positive.
          </p>
          <p>
            <strong>Infer from prompt</strong> is the chat default. It matches
            your question to saved profiles and uses the workspace default when
            there is no clear match. Choose a specific profile to use it for
            that request.
          </p>
          <p>
            <strong>Save ranking profile</strong> stores your edits.{" "}
            <strong>Use ranking profile</strong> makes a saved profile the
            workspace default. Saving changes to an already active custom
            profile also updates that default. Preset edits create a new
            profile; previous reports keep their saved criteria.
          </p>
          <p>
            The preliminary shortlist starts with cited application evidence.
            Accepted property assessments then refine it using your weights;
            validated numerical values also support the separate property
            ranking. Higher weights guide targeted property searches. Unknown
            properties stay unknown, and equally unassessed candidates can tie.
          </p>
          <p>
            To apply edited weights, save and choose that profile in the chat,
            then run another analysis. Existing reports and pinned snapshots
            keep their recorded settings.
          </p>
        </div>
      )}
    </div>
  );
}
