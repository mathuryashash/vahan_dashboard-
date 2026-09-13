const GROUPS = ['ICE', 'Hybrid', 'EV'] as const;
export type PowertrainGroup = typeof GROUPS[number];

interface PowertrainToggleProps {
  // string, not PowertrainGroup, to match useAppStore's existing (looser)
  // fuelGroup type -- the actual runtime value is always one of GROUPS or
  // null, enforced by this component itself, not by the store's type.
  value: string | null;
  onChange: (value: PowertrainGroup | null) => void;
  className?: string;
  buttonClassName?: (active: boolean) => string;
}

const DEFAULT_BUTTON_CLASS = (active: boolean) =>
  `flex-1 text-xs font-semibold transition-colors ${
    active
      ? 'bg-[var(--accent)] text-[var(--accent-contrast)]'
      : 'bg-[var(--bg-sunken)] text-[var(--text-secondary)] hover:bg-[var(--bg-card-hover)]'
  }`;

// Repeated identically across Overview/MakersModels/Comparison/Categories
// with no ARIA semantics at all -- assistive tech had no way to tell which
// button (if any) was active. role="group" + aria-pressed per button is the
// correct pattern here (not role="radiogroup"): clicking the active button
// again clears the filter entirely, which isn't standard radio-group
// behavior (always exactly one selected).
export function PowertrainToggle({ value, onChange, className, buttonClassName = DEFAULT_BUTTON_CLASS }: PowertrainToggleProps) {
  return (
    <div
      role="group"
      aria-label="Powertrain filter"
      className={className ?? 'flex rounded-xl border border-[var(--border)] overflow-hidden h-[34px]'}
    >
      {GROUPS.map((group) => (
        <button
          key={group}
          type="button"
          aria-pressed={value === group}
          onClick={() => onChange(value === group ? null : group)}
          className={buttonClassName(value === group)}
        >
          {group}
        </button>
      ))}
    </div>
  );
}
