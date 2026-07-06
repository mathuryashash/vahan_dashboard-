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
          bg: 'bg-rose-50',
          border: 'border-rose-200',
          borderLeft: 'border-l-4 border-l-rose-600',
          icon: 'text-rose-600',
          title: 'text-rose-900',
          desc: 'text-rose-700',
          button: 'hover:bg-rose-100 focus-visible:ring-rose-500',
        };
      case 'warning':
        return {
          bg: 'bg-amber-50',
          border: 'border-amber-200',
          borderLeft: 'border-l-4 border-l-amber-600',
          icon: 'text-amber-600',
          title: 'text-amber-900',
          desc: 'text-amber-700',
          button: 'hover:bg-amber-100 focus-visible:ring-amber-500',
        };
      case 'info':
        return {
          bg: 'bg-blue-50',
          border: 'border-blue-200',
          borderLeft: 'border-l-4 border-l-blue-600',
          icon: 'text-blue-600',
          title: 'text-blue-900',
          desc: 'text-blue-700',
          button: 'hover:bg-blue-100 focus-visible:ring-blue-500',
        };
      case 'success':
        return {
          bg: 'bg-emerald-50',
          border: 'border-emerald-200',
          borderLeft: 'border-l-4 border-l-emerald-600',
          icon: 'text-emerald-600',
          title: 'text-emerald-900',
          desc: 'text-emerald-700',
          button: 'hover:bg-emerald-100 focus-visible:ring-emerald-500',
        };
      default:
        return {
          bg: 'bg-slate-50',
          border: 'border-slate-200',
          borderLeft: 'border-l-4 border-l-slate-600',
          icon: 'text-slate-600',
          title: 'text-slate-900',
          desc: 'text-slate-700',
          button: 'hover:bg-slate-100 focus-visible:ring-slate-500',
        };
    }
  };

  const styles = getStyles();

  return (
    <div
      className={clsx(
        'animate-slideUp',
        styles.bg,
        styles.border,
        'border rounded-lg p-4 mb-4',
        className
      )}
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
