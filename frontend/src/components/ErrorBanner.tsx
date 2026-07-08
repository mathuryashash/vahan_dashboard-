/**
 * Error Banner Component
 * Vahan Dashboard — Dismissible banner for errors, warnings, and alerts
 * 
 * Features:
 * - Multiple severity levels (error, warning, info, success)
 * - Dismissible with close button
 * - Optional action button
 * - Animated entrance/exit
 * - Accessible with ARIA labels
 */

import clsx from 'clsx';
import React from 'react';

export interface ErrorBannerProps {
  /** Banner message/title */
  title: string;

  /** Detailed description (optional) */
  description?: string;

  /** Banner severity level */
  severity?: 'error' | 'warning' | 'info' | 'success';

  /** Icon to display (can be SVG or emoji) */
  icon?: React.ReactNode;

  /** Whether banner is visible */
  isVisible?: boolean;

  /** Callback when close button is clicked */
  onClose?: () => void;

  /** Optional action button */
  action?: {
    label: string;
    onClick: () => void;
  };

  /** Auto-dismiss after milliseconds (0 = never) */
  autoDismiss?: number;

  /** Additional CSS classes */
  className?: string;
}

export function ErrorBanner({
  title,
  description,
  severity = 'error',
  icon,
  isVisible = true,
  onClose,
  action,
  autoDismiss = 0,
  className,
}: ErrorBannerProps) {
  const [visible, setVisible] = React.useState(isVisible);

  // Auto-dismiss after delay
  React.useEffect(() => {
    if (!visible || autoDismiss === 0) return;

    const timer = setTimeout(() => {
      setVisible(false);
      onClose?.();
    }, autoDismiss);

    return () => clearTimeout(timer);
  }, [visible, autoDismiss, onClose]);

  // Update visibility from props
  React.useEffect(() => {
    setVisible(isVisible);
  }, [isVisible]);

  if (!visible) return null;

  const getStyles = () => {
    switch (severity) {
      case 'error':
        return {
          bg: 'bg-[var(--bg-card)]',
          border: 'border-[var(--border)]',
          borderLeft: 'border-l-4',
          borderLeftColor: { borderLeftColor: 'var(--danger)' },
          icon: 'text-[var(--danger)]',
          title: 'text-[var(--text-primary)]',
          desc: 'text-[var(--text-secondary)]',
          button: 'hover:bg-[var(--bg-card-hover)] focus-visible:ring-[var(--danger)]',
        };
      case 'warning':
        return {
          bg: 'bg-[var(--bg-card)]',
          border: 'border-[var(--border)]',
          borderLeft: 'border-l-4',
          borderLeftColor: { borderLeftColor: 'var(--accent)' },
          icon: 'text-[var(--accent)]',
          title: 'text-[var(--text-primary)]',
          desc: 'text-[var(--text-secondary)]',
          button: 'hover:bg-[var(--bg-card-hover)] focus-visible:ring-[var(--accent)]',
        };
      case 'info':
        return {
          bg: 'bg-[var(--bg-card)]',
          border: 'border-[var(--border)]',
          borderLeft: 'border-l-4',
          borderLeftColor: { borderLeftColor: 'var(--chart-5)' },
          icon: 'text-[var(--text-secondary)]',
          title: 'text-[var(--text-primary)]',
          desc: 'text-[var(--text-secondary)]',
          button: 'hover:bg-[var(--bg-card-hover)] focus-visible:ring-[var(--border-strong)]',
        };
      case 'success':
        return {
          bg: 'bg-[var(--bg-card)]',
          border: 'border-[var(--border)]',
          borderLeft: 'border-l-4',
          borderLeftColor: { borderLeftColor: 'var(--success)' },
          icon: 'text-[var(--success)]',
          title: 'text-[var(--text-primary)]',
          desc: 'text-[var(--text-secondary)]',
          button: 'hover:bg-[var(--bg-card-hover)] focus-visible:ring-[var(--success)]',
        };
      default:
        return {
          bg: 'bg-[var(--bg-card)]',
          border: 'border-[var(--border)]',
          borderLeft: 'border-l-4',
          borderLeftColor: { borderLeftColor: 'var(--text-muted)' },
          icon: 'text-[var(--text-muted)]',
          title: 'text-[var(--text-primary)]',
          desc: 'text-[var(--text-secondary)]',
          button: 'hover:bg-[var(--bg-card-hover)] focus-visible:ring-[var(--border-strong)]',
        };
    }
  };

  const styles = getStyles();

  return (
    <div
      className={clsx(
        'animate-entrance',
        styles.bg,
        styles.border,
        styles.borderLeft,
        'border rounded-lg p-4 mb-4',
        className
      )}
      style={styles.borderLeftColor}
      role="alert"
      aria-live="assertive"
      aria-label={`${severity}: ${title}`}
    >
      <div className="flex gap-4">
        {/* Icon */}
        {icon && (
          <div className={clsx('flex-shrink-0', styles.icon)} aria-hidden="true">
            {typeof icon === 'string' ? <span className="text-xl">{icon}</span> : icon}
          </div>
        )}

        {/* Content */}
        <div className="flex-1 min-w-0">
          <h4 className={clsx('font-semibold text-sm', styles.title)}>
            {title}
          </h4>
          {description && (
            <p className={clsx('text-sm mt-1', styles.desc)}>
              {description}
            </p>
          )}

          {/* Action button */}
          {action && (
            <button
              onClick={() => {
                action.onClick();
                setVisible(false);
              }}
              className={clsx(
                'mt-3 inline-flex text-sm font-medium px-3 py-1 rounded',
                'transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2',
                styles.button
              )}
            >
              {action.label}
            </button>
          )}
        </div>

        {/* Close button */}
        {onClose && (
          <button
            onClick={() => {
              setVisible(false);
              onClose();
            }}
            className={clsx(
              'flex-shrink-0 text-xl leading-none opacity-60 hover:opacity-100',
              'transition-opacity focus-visible:outline-none focus-visible:ring-2',
              styles.button
            )}
            aria-label="Close"
            aria-pressed={!visible}
          >
            ×
          </button>
        )}
      </div>
    </div>
  );
}

export default ErrorBanner;

/**
 * Usage Examples:
 * 
 * Error with retry:
 * <ErrorBanner
 *   severity="error"
 *   title="Data load failed"
 *   description="We couldn't fetch the latest data. Please try again."
 *   icon="⚠️"
 *   action={{ label: 'Retry', onClick: refetch }}
 *   onClose={() => dismissBanner()}
 * />
 * 
 * Success message (auto-dismiss):
 * <ErrorBanner
 *   severity="success"
 *   title="Data exported successfully"
 *   icon="✓"
 *   autoDismiss={3000}
 * />
 * 
 * Warning (e.g., partial data):
 * <ErrorBanner
 *   severity="warning"
 *   title="Incomplete data"
 *   description="2 states are currently unavailable. Showing data for 34 states."
 *   icon="ℹ️"
 * />
 * 
 * Info message:
 * <ErrorBanner
 *   severity="info"
 *   title="New data available"
 *   description="Refresh to see the latest registrations."
 *   action={{ label: 'Refresh', onClick: refreshData }}
 * />
 */
