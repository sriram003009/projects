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

export interface TomorrowWatchlistResponse {
  symbols: string[]
  live_fetch?: boolean
  data_source?: string
  cache_hint?: string | null
  rows: TomorrowWatchlistRow[]
}

export interface TomorrowWatchlistRow {
  Stock: string
  'Price (approx.)'?: number | null
  '50-day SMA price'?: number | null
  'vs 50-day SMA'?: string
  '200-day SMA price'?: number | null
  'vs 200-day SMA'?: string
  'MA Signal'?: string
  'Overall Trend'?: string
}

export interface OptionsTrackerRow {
  id: string
  ticker: string
  option_type: 'Call' | 'Put'
  expiration_input?: string | null
  expiration_date: string
  strike: number
  entry_price: number
  added_at?: string | null
  current_price?: number | null
  change_abs?: number | null
  change_pct?: number | null
  direction: 'up' | 'down' | 'flat' | 'unknown'
  price_unavailable?: boolean
}

export interface OptionsTrackerResponse {
  count: number
  live_fetch?: boolean
  data_source?: string
  cache_hint?: string | null
  rows: OptionsTrackerRow[]
}

export interface CacheMeta {
  symbol?: string
  last_bar_date?: string
  cache_updated_at?: string
  num_rows?: number
  file_size_kb?: number
}

export interface WeekdaySessionsResponse {
  ticker: string
  weekday: string
  sessions_returned: number
  live_fetch?: boolean
  data_source?: string
  cache_meta?: CacheMeta | null
  rows: ({
    Date: string
    Weekday: string
    'Prev Close': number | null
    High: number
    Low: number
    Close: number
    'Is Current Session'?: boolean
    'Row Source'?: 'live' | 'cache' | 'historical'
  })[]
}

export interface RecentSessionsResponse {
  ticker: string
  sessions_returned: number
  live_fetch?: boolean
  data_source?: string
  cache_meta?: CacheMeta | null
  rows: ({
    Date: string
    Weekday: string
    Open: number
    High: number
    Low: number
    Close: number
    'Prev Close': number | null
    'Is Current Session'?: boolean
    'Row Source'?: 'live' | 'cache' | 'historical'
  })[]
}

export interface PivotLevelRow {
  Label: string
  Price: number
  Kind: 'resistance' | 'pivot' | 'support'
  Notes: string
  Today?: string
}

export interface PivotLevelsResponse {
  ticker: string
  display_name: string
  formula: string
  session_date?: string | null
  prior_session: {
    Date: string
    Weekday: string
    Open: number
    High: number
    Low: number
    Close: number
  }
  prior_2_session?: {
    Date: string
    Weekday: string
    Low: number
    High?: number
    Close?: number
    Open?: number
  } | null
  pivots: Record<string, number>
  levels: PivotLevelRow[]
  today?: {
    Date: string
    Weekday: string
    Open: number
    High: number
    Low: number
    Close: number
    'Is Current Session'?: boolean
    'Row Source'?: string
  } | null
  summary_lines: string[]
  next_resistance?: {
    Label: string
    Price: number
    Kind: string
    Distance: number
    'Distance Pct': number
  } | null
  live_fetch?: boolean
  data_source?: string
  cache_meta?: CacheMeta | null
}

export interface VixSpySignalLayer {
  Layer: string
  Reading: string
  Bias: string
  Aligned: boolean
}

export interface VixSpySignalResponse {
  signal: 'BUY CALL' | 'BUY PUT' | 'NO TRADE'
  confidence_pct: number
  confidence_label: 'High' | 'Medium' | 'Low'
  summary: string
  disclaimer: string
  regime: 'Contango' | 'Backwardation'
  stress: 'EXTREME_HIGH' | 'EXTREME_LOW' | 'NORMAL'
  trend: 'Bullish' | 'Bearish' | 'Neutral'
  structure_trend?: 'Bullish' | 'Bearish' | 'Neutral'
  session_note?: string | null
  rule_matched: string
  context_note?: string | null
  reasons: string[]
  layers: VixSpySignalLayer[]
  term_structure: {
    vix_symbol: string
    vix3m_symbol: string
    vix_close: number
    vix3m_close: number
    ratio: number
    backwardation_threshold: number
  }
  vix_stress: {
    zscore: number
    lookback_days: number
    mean: number
    std: number
    extreme_high_threshold: number
    extreme_low_threshold: number
  }
  vix_detail: {
    symbol: string
    close: number
    change_1d_pct?: number | null
    level: string
    level_note: string
    vs_20d_avg: number
    spy_implication: string
  }
  spy_technicals: {
    symbol: string
    close: number
    change_1d_pct?: number | null
    vwap?: number | null
    ema9: number
    ema20: number
    rsi14?: number | null
    above_vwap?: boolean
    ema_stack_bull?: boolean
    ema_stack_bear?: boolean
  }
  suggested_strike?: {
    option_type: 'Call' | 'Put'
    reference_price: number
    atm_strike: number
    example_strike: number
    delta_band: string
    notes: string
  } | null
  thresholds?: Record<string, number>
  live_fetch?: boolean
  data_source?: string
  cache_meta?: {
    spy?: CacheMeta | null
    vix?: CacheMeta | null
    vix3m?: CacheMeta | null
  }
}

export interface GexStrikeRow {
  strike: number
  call_gex: number
  put_gex: number
  net_gex: number
  abs_net_gex: number
}

export interface GexResponse {
  ticker: string
  spot: number
  expiration_filter: string
  expiration_label: string
  expirations_used: string[]
  view: 'total' | '0dte'
  has_0dte: boolean
  odte_date?: string | null
  metrics: {
    net_gex: number
    call_gex: number
    put_gex: number
    gamma_flip?: number | null
    regime: string
  }
  call_wall?: { strike: number; gex: number } | null
  put_wall?: { strike: number; gex: number } | null
  gamma_flip?: number | null
  spot_source?: 'live' | 'cache'
  by_strike: GexStrikeRow[]
  formula: string
  disclaimer: string
  live_fetch?: boolean
  data_source?: string
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

  tomorrowWatchlist: (liveFetch: boolean) =>
    request<TomorrowWatchlistResponse>(
      `/api/tomorrow-watchlist?live_fetch=${liveFetch}`,
    ),

  addTomorrowWatchlist: (ticker: string) =>
    request<{ symbol: string; symbols: string[] }>('/api/tomorrow-watchlist', {
      method: 'POST',
      body: JSON.stringify({ ticker }),
    }),

  removeTomorrowWatchlist: (symbol: string) =>
    request<{ symbol: string; symbols: string[] }>(
      `/api/tomorrow-watchlist/${encodeURIComponent(symbol)}`,
      { method: 'DELETE' },
    ),

  optionsTracker: (liveFetch: boolean) =>
    request<OptionsTrackerResponse>(`/api/options-tracker?live_fetch=${liveFetch}`),

  addOptionsTracker: (payload: {
    ticker: string
    optionType: 'Call' | 'Put'
    expirationMmdd: string
    strike: number
    entryPrice?: number | null
    liveFetch: boolean
  }) =>
    request<{ id: string; count: number }>('/api/options-tracker', {
      method: 'POST',
      body: JSON.stringify({
        ticker: payload.ticker,
        option_type: payload.optionType,
        expiration_mmdd: payload.expirationMmdd,
        strike: payload.strike,
        entry_price: payload.entryPrice ?? null,
        live_fetch: payload.liveFetch,
      }),
    }),

  removeOptionsTracker: (id: string) =>
    request<{ id: string; count: number }>(
      `/api/options-tracker/${encodeURIComponent(id)}`,
      { method: 'DELETE' },
    ),

  weekdaySessions: (
    ticker: string,
    weekday: string,
    liveFetch: boolean,
    sessions = 20,
  ) =>
    request<WeekdaySessionsResponse>('/api/weekday-sessions', {
      method: 'POST',
      body: JSON.stringify({
        ticker,
        weekday,
        sessions,
        live_fetch: liveFetch,
      }),
    }),

  recentSessions: (ticker: string, liveFetch: boolean, sessions = 20) =>
    request<RecentSessionsResponse>('/api/recent-sessions', {
      method: 'POST',
      body: JSON.stringify({
        ticker,
        sessions,
        live_fetch: liveFetch,
      }),
    }),

  pivotLevels: (ticker: string, liveFetch: boolean) =>
    request<PivotLevelsResponse>('/api/pivot-levels', {
      method: 'POST',
      body: JSON.stringify({ ticker, live_fetch: liveFetch }),
    }),

  vixSpySignal: (liveFetch: boolean) =>
    request<VixSpySignalResponse>('/api/vix-spy-signal', {
      method: 'POST',
      body: JSON.stringify({ live_fetch: liveFetch }),
    }),

  gex: (
    ticker: string,
    expirationFilter: 'all' | '0dte' | 'nearest' | 'custom',
    liveFetch: boolean,
    options?: { customDate?: string; view?: 'total' | '0dte' },
  ) =>
    request<GexResponse>('/api/gex', {
      method: 'POST',
      body: JSON.stringify({
        ticker,
        expiration_filter: expirationFilter,
        custom_date: options?.customDate ?? null,
        view: options?.view ?? 'total',
        live_fetch: liveFetch,
      }),
    }),

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
