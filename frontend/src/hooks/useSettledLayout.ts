import { useEffect, useState } from 'react';

/** True starting one paint frame after `isLoading` flips to false. Recharts'
 * ResponsiveContainer measures its container synchronously the instant it
 * mounts; when that mount happens in the very same commit that swaps out a
 * loading skeleton, the browser hasn't necessarily finished layout yet, so
 * Recharts can capture a wrong width/height -- it only self-corrects on a
 * later resize, which a real user may never trigger (seen in practice on the
 * Vehicle Mix / Category Share donuts, rendering as a collapsed sliver until
 * the window was resized). Callers keep showing their own skeleton until this
 * returns true, so the chart's actual mount happens one frame after the
 * skeleton is already gone and layout has settled. */
export function useSettledLayout(isLoading: boolean): boolean {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (isLoading) {
      setReady(false);
      return;
    }
    const raf = requestAnimationFrame(() => setReady(true));
    return () => cancelAnimationFrame(raf);
  }, [isLoading]);
  return ready;
}
