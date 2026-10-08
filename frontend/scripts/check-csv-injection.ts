// Run: node --experimental-strip-types scripts/check-csv-injection.ts
//   (or: npx tsx scripts/check-csv-injection.ts)
// Asserts utils/csv.ts neutralises spreadsheet formula prefixes (B14).
import { escapeCsvCell } from '../src/utils/csv.ts';

const cases: [unknown, string][] = [
  ['=1+1', "'=1+1"],
  ['+91 98', "'+91 98"],
  ['-cmd', "'-cmd"],
  ['@SUM(A1)', "'@SUM(A1)"],
  ['\tTAB', "'\tTAB"],
  ['\rCR', "\"'\rCR\""],
  ['=HYPERLINK("http://x","y")', `"'=HYPERLINK(""http://x"",""y"")"`],
  ['Maruti Suzuki', 'Maruti Suzuki'],
  ['a,b', '"a,b"'],
  [-5.2, '-5.2'],
  [0, '0'],
  [null, ''],
  [undefined, ''],
];
let failed = 0;
for (const [input, want] of cases) {
  const got = escapeCsvCell(input);
  if (got !== want) { failed++; console.error(`FAIL ${JSON.stringify(input)} -> ${JSON.stringify(got)} (want ${JSON.stringify(want)})`); }
}
console.log(failed ? `${failed} csv check(s) failed` : `csv injection checks: ${cases.length}/${cases.length} ok`);
process.exit(failed ? 1 : 0);
