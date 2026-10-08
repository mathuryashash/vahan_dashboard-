// Exports the full row objects a page already has in memory -- every field
// the API returned (share_percent, yoy_growth, etc.), not just what's shown
// on screen, so the CSV carries the same computed metrics visible in the UI.
//
// CSV/formula injection (B14): a spreadsheet treats a cell starting with
// = + - @ (or a tab / carriage return before one) as a formula. Maker and
// model names come from a scraped third-party site, so a value like
// `=HYPERLINK("http://evil","x")` must open as text. Such STRING cells get a
// leading single quote (OWASP's recommendation). Real numbers are left
// alone -- a negative yoy_growth of -5.2 must stay a number, not '-5.2.
const FORMULA_PREFIX = /^[=+\-@\t\r]/;

export function neutraliseFormula(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'number' || typeof value === 'bigint' || typeof value === 'boolean') return String(value);
  const str = String(value);
  return FORMULA_PREFIX.test(str) ? `'${str}` : str;
}

export function escapeCsvCell(value: unknown): string {
  const str = neutraliseFormula(value);
  return /[",\r\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
}

export function downloadCsv(filename: string, rows: Record<string, unknown>[]) {
  if (rows.length === 0) return;
  const headers = Array.from(rows.reduce((set, row) => {
    Object.keys(row).forEach((k) => set.add(k));
    return set;
  }, new Set<string>()));

  const lines = [
    headers.join(','),
    ...rows.map((row) => headers.map((h) => escapeCsvCell(row[h])).join(',')),
  ];

  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename.endsWith('.csv') ? filename : `${filename}.csv`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

// Real multi-sheet workbook (one tab per category, e.g. Two-Wheeler/
// Three-Wheeler/Four-Wheeler) instead of a separate CSV download per
// category -- a plain CSV has no concept of multiple sheets, so this needs
// an actual .xlsx.
export async function downloadXlsx(filename: string, sheets: { name: string; rows: Record<string, unknown>[] }[]) {
  const nonEmptySheets = sheets.filter((s) => s.rows.length > 0);
  if (nonEmptySheets.length === 0) return;

  const ExcelJS = (await import('exceljs')).default;
  const workbook = new ExcelJS.Workbook();

  for (const { name, rows } of nonEmptySheets) {
    // Sheet names can't exceed 31 chars or contain []*?/\: -- Excel rejects
    // the whole file otherwise, not just that one sheet.
    const safeName = name.replace(/[[\]*?/\\:]/g, ' ').slice(0, 31);
    const headers = Array.from(rows.reduce((set, row) => {
      Object.keys(row).forEach((k) => set.add(k));
      return set;
    }, new Set<string>()));

    const sheet = workbook.addWorksheet(safeName);
    sheet.columns = headers.map((h) => ({ header: h, key: h, width: Math.max(12, h.length + 2) }));
    sheet.getRow(1).font = { bold: true };
    rows.forEach((row) => sheet.addRow(row));
  }

  const buffer = await workbook.xlsx.writeBuffer();
  const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename.endsWith('.xlsx') ? filename : `${filename}.xlsx`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
