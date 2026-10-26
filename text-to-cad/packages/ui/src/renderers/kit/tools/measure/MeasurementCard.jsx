import { MEASURE_SNAP_LABELS, formatMeasurement, formatMeasurementAngle } from "@text-to-cad/core/lib/viewer/measurement.js";
import { measureLabelText } from "@text-to-cad/core/lib/viewer/measureDimension.js";
import { CoordValue, InfoRow, MonoValue } from "../../inspector/referenceRows.jsx";

// What the pair's headline reading is called: what a CAD measure tool calls it.
const HEADLINE = Object.freeze({
  normal: "Perpendicular distance",
  centers: "Centre to centre",
  min: "Shortest distance",
  angle: "Angle"
});

/**
 * A measurement's card, its chip's in Measure's row: the full reading — what the two entities make
 * (the perpendicular distance of parallel faces, the centre-to-centre of two holes, the angle of two
 * faces or edges, the shortest distance between the two, or the distance between two points) —
 * with the angle and the shortest distance that go with it, the delta along each axis where
 * the reading is a distance between points, and what each end bound to, so an exact edge or face
 * reading is told from a free point off the surface — and, for a mesh's, that it is approximate: a
 * width across two facets of a curve is no diameter. Rows only, as every chip's card is: the card
 * insets them.
 * @param {{ item: { pickA?: object, pickB?: object, measurement: object } }} props
 */
export default function MeasurementCard({ item }) {
  const measurement = item.measurement;
  const kind = measurement?.kind;
  const angle = formatMeasurementAngle(measurement);
  const delta = measurement?.delta;
  const first = MEASURE_SNAP_LABELS[item.pickA?.snapKind];
  const second = MEASURE_SNAP_LABELS[item.pickB?.snapKind];
  const pointsApart = kind === undefined || kind === "points" || kind === "distance";
  // An angle's headline is the angle; the distance between the two goes under it.
  const distance = kind === "angle" && measurement?.minDistance !== null && measurement?.minDistance !== undefined ? formatMeasurement(measurement) : "";
  return <>
    <InfoRow label={HEADLINE[kind] || "Distance"}><MonoValue>{measureLabelText(measurement)}</MonoValue></InfoRow>
    {angle && kind !== "angle" ? <InfoRow label="Angle"><MonoValue>{angle}</MonoValue></InfoRow> : null}
    {distance ? <InfoRow label="Shortest distance"><MonoValue>{distance}</MonoValue></InfoRow> : null}
    {pointsApart && Array.isArray(delta) && delta.length >= 3 ? <InfoRow label="Delta"><CoordValue vector={delta} /></InfoRow> : null}
    {first && second ? <InfoRow label="Between" copy={false}>{`${first} → ${second}`}</InfoRow> : null}
    {measurement?.approximate ? <InfoRow label="Accuracy" copy={false}>Approximate: between the mesh’s triangles</InfoRow> : null}
  </>;
}
