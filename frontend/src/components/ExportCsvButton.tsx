import { downloadCsv } from '../utils/csv';

export function ExportCsvButton<T extends object>({ filename, rows }: { filename: string; rows: T[] | undefined }) {
  if (!rows || rows.length === 0) return null;
  return (
    <button
      onClick={() => downloadCsv(filename, rows as Record<string, unknown>[])}
      title="Download this data as CSV"
      className="flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] font-mono uppercase tracking-wider text-[var(--text-muted)] hover:text-[var(--text-primary)] border border-[var(--border)] rounded-lg transition-colors"
    >
      <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        <polyline points="7 10 12 15 17 10" />
        <line x1="12" y1="15" x2="12" y2="3" />
      </svg>
      CSV
    </button>
  );
}
