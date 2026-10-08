import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { shouldRetry } from './api/queryRetry'
import App from './App'
import { ErrorBoundary } from './components/ErrorBoundary'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Registration data changes at most once per scheduled scrape (daily
      // at best), so 10 minutes of freshness costs nothing in accuracy and
      // saves re-running multi-second aggregates on every tab switch.
      staleTime: 1000 * 60 * 10,
      gcTime: 1000 * 60 * 30,
      retry: shouldRetry,
      refetchOnWindowFocus: false,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <ErrorBoundary>
          <App />
        </ErrorBoundary>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
)
