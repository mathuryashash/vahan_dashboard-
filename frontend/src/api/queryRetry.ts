import { isAxiosError } from 'axios';

/** At most ONE retry, and none where a retry cannot help.
 *
 * The old `retry: 2` with a 30 s axios timeout meant a slow cold endpoint
 * (/categories/ at 15-30 s all-India) could hold a card in skeleton for
 * 3 x 30 s and fire the same expensive query three times against an already
 * struggling backend -- measured 47 s for Overview 2025's Vehicle Mix.
 * - 4xx: the request itself is wrong or forbidden; it will fail identically.
 * - timeout (ECONNABORTED): the server is still computing the first one;
 *   a second copy only competes with it. The slow endpoint gets a longer
 *   timeout instead (api/vahan.ts getCategories).
 * - network error / 5xx: one retry, for a genuinely transient blip. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= 1) return false
  if (isAxiosError(error)) {
    if (error.code === 'ECONNABORTED' || error.code === 'ERR_CANCELED') return false
    const status = error.response?.status
    if (status && status >= 400 && status < 500) return false
  }
  return true
}
