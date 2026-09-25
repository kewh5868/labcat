export const brandName = "Labcat";
export const brandTagline = "Curious. Clever. Companionable.";

/** Decorative mark; each placement provides its own visible brand text. */
export function LabcatMark({ className = "" }: { className?: string }) {
  return (
    <img
      className={`labcat-mark ${className}`}
      src="/assets/brand/labcat-mark.png"
      alt=""
      aria-hidden="true"
      width={1254}
      height={1254}
      decoding="async"
    />
  );
}
