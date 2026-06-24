import type { ContractForm, ContractLookup } from './types'

export class ApiError extends Error {
  code?: string
  needsLiveFetch: boolean

  constructor(message: string, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.needsLiveFetch =
      !!code?.startsWith('no_cached') || code === 'insufficient_underlying_cache'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    const detail = err?.detail
    const msg =
      (typeof detail === 'object' && detail?.message) ||
      (typeof detail === 'string' ? detail : null) ||
      res.statusText
    const code = typeof detail === 'object' ? detail?.code : undefined
    throw new ApiError(msg, code)
  }
  return res.json() as Promise<T>
}

export interface MoversResponse {
  live_fetch?: boolean
  data_source?: string
  cache_hint?: string | null
  gainers: Record<string, unknown>[]
  losers: Record<string, unknown>[]
  gainers_table: Record<string, unknown>[]
  losers_table: Record<string, unknown>[]
  unavailable?: string[]
}

export interface SummaryResponse {
  live_fetch?: boolean
  data_source?: string
  cache_hint?: string | null
  rows: Record<string, unknown>[]
}

export interface SmaCheckResponse {
  live_fetch?: boolean
  data_source?: string
  cache_hint?: string | null
  rows: Record<string, unknown>[]
  vertical: Record<string, unknown>[]
  weekly_trends: { stock: string; text: string }[]
}

export interface CacheSummary {
  num_files?: number
  total_kb?: number
}

export const api = {
  health: () => request<{ status: string }>('/api/health'),

  lookupContract: (form: ContractForm) =>
    request<ContractLookup>('/api/contract/lookup', {
      method: 'POST',
      body: JSON.stringify({
        ticker: form.ticker,
        option_type: form.optionType,
        expiration_mmdd: form.expirationMmdd,
        strike: form.strike,
        live_fetch: form.liveFetch,
      }),
    }),

  forecasts: (form: ContractForm) =>
    request<Record<string, unknown>>('/api/contract/forecasts', {
      method: 'POST',
      body: JSON.stringify({
        ticker: form.ticker,
        option_type: form.optionType,
        expiration_mmdd: form.expirationMmdd,
        strike: form.strike,
        live_fetch: form.liveFetch,
      }),
    }),

  whatIf: (
    form: ContractForm,
    targetPrice: number,
    targetMmdd: string,
    scenarioIvPct: number,
  ) =>
    request<Record<string, unknown>>('/api/contract/what-if', {
      method: 'POST',
      body: JSON.stringify({
        ticker: form.ticker,
        option_type: form.optionType,
        expiration_mmdd: form.expirationMmdd,
        strike: form.strike,
        live_fetch: form.liveFetch,
        target_price: targetPrice,
        target_mmdd: targetMmdd,
        scenario_iv_pct: scenarioIvPct,
      }),
    }),

  movers: (liveFetch: boolean) =>
    request<MoversResponse>(`/api/watchlist/movers?live_fetch=${liveFetch}`),

  summary: (liveFetch: boolean) =>
    request<SummaryResponse>(`/api/watchlist/summary?live_fetch=${liveFetch}`),

  smaCheck: (tickers: string, liveFetch: boolean) =>
    request<SmaCheckResponse>('/api/sma/check', {
      method: 'POST',
      body: JSON.stringify({ tickers, live_fetch: liveFetch }),
    }),

  putCall: (ticker: string, expirationMmdd: string, liveFetch: boolean) =>
    request<Record<string, unknown>>('/api/put-call/analyze', {
      method: 'POST',
      body: JSON.stringify({
        ticker,
        expiration_mmdd: expirationMmdd,
        live_fetch: liveFetch,
      }),
    }),

  cacheContracts: () => request<Record<string, unknown>[]>('/api/cache/contracts'),

  cacheContract: (symbol: string) =>
    request<Record<string, unknown>>(`/api/cache/contracts/${encodeURIComponent(symbol)}`),

  cacheSummary: () => request<CacheSummary>('/api/cache/summary'),

  clearCache: (confirm: boolean, symbol?: string) =>
    request<{ cleared: number }>('/api/cache/clear', {
      method: 'POST',
      body: JSON.stringify({ confirm, symbol: symbol ?? null }),
    }),
}
