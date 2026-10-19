import { useMemo } from "react";
import { referenceMeasurements } from "../../workbench/referenceMeasurements.js";
import { nodeVolume } from "../../workbench/partVolume.js";
import { STEP_MODEL_ROOT_ID, stepTreeNodeLeafPartIds } from "@text-to-cad/core/lib/step/stepTree.js";
import { stepPartNameFromFile } from "@text-to-cad/core/lib/step/productName.js";

import { InfoRow, MonoValue, formatNumber } from "../../../kit/inspector/referenceRows.jsx";

// A selected "element" is either a topology reference (face / edge / solid,
// carrying reference.pickData) or an assembly node (component / subassembly).
// Measurements use the current STEP selection, including its occurrence transforms.

const SELECTOR_TYPE_LABELS = Object.freeze({
  face: "Face",
  edge: "Edge",
  shape: "Solid",
  occurrence: "Component"
});

// A part's overall size, from its bounding box.
function boxSize(source) {
  const bbox = source?.bbox || source?.boundingBox || null;
  const min = Array.isArray(bbox?.min) ? bbox.min : null;
  const max = Array.isArray(bbox?.max) ? bbox.max : null;
  if (!min || !max) {
    return null;
  }
  const dims = [0, 1, 2].map((axis) => Math.abs((Number(max[axis]) || 0) - (Number(min[axis]) || 0)));
  return dims.some((value) => value > 1e-9) ? dims : null;
}

function isPartNode(item) {
  return Boolean(item) && !item.pickData && (item.nodeType || Array.isArray(item.children));
}


function MeasurementRows({rows}) {
  return rows.map(([label,value,unit])=><InfoRow key={label} label={label}><MonoValue>{`${formatNumber(value)} ${unit}`}</MonoValue></InfoRow>);
}

// A face's or an edge's own measurements: its area, its length, the radii of a round one, an
// arc's sweep. Where it is (its centre, its normal), what kind it is and whose it is are the
// heading's and the view's to say.
function TopologyDetail({ reference }) {
  return <MeasurementRows rows={referenceMeasurements(reference).rows} />;
}

// A component's or a subassembly's: how many parts, its overall size and its volume.
function PartDetail({ node, size, meshData }) {
  const isAssembly =
    String(node.nodeType || "").trim() === "assembly" ||
    (Array.isArray(node.children) && node.children.length > 0);
  const partCount = Array.isArray(node.leafPartIds)
    ? node.leafPartIds.length
    : Array.isArray(node.children)
      ? node.children.length
      : 0;
  const volume = useMemo(() => nodeVolume(node, meshData), [node, meshData]);
  return <>
    {isAssembly && partCount > 0 ? (
      <InfoRow label="Parts"><MonoValue>{formatNumber(partCount, 0)}</MonoValue></InfoRow>
    ) : null}
    {size && <SizeRow size={size}/>}
    {volume !== null && <VolumeRow volume={volume}/>}
  </>;
}

// From the displayed mesh: exact for flat faces, a close approximation where faces curve.
function VolumeRow({ volume }) {
  return <InfoRow label="Volume" title="Approximate mesh volume">
    <MonoValue>{formatNumber(volume, volume >= 100 ? 0 : 2)} mm³</MonoValue>
  </InfoRow>;
}

function SizeRow({ size }) {
  return <InfoRow label="Size" title="XYZ bounding size"><MonoValue>{size.map(value=>formatNumber(value)).join(' × ')} mm</MonoValue></InfoRow>;
}

function itemKey(item) {
  return String(item?.id || item?.occurrenceId || item?.displaySelector || "").trim();
}

/**
 * A reference as a person reads it: its own label when it has one (a part's or subassembly's
 * name, a named face), otherwise where it is and what — "base · face 3" — from its part as the
 * tree names it (`partName`) and its selector's last token. A generated label that only
 * restates the selector ("Face o1.1.f3") is not a name. A single-part file's part with no name of
 * its own is the file's ("l_bracket · face 11"): the tree's root is that part, named after the
 * file. Never the raw id: that is what a copy carries, with the file it is in.
 */
function referenceName(item, meshData, partName) {
  if (isPartNode(item)) return String(item.name || item.displayName || "").trim() || itemKey(item);
  const { own, parent, kind, number } = referenceParts(item, meshData, partName);
  if (own) return own;
  return [parent, number ? `${kind} ${number}` : kind].filter(Boolean).join(" · ");
}

// A face's or an edge's name, in its pieces: its own label where it has one, its part as the tree
// names it, its kind ("face") and its number on that part ("3").
function referenceParts(item, meshData, partName) {
  const selector = String(item.displaySelector || item.normalizedSelector || item.id || "").split("|").pop();
  const token = selector.split(".").filter(Boolean).pop() || "";
  const text = value => String(value ?? "").trim();
  const own = [item.name, item.pickData?.name, item.label].map(text)
    .find(value => value && !(token && value.includes(token)) && !value.includes(selector)) || "";
  const kind = (SELECTOR_TYPE_LABELS[item.selectorType] || "Reference").toLowerCase();
  const number = token.match(/^[a-z]+(\d+)$/i)?.[1] || "";
  const occurrence = item.occurrenceId || selector.slice(0, -token.length - 1);
  const parts = Array.isArray(meshData?.parts) ? meshData.parts : [];
  const part = parts.find(entry => [entry.occurrenceId, entry.id].includes(occurrence));
  // The part's own name, where it is one: an occurrence with none goes by its id, and that is
  // the last resort here, after the name a single-part file gives its part.
  const partLabel = [part?.name, part?.displayName].map(text).find(value => value && value !== occurrence) || "";
  const fileName = stepPartNameFromFile(partName?.(STEP_MODEL_ROOT_ID));
  const parent = [item.pickData?.sourceName, item.sourceName, partName?.(occurrence), partLabel, fileName, occurrence]
    .map(text).find(Boolean) || "";
  return { own, parent, kind, number, occurrence };
}

const PLURAL_KINDS = Object.freeze({ face: "faces", edge: "edges", solid: "solids", component: "components" });

// A run of faces or edges on one part, one row each: its number (or its own name) and its first
// measurement, an area or a length.
function TopologyRunDetail({ members }) {
  return members.map(({ item, label }) => {
    const [, value, unit] = referenceMeasurements(item).rows[0] || [];
    return <InfoRow key={itemKey(item)} label={label}>
      <MonoValue>{value === undefined ? "—" : `${formatNumber(value)} ${unit}`}</MonoValue>
    </InfoRow>;
  });
}

/**
 * The selection as Quick Edit's chips (`kit/tools/quick-edit/ReferenceChips.jsx`): a component or
 * a subassembly is a chip of its own; faces, edges and solids are a chip for each kind on each
 * part — "base · face 3" alone, "base · 6 faces" for several, however they were picked (one by
 * one, or grown by Group faces or Group edges) — so a large selection stays a few chips. Each
 * chip's card is what the Reference panel said of it: a face's or an edge's key measurements, a
 * run's one row each, a part's size and volume. `onRemove(ids)` drops a chip's picks from the
 * selection; `onHover(target)` lights them while the pointer rests on the chip (`{ referenceId }`
 * for one face or edge, `{ nodeId }` for a part, a subassembly or a run on one part), or nothing.
 * `copyText(ids)` is what a click on the chip copies, its references as Copy References writes
 * them; the card's ID is their selectors, without the file.
 *
 * @returns {import("../../../kit/tools/quick-edit/ReferenceChips.jsx").ReferenceChip[]}
 */
export function useStepReferenceChips({ references = [], meshData = null, partsSize = null, partName = null, onRemove = null, onHover = null, copyText = null }) {
  return useMemo(() => {
    const chips = [];
    const runs = new Map();
    for (const item of Array.isArray(references) ? references : []) {
      if (!item) continue;
      const id = itemKey(item);
      if (isPartNode(item)) {
        const name = referenceName(item, meshData, partName);
        const size = boxSize(item) || partsSize?.(stepTreeNodeLeafPartIds(item)) || null;
        chips.push({ key: `node:${id}`, label: name, ids: [id], glyph: "solid",
          card: <PartDetail node={item} meshData={meshData} size={size}/>,
          hover: { nodeId: id } });
        continue;
      }
      const parts = referenceParts(item, meshData, partName);
      const runKey = `${parts.occurrence}|${item.selectorType}`;
      let run = runs.get(runKey);
      if (!run) {
        run = { key: `run:${runKey}`, parts, members: [] };
        runs.set(runKey, run);
        chips.push(run);
      }
      run.members.push({ item, label: parts.own || (parts.number ? `${parts.kind} ${parts.number}` : parts.kind) });
    }
    return chips.map(chip => ({ ...chipFor(chip), ...copyFields(chip.ids || chip.members.map(member => itemKey(member.item))) }));
    function copyFields(ids) {
      const copy = copyText?.(ids) || "";
      const id = copy.split("\n").filter(line => line.includes("#")).flatMap(line => line.slice(line.lastIndexOf("#") + 1).split(",")).join(", ");
      return { ...(copy ? { copy } : {}), ...(id ? { id } : {}) };
    }
    function chipFor(chip) {
      if (!chip.members) {
        return { key: chip.key, label: chip.label, glyph: chip.glyph, card: chip.card,
          onRemove: onRemove ? () => onRemove(chip.ids) : undefined,
          onHover: onHover ? on => onHover(on ? chip.hover : null) : undefined };
      }
      const { parts, members } = chip;
      const ids = members.map(member => itemKey(member.item));
      if (members.length === 1) {
        const [{ item }] = members;
        // Named in its own right, it shows that name; otherwise its part, glyph and number.
        const compact = !parts.own && parts.number && parts.parent ? { name: parts.parent, kind: parts.kind, number: parts.number } : undefined;
        return { key: chip.key, label: referenceName(item, meshData, partName), glyph: parts.kind, ...(compact ? { compact } : {}),
          card: <TopologyDetail reference={item}/>,
          onRemove: onRemove ? () => onRemove(ids) : undefined,
          onHover: onHover ? on => onHover(on ? { referenceId: ids[0] } : null) : undefined };
      }
      const kinds = PLURAL_KINDS[parts.kind] || `${parts.kind}s`;
      return { key: chip.key, label: [parts.parent, `${members.length} ${kinds}`].filter(Boolean).join(" · "),
        compact: { name: parts.parent, kind: parts.kind, count: members.length },
        card: <TopologyRunDetail members={members}/>,
        onRemove: onRemove ? () => onRemove(ids) : undefined,
        onHover: onHover ? on => onHover(on ? (parts.occurrence ? { nodeId: parts.occurrence } : { referenceId: ids[0] }) : null) : undefined };
    }
  }, [references, meshData, partsSize, partName, onRemove, onHover, copyText]);
}
