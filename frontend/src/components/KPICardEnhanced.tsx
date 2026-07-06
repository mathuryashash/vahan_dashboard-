/**
 * Enhanced KPI Card Component
 * Vahan Dashboard — Improved from original with design enhancements
 * 
 * Features:
 * - Gradient accent bar (color-coded by type)
 * - Better contrast colors (WCAG AAA)
 * - Proper loading skeleton with shimmer
 * - Accessible ARIA labels
 * - Keyboard navigation support
 * - Hover and focus states
 * - Responsive padding
 */

import clsx from 'clsx';
import React from 'react';

interface KPICardProps {
  label: string;
  value: number | string;
  change?: number; // Percentage change
  type?: 'growth' | 'decline' | 'neutral'; // For accent bar color
  icon?: React.ReactNode;
  suffix?: string;
  loading?: boolean;
  onClick?: () => void;
  ariaLabel?: string;
  isClickable?: boolean;
}

export const KPICard = React.forwardRef<HTMLDivElement, KPICardProps>(
  (
    {
      label,
      value,
      change,
      type = 'neutral',
      icon,
      suffix,
      loading = false,
      onClick,
      ariaLabel,
      isClickable = false,
    },
    ref
  ) => {
    // Determine accent bar color based on type or change
    const getAccentColor = () => {
      if (type === 'growth' || (change !== undefined && change >= 0)) {
        return 'bg-gradient-to-r from-emerald-400 to-emerald-600';
      } else if (type === 'decline' || (change !== undefined && change < 0)) {
        return 'bg-gradient-to-r from-rose-400 to-rose-600';
      }
      return 'bg-gradient-to-r from-blue-400 to-blue-600';
    };

    if (loading) {
      return (
        <div
          ref={ref}
          className="relative overflow-hidden bg-white rounded-lg border border-slate-200 p-6 shadow-sm"
          role="status"
          aria-label={`Loading ${label}`}
        >
          {/* Accent bar */}
          <div className={clsx('absolute top-0 left-0 h-1 w-full', getAccentColor())} />

          {/* Skeleton content */}
          <div className="space-y-3">
            <div className="skeleton skeleton-text w-24" />
            <div className="skeleton skeleton-title" />
            <div className="skeleton skeleton-text w-16" />
          </div>
        </div>
      );
    }

    const containerClasses = clsx(
      'relative overflow-hidden bg-white rounded-lg border border-slate-200 p-6 shadow-sm',
      'transition-all duration-fast',
      'hover:shadow-card-hover hover:border-slate-300',
      isClickable && 'cursor-pointer hover:-translate-y-0.5',
      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2'
    );

    const handleClick = () => {
      if (isClickable && onClick) {
        onClick();
      }
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
      if ((e.key === 'Enter' || e.key === ' ') && isClickable && onClick) {
        e.preventDefault();
        onClick();
      }
    };

    return (
      <div
        ref={ref}
        className={containerClasses}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        role={isClickable ? 'button' : undefined}
        tabIndex={isClickable ? 0 : undefined}
        aria-label={ariaLabel || `${label}: ${value}${suffix || ''}${change !== undefined ? ` (${change >= 0 ? '+' : ''}${change.toFixed(1)}%)` : ''}`}
      >
        {/* Accent bar */}
        <div className={clsx('absolute top-0 left-0 h-1 w-full', getAccentColor())} />

        {/* Main content */}
        <div className="flex items-center justify-between mb-3">
          <span className="text-sm font-medium text-slate-600">{label}</span>
          {icon && (
            <span className="text-slate-400" aria-hidden="true">
              {icon}
            </span>
          )}
        </div>

        {/* Value */}
        <div className="mb-2">
          <div className="font-mono text-3xl font-bold text-slate-900">
            {typeof value === 'number' ? value.toLocaleString('en-IN') : value}
            {suffix && <span className="text-lg text-slate-500 ml-1">{suffix}</span>}
          </div>
        </div>

        {/* Change indicator */}
        {change !== undefined && (
          <div className="flex items-center gap-2">
            <span
              className={clsx(
                'inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded-full',
                change >= 0
                  ? 'bg-emerald-50 text-emerald-700'
                  : 'bg-rose-50 text-rose-700'
              )}
              role="status"
              aria-label={`${change >= 0 ? 'Increased' : 'Decreased'} by ${Math.abs(change).toFixed(1)}%`}
            >
              {change >= 0 ? (
                <span aria-hidden="true">↑</span>
              ) : (
                <span aria-hidden="true">↓</span>
              )}
              <span>{Math.abs(change).toFixed(1)}%</span>
            </span>
            <span className="text-xs text-slate-500">vs last period</span>
          </div>
        )}

        {/* Accessibility: Hidden helper text for context */}
        {isClickable && (
          <span className="sr-only">Click to view details or drill down</span>
        )}
      </div>
    );
  }
);

KPICard.displayName = 'KPICard';

export default KPICard;

/**
 * Usage Examples:
 * 
 * Basic KPI:
 * <KPICard
 *   label="Today's Registrations"
 *   value={12500}
 *   change={15.2}
 *   type="growth"
 * />
 * 
 * Loading state:
 * <KPICard label="Loading..." loading />
 * 
 * Clickable (drill-down):
 * <KPICard
 *   label="Top State"
 *   value="Maharashtra"
 *   isClickable
 *   onClick={() => navigate('/comparison?state=MH')}
 * />
 * 
 * With icon and suffix:
 * <KPICard
 *   label="Growth Rate"
 *   value={23.5}
 *   suffix="%"
 *   icon={<TrendingUp />}
 *   type="growth"
 * />
 */
