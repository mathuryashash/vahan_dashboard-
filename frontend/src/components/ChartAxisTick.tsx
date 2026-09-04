// frontend/src/components/ChartAxisTick.tsx
const MAX_LINE_CHARS = 22;
const MAX_LINES = 2;

// Real maker/category names ("MAHINDRA LIMITED (SWARAJ DIVISION)") run much
// longer than a single line comfortably fits, and Recharts doesn't wrap
// category-axis ticks on its own -- long labels just overflow and overlap
// adjacent rows. Wraps onto up to MAX_LINES lines (word-boundary greedy
// packing) instead of truncating with an ellipsis, so the full name is
// always visible on the chart itself rather than only on hover. Only a name
// that still doesn't fit in MAX_LINES lines gets a trailing "…" on the last
// line -- callers pass the untouched real name as the bar's own data, so
// click-to-select and the value tooltip keep working off the real name
// regardless of how the label wrapped.
function wrapLabel(full: string): string[] {
  const words = full.split(" ");
  const lines: string[] = [];
  let current = "";
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length <= MAX_LINE_CHARS || !current) {
      current = candidate;
    } else {
      lines.push(current);
      current = word;
      if (lines.length === MAX_LINES - 1) break;
    }
  }
  if (current) lines.push(current);

  if (lines.length > MAX_LINES) {
    lines.length = MAX_LINES;
  }
  const consumed = lines.join(" ").length;
  if (consumed < full.length && lines.length === MAX_LINES) {
    const last = lines[MAX_LINES - 1];
    lines[MAX_LINES - 1] = last.length > MAX_LINE_CHARS - 1 ? `${last.slice(0, MAX_LINE_CHARS - 1)}…` : `${last}…`;
  }
  return lines;
}

export function TruncatedYAxisTick({
  x, y, payload, fill,
}: {
  x: number;
  y: number;
  payload: { value: string };
  fill: string;
}) {
  const full = payload.value;
  const lines = wrapLabel(full);
  const lineHeight = 11;
  // Vertically center the whole block on the tick's own y (Recharts positions
  // y at the bar's row center) -- start the first line above center by half
  // the total block height, rather than anchoring on the first line only.
  const startDy = 3 - ((lines.length - 1) * lineHeight) / 2;
  return (
    <text x={x} y={y} textAnchor="end" fontSize={10} fontFamily="JetBrains Mono" fill={fill}>
      {lines.map((line, i) => (
        <tspan key={i} x={x} dy={i === 0 ? startDy : lineHeight}>
          {line}
        </tspan>
      ))}
    </text>
  );
}
