import { useQueryClient } from '@tanstack/react-query';
import { triggerRefresh } from '../api/vahan';
import { useState } from 'react';

interface HeaderProps {
  lastUpdated: string | null;
}

export function Header({ lastUpdated }: HeaderProps) {
  const queryClient = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);

  const handleRefresh = async () => {
    setRefreshing(true);
    await triggerRefresh();
    setTimeout(() => {
      queryClient.invalidateQueries();
      setRefreshing(false);
    }, 2000);
  };

  return (
    <header className="h-14 border-b border-[rgba(255,255,255,0.06)] bg-[#0D1829] flex items-center justify-between px-6 shrink-0">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-cyan-400 flex items-center justify-center shadow-[0_0_20px_rgba(59,130,246,0.4)]">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round">
            <circle cx="12" cy="12" r="10" />
            <line x1="2" y1="12" x2="22" y2="12" />
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
          </svg>
        </div>
        <div>
          <h1 className="text-sm font-bold text-slate-100 tracking-tight">VAHAN SEWA</h1>
          <p className="text-[10px] text-slate-500 uppercase tracking-widest">Vehicle Analytics Observatory</p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        {lastUpdated && (
          <div className="flex items-center gap-1.5 text-[11px] text-slate-500 font-mono">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse-glow" />
            <span>SYNC {lastUpdated}</span>
          </div>
        )}

        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="flex items-center gap-2 px-3 py-1.5 bg-[rgba(59,130,246,0.1)] hover:bg-[rgba(59,130,246,0.2)] border border-[rgba(59,130,246,0.25)] text-blue-400 text-xs font-semibold rounded-lg transition-all duration-200 disabled:opacity-50"
        >
          <svg
            className={refreshing ? 'animate-spin' : ''}
            width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"
          >
            <path d="M21 12a9 9 0 0 1-9 9m0 0a9 9 0 0 1-9-9m9 9v-4m0-8H5a4 4 0 0 0-4 4v4a4 4 0 0 0 4 4h4" />
          </svg>
          {refreshing ? 'SYNCING...' : 'REFRESH'}
        </button>
      </div>
    </header>
  );
}