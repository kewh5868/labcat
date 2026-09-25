import { useEffect, useState } from "react";
import "./materialsFact.css";

// Curated educational UI copy, reviewed against these public primary sources
// on 2026-09-10–11. Never use this collection as report or research evidence.
const facts = [
  {
    text: "Ordinary adhesive tape helped researchers peel graphene from graphite, down to a single layer of carbon atoms.",
    publisher: "Nobel Prize",
    sourceTitle: "The 2010 Nobel Prize in Physics",
    url: "https://www.nobelprize.org/prizes/physics/2010/press-release/",
  },
  {
    text: "NASA’s Stardust spacecraft used porous silica aerogel to catch comet dust and bring it back to Earth.",
    publisher: "NASA",
    sourceTitle: "Stardust / Stardust NExT",
    url: "https://science.nasa.gov/mission/stardust/",
  },
  {
    text: "Atomic order can exist without a repeating pattern. Quasicrystals have ordered structures that do not repeat periodically.",
    publisher: "Nobel Prize",
    sourceTitle: "The 2011 Nobel Prize in Chemistry",
    url: "https://www.nobelprize.org/prizes/chemistry/2011/press-release/",
  },
  {
    text: "Some plastics can conduct electricity. Doping certain polymers changes their electron population so charge can move along their chains.",
    publisher: "Nobel Prize",
    sourceTitle: "The 2000 Nobel Prize in Chemistry",
    url: "https://www.nobelprize.org/prizes/chemistry/2000/press-release/",
  },
  {
    text: "A quantum dot’s size can change the color of light it emits. These tiny semiconductor particles help produce vivid colors in television and computer displays.",
    publisher: "MIT",
    sourceTitle: "MIT Professor Moungi Bawendi shares Nobel Prize in Chemistry",
    url: "https://news.mit.edu/2023/mit-chemist-moungi-bawendi-shares-nobel-prize-chemistry-1004",
  },
  {
    text: "Some metal alloys can remember a shape and return to it when heated. NASA has tested this behavior in small fins that adjust airflow over aircraft wings.",
    publisher: "NASA",
    sourceTitle: "Memory Metals are Shaping the Evolution of Aviation",
    url: "https://www.nasa.gov/aeronautics/memory-metals-are-shaping-the-evolution-of-aviation/",
  },
  {
    text: "Metallic glass is a metal alloy whose atoms lack a regular crystal lattice. NASA has explored using it to make gears that work without liquid lubricants.",
    publisher: "NASA",
    sourceTitle: "Metallic Glass Gears Up for “Cobots,” Coatings, and More",
    url: "https://www.nasa.gov/technology/metallic-glass-gears-up-for-cobots-coatings-and-more/",
  },
  {
    text: "Efficient blue LEDs were a crucial missing ingredient for bright white LED lighting. Their development earned three scientists the 2014 Nobel Prize in Physics.",
    publisher: "Nobel Prize",
    sourceTitle: "The 2014 Nobel Prize in Physics",
    url: "https://www.nobelprize.org/prizes/physics/2014/press-release/",
  },
  {
    text: "Stacks of extremely thin metal layers can turn tiny magnetic changes into large changes in electrical resistance. This effect helped make hard drives smaller and more capable.",
    publisher: "Nobel Prize",
    sourceTitle: "The 2007 Nobel Prize in Physics",
    url: "https://www.nobelprize.org/prizes/physics/2007/press-release/",
  },
  {
    text: "Glass can become flexible when drawn into a fine fiber. These slender glass threads carry information as light through optical communication cables around the world.",
    publisher: "Nobel Prize",
    sourceTitle: "The Nobel Prize in Physics 2009: Filled with light",
    url: "https://www.nobelprize.org/uploads/2018/06/popular-physicsprize2009.pdf",
  },
  {
    text: "Some copper oxides become superconductors when cooled, carrying direct current without electrical resistance. Their nickname, “high-temperature superconductors,” still describes materials that need very cold conditions.",
    publisher: "U.S. Department of Energy",
    sourceTitle: "DOE Explains...Superconductivity",
    url: "https://www.energy.gov/science/doe-explainssuperconductivity",
  },
  {
    text: "Mother-of-pearl combines brittle mineral plates with thin organic layers. Its carefully arranged structure helps a shell resist damage better than its mineral ingredient could alone.",
    publisher: "MIT",
    sourceTitle:
      "Technique reveals deeper insights into the makeup of nacre, a natural material",
    url: "https://news.mit.edu/2020/technique-reveals-insights-makeup-of-nacre-1030",
  },
  {
    text: "Gecko feet inspired NASA grippers covered in tiny synthetic hairs. Their grip relies on molecular attractions called van der Waals forces and leaves no sticky residue.",
    publisher: "NASA",
    sourceTitle: "Gecko Grippers Moving On Up",
    url: "https://www.nasa.gov/missions/station/gecko-grippers-moving-on-up/",
  },
  {
    text: "Researchers have made polymers with tiny capsules of healing liquid inside. When a crack breaks the capsules, the released liquid helps repair the damage.",
    publisher: "University of Illinois Urbana-Champaign",
    sourceTitle: "The Moore Group: Lab Tours and Demonstrations",
    url: "https://mooregroup.beckman.illinois.edu/lab-tours-and-demonstrations",
  },
  {
    text: "A specially designed polyurethane can turn purple when stretched because force changes molecules inside it. Visible light can reverse the color change for another demonstration.",
    publisher: "University of Illinois Urbana-Champaign",
    sourceTitle: "The Moore Group: Lab Tours and Demonstrations",
    url: "https://mooregroup.beckman.illinois.edu/lab-tours-and-demonstrations",
  },
  {
    text: "Some flower petals have microscopic ridges that scatter blue and ultraviolet light. This structural color creates a “blue halo” that can help bees find the flowers.",
    publisher: "University of Cambridge",
    sourceTitle: "Petals produce a “blue halo” that helps bees find flowers",
    url: "https://www.cam.ac.uk/research/news/petals-produce-a-blue-halo-that-helps-bees-find-flowers",
  },
  {
    text: "In a lithium-ion battery, lithium ions travel between the two electrodes during charging and discharging. Electrode materials provide places for those ions to settle temporarily.",
    publisher: "Nobel Prize",
    sourceTitle:
      "The Nobel Prize in Chemistry 2019: They created a rechargeable world",
    url: "https://www.nobelprize.org/prizes/chemistry/2019/popular-information/",
  },
  {
    text: "Auxetic materials can get wider when pulled lengthwise. Their unusual response can come from the geometry of their internal structure, rather than an unusual chemical ingredient.",
    publisher: "NIST",
    sourceTitle: "A New Way of Designing Auxetic Materials",
    url: "https://www.nist.gov/news-events/news/2024/05/new-way-designing-auxetic-materials",
  },
  {
    text: "Diamond and graphite are both forms of carbon. In diamond, each carbon atom bonds to four neighbors; in graphite, it bonds to three within sheets.",
    publisher: "Royal Society of Chemistry",
    sourceTitle: "How to teach structure and bonding of carbon at 14–16",
    url: "https://edu.rsc.org/cpd/how-to-teach-structure-and-bonding-of-carbon-at-14-16/4020312.article",
  },
  {
    text: "Piezoelectric materials can convert pressure into an electrical signal and electrical input into motion. NASA-supported sensors use this two-way behavior to detect ice forming on a vibrating wire.",
    publisher: "NASA",
    sourceTitle: "Wire Sensors Alert to Dangerous Conditions in the Clouds",
    url: "https://spinoff.nasa.gov/node/10935",
  },
] as const;

// A new draft remounts this component. Remember only the last displayed fact
// in UI memory so another chat starts randomly, without an immediate repeat.
let lastDisplayedIndex: number | null = null;
function randomStartingIndex() {
  const offset = Math.floor(
    Math.random() * (facts.length - (lastDisplayedIndex === null ? 0 : 1)),
  );
  return lastDisplayedIndex !== null && offset >= lastDisplayedIndex
    ? offset + 1
    : offset;
}

export default function MaterialsFact() {
  const [index, setIndex] = useState(randomStartingIndex);
  const [paused, setPaused] = useState(false);
  const [focused, setFocused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [hidden, setHidden] = useState(() => document.hidden);
  const [reducedMotion, setReducedMotion] = useState(
    () =>
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false,
  );

  useEffect(() => {
    lastDisplayedIndex = index;
  }, [index]);

  useEffect(() => {
    const preference = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const changed = () => setReducedMotion(preference?.matches ?? false);
    const visibility = () => setHidden(document.hidden);
    preference?.addEventListener("change", changed);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      preference?.removeEventListener("change", changed);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, []);

  useEffect(() => {
    if (paused || focused || hovered || hidden || reducedMotion) return;
    const timer = window.setTimeout(
      () => setIndex((current) => (current + 1) % facts.length),
      20_000,
    );
    return () => window.clearTimeout(timer);
  }, [index, paused, focused, hovered, hidden, reducedMotion]);

  const fact = facts[index];
  return (
    <aside
      className="materials-fact"
      aria-label="Materials science fact"
      aria-live="off"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setFocused(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget))
          setFocused(false);
      }}
    >
      <p className="materials-fact-label">
        <span aria-hidden="true">✧</span> Materials curiosity
      </p>
      <p className="materials-fact-copy">{fact.text}</p>
      <div className="materials-fact-footer">
        <a
          href={fact.url}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Read source: ${fact.sourceTitle}`}
        >
          Source: {fact.publisher} <span aria-hidden="true">↗</span>
        </a>
        <div className="materials-fact-controls">
          {!reducedMotion && (
            <button
              type="button"
              aria-label={
                paused ? "Resume automatic facts" : "Pause automatic facts"
              }
              onClick={() => setPaused((current) => !current)}
            >
              {paused ? "Resume" : "Pause"}
            </button>
          )}
          <button
            type="button"
            onClick={() => setIndex((current) => (current + 1) % facts.length)}
          >
            Next fact <span aria-hidden="true">→</span>
          </button>
        </div>
      </div>
    </aside>
  );
}
