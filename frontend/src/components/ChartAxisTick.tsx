// frontend/src/components/ChartAxisTick.tsx
const MAX_LINE_CHARS = 24;
// Real Indian OEM legal names ("HONDA MOTORCYCLE AND SCOOTER INDIA PVT LTD",
// "SUZUKI MOTORCYCLE INDIA PRIVATE LIMITED") routinely run 40-45 chars --
// 2 lines * 22 chars wasn't enough headroom and was ellipsis-clipping real
// names (found via live testing: full name only visible on tooltip hover,
// not the axis label). 3 * 24 covers effectively all of them.
const MAX_LINES = 3;

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
    // Once on the last allowed line, keep packing every remaining word onto
    // it unconditionally instead of stopping at the char limit -- the tail
    // below truncates it with an ellipsis if it's still too long. The old
    // version broke out of the loop here on the FIRST overflow, silently
    // discarding every word after it (found live: a name near the boundary
    // lost its final word or two even though they'd have fit).
    const onFinalLine = lines.length === MAX_LINES - 1;
    const candidate = current ? `${current} ${word}` : word;
    if (onFinalLine || candidate.length <= MAX_LINE_CHARS || !current) {
      current = candidate;
    } else {
      lines.push(current);
      current = word;
    }
  }
  if (current) lines.push(current);

  if (lines.length > MAX_LINES) {
    lines.length = MAX_LINES;
  }
  const lastIdx = lines.length - 1;
  if (lastIdx >= 0 && lines[lastIdx].length > MAX_LINE_CHARS) {
    lines[lastIdx] = `${lines[lastIdx].slice(0, MAX_LINE_CHARS - 1)}…`;
  }
  return lines;
}

// Recharts' default Pie label sits OUTSIDE the ring with a leader line --
// looks fine on a large chart, but clips against the card edge on these
// dashboard's compact donuts (160-320px containers). Rendered at the
// midpoint of the ring instead: always fits, no leader line needed.
// Suppresses tiny slices (<5%) since a label wouldn't fit inside their
// sliver anyway. Pass directly as <Pie label={insidePieLabel} labelLine={false}>.
export function insidePieLabel({
  cx, cy, midAngle, innerRadius, outerRadius, percent,
}: {
  cx: number; cy: number; midAngle: number; innerRadius: number; outerRadius: number; percent: number;
}) {
  if (!percent || percent <= 0.05) return null;
  const RADIAN = Math.PI / 180;
  const r = innerRadius + (outerRadius - innerRadius) / 2;
  const x = cx + r * Math.cos(-midAngle * RADIAN);
  const y = cy + r * Math.sin(-midAngle * RADIAN);
  return (
    <text x={x} y={y} fill="#fff" textAnchor="middle" dominantBaseline="central" fontSize={10} fontFamily="JetBrains Mono">
      {`${(percent * 100).toFixed(0)}%`}
    </text>
  );
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
