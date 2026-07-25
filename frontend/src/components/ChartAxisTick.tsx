// frontend/src/components/ChartAxisTick.tsx
const MAX_AXIS_LABEL_CHARS = 26;

// Real maker/category names ("MAHINDRA LIMITED (SWARAJ DIVISION)") run much
// longer than the synthetic placeholders these charts' label widths were
// tuned for, and Recharts doesn't wrap/truncate category-axis ticks on its
// own — long labels just overflow and overlap adjacent rows. Truncate for
// display only (an SVG <title> gives the full name on hover); callers pass
// the untouched real name as the bar's own data, so click-to-select and the
// value tooltip keep working off the real name.
export function TruncatedYAxisTick({
  x, y, payload, fill,
}: {
  x: number;
  y: number;
  payload: { value: string };
  fill: string;
}) {
  const full = payload.value;
  const text = full.length > MAX_AXIS_LABEL_CHARS ? `${full.slice(0, MAX_AXIS_LABEL_CHARS - 1)}…` : full;
  return (
    <text x={x} y={y} dy={3} textAnchor="end" fontSize={10} fontFamily="JetBrains Mono" fill={fill}>
      {text !== full && <title>{full}</title>}
      {text}
    </text>
  );
}
