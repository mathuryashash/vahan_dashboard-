import { useId, useMemo, useRef, useState } from 'react';

export interface SearchableOption {
  value: string;
  label: string;
  /** Shown under the name and searched too -- e.g. "Renamed Hero MotoCorp in 2011". */
  note?: string | null;
}

interface SearchableSelectProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: SearchableOption[];
  /** The "no filter" choice, listed first and shown when value is ''. */
  allLabel: string;
}

// Case-, whitespace- and punctuation-insensitive, so "hero honda" finds
// VAHAN's "HERO HONDA MOTORS  LTD" (double space) and "pvt ltd" finds
// "PVT. LTD".
const normalize = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

// "All Brands" carries ~2,000 companies; rendering them all on every open and
// keystroke would lag for no benefit, since nobody scrolls that far. Past
// this many matches the list says so and asks for more letters.
const MAX_RENDERED = 200;

/**
 * A combobox with list autocomplete, following the W3C APG pattern.
 *
 * Not <datalist>: native is the better default, but it renders a secondary
 * label differently in Chrome and Firefox, matches differently per browser,
 * and accepts free text rather than restricting to real options -- and this
 * list needs all three (rename notes, VAHAN's irregular spacing, and a value
 * that must be an exact maker name). Up to ~2,000 options, so type-to-search is
 * the whole point; a plain <select> only jumps by first letter.
 */
export function SearchableSelect({ label, value, onChange, options, allLabel }: SearchableSelectProps) {
  const id = useId();
  const listId = `${id}-list`;
  const optionId = (i: number) => `${id}-opt-${i}`;
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLUListElement>(null);

  const filtered = useMemo(() => {
    const tokens = normalize(query).split(' ').filter(Boolean);
    if (!tokens.length) return [{ value: '', label: allLabel }, ...options];
    // Every word must appear, in any order -- "motocorp hero" works too.
    return options.filter((o) => {
      const haystack = normalize(`${o.label} ${o.note ?? ''}`);
      return tokens.every((t) => haystack.includes(t));
    });
  }, [query, options, allLabel]);

  const shown = filtered.slice(0, MAX_RENDERED);
  // A value missing from options (e.g. a brand with no rows in the newly
  // picked state) is still the active filter, so show it rather than
  // "All Brands" over numbers that are one brand's.
  const selectedLabel = options.find((o) => o.value === value)?.label ?? (value || allLabel);

  const close = () => { setOpen(false); setQuery(''); };
  const commit = (o: SearchableOption) => { onChange(o.value); close(); };

  const moveTo = (i: number) => {
    const next = Math.max(0, Math.min(shown.length - 1, i));
    setActive(next);
    listRef.current?.children[next]?.scrollIntoView({ block: 'nearest' });
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (!open) { setOpen(true); setActive(0); } else moveTo(active + 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (open) moveTo(active - 1);
    } else if (e.key === 'Home' && open) {
      e.preventDefault(); moveTo(0);
    } else if (e.key === 'End' && open) {
      e.preventDefault(); moveTo(shown.length - 1);
    } else if (e.key === 'Enter' && open && shown[active]) {
      e.preventDefault(); commit(shown[active]);
    } else if (e.key === 'Escape' && open) {
      e.preventDefault(); close();
    }
  };

  return (
    <div className="flex flex-col gap-1.5 relative">
      <label htmlFor={id} className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">
        {label}
      </label>
      <input
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && shown[active] ? optionId(active) : undefined}
        autoComplete="off"
        // While open the box holds what you type; the current choice stays
        // visible as the placeholder so you never lose track of it.
        value={open ? query : selectedLabel}
        placeholder={selectedLabel}
        onFocus={() => { setOpen(true); setActive(0); }}
        // After a mouse pick focus stays here, so a click must reopen too.
        onClick={() => setOpen(true)}
        onChange={(e) => { setQuery(e.target.value); setActive(0); setOpen(true); }}
        onBlur={close}
        onKeyDown={onKeyDown}
        className="w-full bg-[var(--bg-sunken)] border border-[var(--border)] hover:border-[var(--border-strong)] text-[var(--text-primary)] text-xs font-semibold px-3 py-2 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--accent)] transition-all duration-200"
      />
      {open && (
        <div className="absolute top-full mt-1 left-0 right-0 min-w-[16rem] bg-[var(--bg-card)] border border-[var(--border)] rounded-xl shadow-lg z-10 text-xs overflow-hidden">
        <ul
          ref={listRef}
          id={listId}
          role="listbox"
          aria-label={label}
          // Keeps focus in the input, so neither a pick nor a scrollbar drag
          // blurs it and closes the list mid-click.
          onMouseDown={(e) => e.preventDefault()}
          className="max-h-72 overflow-y-auto py-1"
        >
          {shown.length === 0 ? (
            <li role="option" aria-selected="false" aria-disabled="true" className="px-3 py-2 text-[var(--text-muted)]">
              No brand matches “{query}”
            </li>
          ) : (
            shown.map((o, i) => (
              <li
                key={o.value || '__all__'}
                id={optionId(i)}
                role="option"
                aria-selected={i === active}
                onMouseDown={() => commit(o)}
                onMouseEnter={() => setActive(i)}
                className={`px-3 py-2 cursor-pointer flex flex-col gap-0.5 ${
                  i === active ? 'bg-[var(--bg-card-hover)]' : ''
                } ${o.value === value ? 'text-[var(--accent)] font-bold' : 'text-[var(--text-primary)]'}`}
              >
                <span>{o.label}</span>
                {o.note && <span className="text-[10px] text-[var(--text-muted)] font-normal">{o.note}</span>}
              </li>
            ))
          )}
        </ul>
        {/* Outside the listbox, which may only contain options. Mounted for
            as long as the list is open, so screen readers announce changes. */}
        <div
          role="status"
          className={filtered.length > MAX_RENDERED ? 'px-3 py-1.5 border-t border-[var(--border)] text-[10px] text-[var(--text-muted)]' : undefined}
        >
          {filtered.length > MAX_RENDERED &&
            `Showing ${MAX_RENDERED} of ${filtered.length.toLocaleString()} — keep typing to narrow`}
        </div>
        </div>
      )}
    </div>
  );
}
