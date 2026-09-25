import { useEffect, useState } from "react";
import {
  LABCAT_COMPLETION_MS,
  LABCAT_MASCOTS_ENABLED,
} from "./labcatMascotConfig";
import "./labcatMascot.css";

export type LabcatScene =
  | "beaker"
  | "wires"
  | "crystal"
  | "typewriter"
  | "computer"
  | "nap";
type MascotProps = {
  scene: LabcatScene;
  className?: string;
  completed?: boolean;
};
type MotionPolicy = { reduced: boolean; hidden: boolean };

function useMotionPolicy(enabled: boolean): MotionPolicy {
  const [policy, setPolicy] = useState<MotionPolicy>(() => ({
    reduced:
      typeof window !== "undefined" && typeof window.matchMedia === "function"
        ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
        : false,
    hidden: typeof document !== "undefined" && document.hidden,
  }));
  useEffect(() => {
    if (!enabled) return;
    const media =
      typeof window.matchMedia === "function"
        ? window.matchMedia("(prefers-reduced-motion: reduce)")
        : null;
    const update = () =>
      setPolicy({ reduced: media?.matches ?? false, hidden: document.hidden });
    update();
    media?.addEventListener("change", update);
    document.addEventListener("visibilitychange", update);
    return () => {
      media?.removeEventListener("change", update);
      document.removeEventListener("visibilitychange", update);
    };
  }, [enabled]);
  return policy;
}

function Sprite({
  scene,
  className = "",
  completed = false,
  policy,
  onError,
}: MascotProps & {
  policy: MotionPolicy;
  onError: () => void;
}) {
  const animation = scene === "beaker" && completed ? "beaker-complete" : scene;
  return (
    <span
      className={`labcat-mascot ${className}`}
      aria-hidden="true"
      data-scene={scene}
      data-animation={animation}
      data-reduced-motion={policy.reduced}
      data-paused={policy.hidden}
    >
      <img
        className="labcat-mascot-sheet"
        src={`/assets/labcat/${scene}.png`}
        alt=""
        draggable={false}
        decoding="async"
        onError={onError}
      />
      {scene === "beaker" && !completed && (
        <span className="labcat-mascot-liquid">
          <img
            className="labcat-mascot-liquid-sheet"
            src="/assets/labcat/beaker.png"
            alt=""
            draggable={false}
            decoding="async"
            onError={onError}
          />
        </span>
      )}
    </span>
  );
}

function AnimatedMascot(props: MascotProps) {
  const [failed, setFailed] = useState(false);
  const policy = useMotionPolicy(!failed);
  return failed ? null : (
    <Sprite {...props} policy={policy} onError={() => setFailed(true)} />
  );
}

/** Decoration only: never infers completion, dispatches actions, or blocks UI. */
export default function LabcatMascot(props: MascotProps) {
  return LABCAT_MASCOTS_ENABLED ? (
    <AnimatedMascot key={props.scene} {...props} />
  ) : null;
}

function CompletionFlourish({ className }: { className?: string }) {
  const [failed, setFailed] = useState(false);
  const [visible, setVisible] = useState(true);
  const policy = useMotionPolicy(visible && !failed);
  useEffect(() => {
    if (!visible || failed) return;
    if (policy.reduced) {
      setVisible(false);
      return;
    }
    if (policy.hidden) return;
    const timer = window.setTimeout(
      () => setVisible(false),
      LABCAT_COMPLETION_MS,
    );
    return () => window.clearTimeout(timer);
  }, [visible, failed, policy.hidden, policy.reduced]);
  if (!visible || failed || policy.reduced) return null;
  return (
    <Sprite
      scene="beaker"
      completed
      className={className}
      policy={policy}
      onError={() => setFailed(true)}
    />
  );
}

/** Pass a key only for a newly completed report, never for saved history.
 * No image, activity monitoring or idle behavior remains between reports. */
export function ResearchCompletionMascot({
  completionKey,
  className,
}: {
  completionKey?: string;
  className?: string;
}) {
  return LABCAT_MASCOTS_ENABLED && completionKey ? (
    <CompletionFlourish key={completionKey} className={className} />
  ) : null;
}
