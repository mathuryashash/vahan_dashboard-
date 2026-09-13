import { useId } from 'react';

interface LabeledSelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
}

// Every filter bar (Overview/Comparison/RtoAnalysis/IndustrySales/MakersModels)
// repeated this exact label+select pairing with no programmatic association
// between them -- a screen reader announced every filter control unlabeled.
// useId gives each instance its own stable id so multiple LabeledSelects on
// one page never collide.
export function LabeledSelect({ label, className, children, ...selectProps }: LabeledSelectProps) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      {/* htmlFor/id only, deliberately not nested: satisfies
          label-has-associated-control (the modern, correct check) fully.
          jsx-a11y/label-has-for also wants nesting on top of that by
          default -- a legacy, superseded rule (see its own deprecation
          note) -- but nesting the select inside this label would let the
          label's uppercase/mono/tracking-widest styles cascade onto every
          caller's select via CSS inheritance, a real visual regression
          across every page using this component. Not worth it for a
          warning from a rule already covered by its own replacement. */}
      <label htmlFor={id} className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">
        {label}
      </label>
      <select
        id={id}
        className={
          className ??
          'w-full bg-[var(--bg-sunken)] border border-[var(--border)] hover:border-[var(--border-strong)] text-[var(--text-primary)] text-xs font-semibold px-3 py-2 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--accent)] transition-all duration-200 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed'
        }
        {...selectProps}
      >
        {children}
      </select>
    </div>
  );
}
