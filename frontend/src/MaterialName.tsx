import { createContext, useContext } from "react";
import {
  chemicalComponentFormulas,
  chemicalFormulaSignature,
  chemicalNameKey,
} from "./chemicalNamesApi";
import type { MaterialName } from "./chemicalNamesApi";
import type { StructureTarget } from "./structureApi";

export const MaterialNamesContext = createContext<readonly MaterialName[]>([]);
export default function ChemicalName({
  target,
  formula,
}: {
  target?: StructureTarget;
  formula: string;
}) {
  const names = useContext(MaterialNamesContext),
    signature = chemicalFormulaSignature(formula),
    components = chemicalComponentFormulas(formula);
  if (!target || (!signature && !components.length)) return null;
  const matches = names
    .filter((item) => {
      if (item.kind !== target.kind || item.id !== target.id) return false;
      if (item.component_index !== undefined) {
        const index = item.component_index - 1,
          parent = chemicalComponentFormulas(item.parent_formula ?? "");
        return (
          components.length > 0 &&
          components.length === parent.length &&
          index >= 0 &&
          index < components.length &&
          components.every(
            (part, position) =>
              chemicalFormulaSignature(part) ===
              chemicalFormulaSignature(parent[position]),
          ) &&
          chemicalFormulaSignature(item.formula) ===
            chemicalFormulaSignature(components[index])
        );
      }
      return signature && chemicalFormulaSignature(item.formula) === signature;
    })
    .filter(
      (item) =>
        chemicalFormulaSignature(item.name) !==
        chemicalFormulaSignature(item.formula),
    );
  if (
    !matches.length ||
    (!components.length && matches.length !== 1) ||
    new Set(matches.map(chemicalNameKey)).size !== matches.length
  )
    return null;
  return (
    <>
      {matches
        .sort((a, b) => (a.component_index ?? 0) - (b.component_index ?? 0))
        .map((name) => (
          <small key={chemicalNameKey(name)} className="report-chemical-name">
            {name.component_index !== undefined && (
              <>{components[name.component_index - 1]}: </>
            )}
            <a
              href={name.url}
              target="_blank"
              rel="noopener noreferrer"
              title={`${name.source_name} · Chemical name for this ${name.component_index !== undefined ? "component composition" : "composition"}; does not verify the phase or suitability.`}
            >
              {name.name}
              <span className="sr-only"> (chemical name source)</span>
            </a>
          </small>
        ))}
    </>
  );
}
