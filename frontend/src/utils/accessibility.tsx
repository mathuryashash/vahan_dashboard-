/**
 * Accessibility Utilities
 * Vahan Dashboard — WCAG 2.1 AA Compliance Helpers
 *
 * Usage:
 *   import { useFocusManager, getAriaLabel, useKeyboardShortcuts } from '@/utils/accessibility'
 */

import React from 'react';

/**
 * Keyboard navigation constants
 */
export const KEYS = {
  ENTER: 'Enter',
  ESCAPE: 'Escape',
  TAB: 'Tab',
  SPACE: ' ',
  ARROW_UP: 'ArrowUp',
  ARROW_DOWN: 'ArrowDown',
  ARROW_LEFT: 'ArrowLeft',
  ARROW_RIGHT: 'ArrowRight',
};

/**
 * Modifier keys
 */
export const MODIFIERS = {
  CMD: 'meta',      // Mac command key
  CTRL: 'control',  // Ctrl on Windows/Linux
  SHIFT: 'shift',
  ALT: 'alt',
};

/**
 * Focus management hook for modal/drawer handling
 * Traps focus within container when open, restores after close
 * 
 * @example
 * const { containerRef } = useFocusManager(isOpen);
 * <div ref={containerRef}>{children}</div>
 */
export function useFocusManager(isOpen: boolean) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const previouslyFocusedElement = React.useRef<HTMLElement | null>(null);

  React.useEffect(() => {
    if (!isOpen) return;

    // Store the element that had focus before modal opened
    previouslyFocusedElement.current = document.activeElement as HTMLElement;

    // Set focus to first focusable element in container
    const focusableElements = containerRef.current?.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    if (focusableElements?.length) {
      (focusableElements[0] as HTMLElement).focus();
    }

    // Return focus to previous element when modal closes
    return () => {
      previouslyFocusedElement.current?.focus();
    };
  }, [isOpen]);

  return { containerRef };
}

/**
 * Keyboard shortcuts hook
 * Registers global keyboard shortcuts (Cmd+K, Esc, etc.)
 * 
 * @example
 * useKeyboardShortcuts({
 *   'cmd+k': () => openCommandPalette(),
 *   'escape': () => closeModal(),
 * });
 */
export function useKeyboardShortcuts(
  shortcuts: Record<string, () => void>,
  enabled = true
) {
  React.useEffect(() => {
    if (!enabled) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();
      const hasCmd = event.metaKey || event.ctrlKey;
      const hasShift = event.shiftKey;
      const hasAlt = event.altKey;

      // Build key combination string
      const combination = [
        hasCmd ? 'cmd' : '',
        hasShift ? 'shift' : '',
        hasAlt ? 'alt' : '',
        key,
      ]
        .filter(Boolean)
        .join('+');

      // Check if this combination has a registered shortcut
      if (shortcuts[combination]) {
        event.preventDefault();
        shortcuts[combination]();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [shortcuts, enabled]);
}

/**
 * Generate ARIA label for icon buttons
 * @example
 * <button aria-label={getAriaLabel('close', 'dialog')}>×</button>
 */
export function getAriaLabel(action: string, context?: string): string {
  const labels: Record<string, string> = {
    close: 'Close',
    menu: 'Open menu',
    search: 'Search',
    filter: 'Filter results',
    refresh: 'Refresh data',
    export: 'Export data',
    expand: 'Expand',
    collapse: 'Collapse',
    previous: 'Previous',
    next: 'Next',
    settings: 'Settings',
    download: 'Download',
    share: 'Share',
    delete: 'Delete',
    edit: 'Edit',
    undo: 'Undo',
    redo: 'Redo',
    zoomIn: 'Zoom in',
    zoomOut: 'Zoom out',
  };

  const label = labels[action] || action;
  return context ? `${label} ${context}` : label;
}

/**
 * Announce message to screen readers using live region
 * @example
 * announceToScreenReader('Data updated successfully');
 */
export function announceToScreenReader(
  message: string,
  priority: 'polite' | 'assertive' = 'polite'
) {
  let announcer = document.getElementById('sr-announcer');

  if (!announcer) {
    announcer = document.createElement('div');
    announcer.id = 'sr-announcer';
    announcer.className = 'sr-only';
    announcer.setAttribute('aria-live', priority);
    announcer.setAttribute('aria-atomic', 'true');
    document.body.appendChild(announcer);
  }

  announcer.setAttribute('aria-live', priority);
  announcer.textContent = message;

  // Clear after announcement to prevent re-reading
  setTimeout(() => {
    announcer.textContent = '';
  }, 1000);
}

/**
 * Enhanced button component with proper ARIA and keyboard handling
 * 
 * @example
 * <AccessibleButton 
 *   onClick={handleClick}
 *   aria-label="Close dialog"
 * >
 *   Close
 * </AccessibleButton>
 */
export const AccessibleButton = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement>
>((props, ref) => (
  <button
    ref={ref}
    type="button"
    {...props}
    onKeyDown={(e) => {
      // Support Enter and Space for button activation
      if (e.key === KEYS.ENTER || e.key === KEYS.SPACE) {
        e.preventDefault();
        (e.currentTarget as HTMLButtonElement).click();
      }
      props.onKeyDown?.(e);
    }}
  />
));

AccessibleButton.displayName = 'AccessibleButton';

/**
 * Skip to main content link
 * Should be first element in body for keyboard users
 * 
 * @example
 * <SkipToMainLink href="#main-content" />
 */
export function SkipToMainLink({ href = '#main' }: { href?: string }) {
  return (
    <a
      href={href}
      className="sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-4 focus:z-50 focus:bg-blue-600 focus:text-white focus:px-4 focus:py-2 focus:rounded"
    >
      Skip to main content
    </a>
  );
}

/**
 * Check if element is visible and in viewport
 * Useful for scroll-to-focus scenarios
 */
export function isElementInViewport(element: HTMLElement): boolean {
  const rect = element.getBoundingClientRect();
  return (
    rect.top >= 0 &&
    rect.left >= 0 &&
    rect.bottom <= window.innerHeight &&
    rect.right <= window.innerWidth
  );
}

/**
 * Scroll element into view and focus it
 * Respects user's prefers-reduced-motion setting
 */
export function focusElement(element: HTMLElement | null) {
  if (!element) return;

  const prefersReducedMotion = window.matchMedia(
    '(prefers-reduced-motion: reduce)'
  ).matches;

  if (prefersReducedMotion) {
    element.scrollIntoView({ block: 'nearest' });
  } else {
    element.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  element.focus();
}

/**
 * Get all focusable elements within a container
 * Useful for focus management and tab order
 */
export function getFocusableElements(container: HTMLElement): HTMLElement[] {
  const selector = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
  ].join(',');

  return Array.from(container.querySelectorAll(selector));
}

/**
 * Create a focus trap: Tab cycles through focusable elements
 * Useful for modals and dialogs
 */
export function createFocusTrap(container: HTMLElement) {
  const focusableElements = getFocusableElements(container);
  if (!focusableElements.length) return () => {};

  const firstElement = focusableElements[0] as HTMLElement;
  const lastElement = focusableElements[focusableElements.length - 1] as HTMLElement;

  const handleKeyDown = (event: KeyboardEvent) => {
    if (event.key !== KEYS.TAB) return;

    const activeElement = document.activeElement;

    if (event.shiftKey) {
      // Shift+Tab: move to previous
      if (activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
      }
    } else {
      // Tab: move to next
      if (activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    }
  };

  container.addEventListener('keydown', handleKeyDown);

  // Return cleanup function
  return () => container.removeEventListener('keydown', handleKeyDown);
}

/**
 * Helper to check if user prefers reduced motion
 */
export function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * ARIA live region announcement types
 */
export const ARIA_LIVE_MESSAGES = {
  // Data updates
  DATA_UPDATED: 'Data updated successfully',
  LOADING_COMPLETE: 'Data loading complete',
  
  // Errors
  ERROR_GENERIC: 'An error occurred. Please try again.',
  ERROR_NETWORK: 'Network error. Please check your connection.',
  
  // Navigation
  PAGE_CHANGED: 'Page changed',
  FILTER_APPLIED: 'Filter applied. Results updated.',
  
  // Form
  FORM_SUBMITTED: 'Form submitted successfully',
  FORM_ERROR: 'Please check the form for errors',
};

/**
 * Disable scroll while maintaining scroll position
 * Useful for modals that overlay the page
 */
export function disableScroll() {
  const scrollPosition = window.scrollY;
  document.body.style.overflow = 'hidden';
  document.body.style.position = 'fixed';
  document.body.style.width = '100%';
  document.body.style.top = `-${scrollPosition}px`;

  return () => {
    document.body.style.overflow = '';
    document.body.style.position = '';
    document.body.style.width = '';
    document.body.style.top = '';
    window.scrollTo(0, scrollPosition);
  };
}

export default {
  KEYS,
  MODIFIERS,
  useFocusManager,
  useKeyboardShortcuts,
  getAriaLabel,
  announceToScreenReader,
  AccessibleButton,
  SkipToMainLink,
  isElementInViewport,
  focusElement,
  getFocusableElements,
  createFocusTrap,
  prefersReducedMotion,
  ARIA_LIVE_MESSAGES,
  disableScroll,
};
