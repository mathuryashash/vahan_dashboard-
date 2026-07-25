/**
 * Empty State Component
 * Vahan Dashboard — Reusable empty state UI
 * 
 * Displays when:
 * - No data for date range
 * - No state selected
 * - No search results
 * - Error occurred
 */

import clsx from 'clsx';
import React from 'react';

export interface EmptyStateProps {
  /**
   * Large icon (SVG or JSX) - typically 64px
   * Can use Lucide icons: <AlertCircle size={64} />
   */
  icon?: React.ReactNode;

  /** Main headline (18px, bold) */
  title: string;

  /** Supporting subtext (14px, gray) */
  description?: string;

  /** Primary action button */
  action?: {
    label: string;
    onClick: () => void;
    icon?: React.ReactNode;
  };

  /** Secondary action button */
  secondaryAction?: {
    label: string;
    onClick: () => void;
  };

  /** Variant for styling (default, error, no-data, search) */
  variant?: 'default' | 'error' | 'no-data' | 'search' | 'no-selection';

  /** Additional CSS classes */
  className?: string;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  secondaryAction,
  variant = 'default',
  className,
}: EmptyStateProps) {
  const getVariantStyles = () => {
    switch (variant) {
      case 'error':
        return {
          iconColor: 'text-[var(--danger)]',
          titleColor: 'text-[var(--text-primary)]',
          descColor: 'text-[var(--text-secondary)]',
        };
      case 'no-data':
        return {
          iconColor: 'text-[var(--accent)]',
          titleColor: 'text-[var(--text-primary)]',
          descColor: 'text-[var(--text-secondary)]',
        };
      case 'search':
        return {
          iconColor: 'text-[var(--accent)]',
          titleColor: 'text-[var(--text-primary)]',
          descColor: 'text-[var(--text-secondary)]',
        };
      case 'no-selection':
        return {
          iconColor: 'text-[var(--text-muted)]',
          titleColor: 'text-[var(--text-primary)]',
          descColor: 'text-[var(--text-secondary)]',
        };
      default:
        return {
          iconColor: 'text-[var(--text-muted)]',
          titleColor: 'text-[var(--text-primary)]',
          descColor: 'text-[var(--text-secondary)]',
        };
    }
  };

  const styles = getVariantStyles();

  return (
    <div
      className={clsx(
        'flex flex-col items-center justify-center py-12 px-4 text-center',
        className
      )}
      role="status"
      aria-label={title}
    >
      {/* Icon */}
      {icon && (
        <div className={clsx('mb-4', styles.iconColor)} aria-hidden="true">
          {typeof icon === 'string' ? (
            <span className="text-6xl">{icon}</span>
          ) : (
            icon
          )}
        </div>
      )}

      {/* Title */}
      <h3 className={clsx('text-lg font-bold mb-2', styles.titleColor)}>
        {title}
      </h3>

      {/* Description */}
      {description && (
        <p className={clsx('text-sm max-w-sm mb-6', styles.descColor)}>
          {description}
        </p>
      )}

      {/* Actions */}
      {(action || secondaryAction) && (
        <div className="flex gap-3 flex-wrap justify-center">
          {action && (
            <button
              onClick={action.onClick}
              className="inline-flex items-center gap-2 px-4 py-2 bg-[var(--accent)] text-[var(--accent-contrast)] rounded-lg font-medium text-sm hover:opacity-90 transition-opacity focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
              aria-label={action.label}
            >
              {action.icon && <span>{action.icon}</span>}
              {action.label}
            </button>
          )}

          {secondaryAction && (
            <button
              onClick={secondaryAction.onClick}
              className="inline-flex items-center gap-2 px-4 py-2 border border-[var(--border-strong)] text-[var(--text-secondary)] rounded-lg font-medium text-sm hover:bg-[var(--bg-card-hover)] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--border-strong)]"
              aria-label={secondaryAction.label}
            >
              {secondaryAction.label}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default EmptyState;
