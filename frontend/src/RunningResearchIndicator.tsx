import "./runningResearchIndicator.css";

/** The parent owns research state. This graphic has no polling or timers. */
export default function RunningResearchIndicator({
  label = "Research running",
}: {
  label?: string;
}) {
  return (
    <span
      className="running-research-indicator"
      role="img"
      aria-label={label}
      title="Research continues when you open another chat"
    >
      <svg
        viewBox="0 0 24 28"
        width="16"
        height="20"
        aria-hidden="true"
        focusable="false"
      >
        <path
          className="research-flask-glass"
          d="M10 3v8L4.8 21a2.4 2.4 0 0 0 2.1 3.5h10.2a2.4 2.4 0 0 0 2.1-3.5L14 11V3"
        />
        <path
          className="research-flask-liquid"
          d="M8 16h8l3.2 6.1a1.4 1.4 0 0 1-1.3 1.9H6.1a1.4 1.4 0 0 1-1.3-1.9Z"
        />
        <path
          className="research-flask-rim"
          d="M8.5 3h7M10 11 4.8 21a2.4 2.4 0 0 0 2.1 3.5h10.2a2.4 2.4 0 0 0 2.1-3.5L14 11"
        />
        <circle
          className="research-flask-bubble research-flask-bubble-one"
          cx="9.5"
          cy="20"
          r="1.1"
        />
        <circle
          className="research-flask-bubble research-flask-bubble-two"
          cx="14"
          cy="19"
          r=".85"
        />
        <circle
          className="research-flask-bubble research-flask-bubble-three"
          cx="11.8"
          cy="13.5"
          r=".75"
        />
      </svg>
    </span>
  );
}
