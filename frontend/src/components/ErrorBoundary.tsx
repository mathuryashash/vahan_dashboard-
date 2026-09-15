import React from 'react';

/** Lifted out of main.tsx so the same boundary can also wrap each route.
 *
 * The root-level one alone meant a single bad render anywhere -- one chart
 * calling .toFixed() on an undefined the backend didn't send -- unmounted
 * the Sidebar, the Header and every working panel along with it. Wrapping
 * the routed page too keeps the app chrome alive so the failure reads as one
 * broken page, not a dead dashboard.
 */
export class ErrorBoundary extends React.Component<
  React.PropsWithChildren<{ fallback?: React.ReactNode }>,
  { hasError: boolean }
> {
  constructor(props: React.PropsWithChildren<{ fallback?: React.ReactNode }>) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError() { return { hasError: true }; }
  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('Unhandled error in component tree:', error, info.componentStack);
  }
  render() {
    if (this.state.hasError) {
      return this.props.fallback ?? (
        <div style={{ padding: 24, textAlign: 'center', color: '#666' }}>
          <p>Something went wrong loading this page.</p>
          <button onClick={() => window.location.reload()}>Reload</button>
        </div>
      );
    }
    return this.props.children;
  }
}
