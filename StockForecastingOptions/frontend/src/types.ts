export interface ContractForm {
  ticker: string
  optionType: 'Call' | 'Put'
  expirationMmdd: string
  strike: number
  liveFetch: boolean
}

export interface ContractLookup {
  ticker: string
  option_type: string
  expiration_date: string
  strike: number
  contract_symbol: string
  last_price: number | null
  implied_vol: number | null
  open_interest: number | null
  live_fetch?: boolean
  data_source?: 'cache' | 'live' | string
  cache_badge: string | null
  weekly_trend: WeeklyTrend | null
  sessions: SessionRow[]
  sessions_requested?: number
  sessions_returned?: number
  sessions_note?: string | null
  context: {
    spot: number
    sigma: number
    T0: number
  }
}

export interface SessionRow {
  Date: string
  Open: number
  High: number
  Low: number
  Close: number
  'Stock Close': number | null
  Volume: number
}

export interface WeeklyTrend {
  above_ma: boolean
  note: string
  note_plain: string
}

export interface ApiError {
  detail?: { code?: string; message?: string; details?: Record<string, unknown> }
}
