import { useEffect, useState } from 'react'
import Plot from 'react-plotly.js'
import { api, type MoversResponse } from '../api'
import { CacheHintBanner, DataModeBanner } from './DataModeBanner'
import type { ContractForm, ContractLookup } from '../types'
import { DataTable } from './DataTable'
import { PriceChart } from './PriceChart'

// ---------------------------------------------------------------------------
// Recent Activity
// ---------------------------------------------------------------------------
export function RecentActivityTab({ contract }: { contract: ContractLookup | null }) {
  if (!contract) {
    return (
      <p className="info">
        Fill in the sidebar (ticker, option type, expiration, strike) and click <strong>Fetch Data</strong>.
      </p>
    )
  }

  const trend = contract.weekly_trend
  return (
    <div>
      <header className="contract-header">
        <h3>
          {contract.ticker} {contract.option_type.toUpperCase()} · Strike {contract.strike} · Exp{' '}
          {contract.expiration_date}
        </h3>
        <p className="muted">Contract: {contract.contract_symbol}</p>
        <div className="metrics">
          <span>Last: {contract.last_price != null ? `$${contract.last_price.toFixed(2)}` : '—'}</span>
          <span>
            IV: {contract.implied_vol != null ? `${(contract.implied_vol * 100).toFixed(2)}%` : '—'}
          </span>
          <span>OI: {contract.open_interest?.toLocaleString() ?? '—'}</span>
        </div>
        {contract.cache_badge && <p className="badge">{contract.cache_badge}</p>}
        {contract.data_source && (
          <p className="muted">
            Loaded from: <strong>{contract.data_source === 'live' ? 'Yahoo Finance (live)' : 'disk cache'}</strong>
          </p>
        )}
      </header>

      {trend && (
        <div className={trend.above_ma ? 'banner success' : 'banner error'}>
          <h4>{contract.ticker} weekly trend</h4>
          <p>{trend.note_plain}</p>
        </div>
      )}

      <h4>Last 30 Trading Sessions</h4>
      <DataTable rows={contract.sessions as unknown as Record<string, unknown>[]} />
      <PriceChart sessions={contract.sessions} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Forecasts
// ---------------------------------------------------------------------------
export function ForecastsTab({ form, contract }: { form: ContractForm; contract: ContractLookup | null }) {
  const [data, setData] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [subTab, setSubTab] = useState('A')

  useEffect(() => {
    if (!contract) return
    setLoading(true)
    setError(null)
    api
      .forecasts(form)
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refresh when contract identity changes
  }, [contract?.contract_symbol, form.liveFetch])

  if (!contract) return <p className="info">Load a contract from the sidebar first.</p>
  if (loading) return <p>Running forecast models…</p>
  if (error) return <p className="error">{error}</p>
  if (!data) return null

  const metrics = data.metrics as Record<string, number>
  const summary = (data.summary as Record<string, unknown>[]) ?? []
  const mc = (data.monte_carlo as Record<string, unknown>[]) ?? []
  const histDates = (data.history_dates as string[]) ?? []
  const histCloses = (data.history_closes as number[]) ?? []
  const fcDates = (data.forecast_dates as string[]) ?? []

  const mcP50 = mc.map((r) => r.o_p50 as number)
  const mcP10 = mc.map((r) => r.o_p10 as number)
  const mcP90 = mc.map((r) => r.o_p90 as number)

  return (
    <div>
      <p className="muted">
        Four statistical models — illustrative only, not financial advice. All forecast the underlying
        first, then revalue via Black-Scholes.
      </p>
      <div className="metrics">
        <span>Spot: ${metrics.spot?.toFixed(2)}</span>
        <span>Vol: {metrics.sigma_pct?.toFixed(2)}%</span>
        <span>TTE: {Math.round(metrics.T0_days ?? 0)}d</span>
        <span>Horizon: {metrics.forecast_days}d</span>
      </div>

      <h4>Day-{metrics.forecast_days} comparison</h4>
      <DataTable rows={summary} />

      <div className="sub-tabs">
        {['A', 'B', 'C', 'D'].map((t) => (
          <button
            key={t}
            type="button"
            className={subTab === t ? 'sub-tab active' : 'sub-tab'}
            onClick={() => setSubTab(t)}
          >
            {t === 'A' && 'Monte Carlo'}
            {t === 'B' && 'Patterns'}
            {t === 'C' && 'ARIMA'}
            {t === 'D' && 'Random Forest'}
          </button>
        ))}
      </div>

      {subTab === 'A' && (
        <>
          <Plot
            data={[
              { x: histDates, y: histCloses, type: 'scatter', mode: 'lines+markers', name: 'History' },
              { x: fcDates, y: mcP90, type: 'scatter', mode: 'lines', name: 'P90', line: { dash: 'dot' } },
              { x: fcDates, y: mcP50, type: 'scatter', mode: 'lines+markers', name: 'P50' },
              { x: fcDates, y: mcP10, type: 'scatter', mode: 'lines', name: 'P10', line: { dash: 'dot' } },
            ]}
            layout={{ title: 'Monte Carlo option forecast', height: 400, hovermode: 'x unified' }}
            style={{ width: '100%' }}
          />
          <DataTable rows={mc} />
        </>
      )}

      {subTab === 'B' && (
        <>
          <p>
            Recent patterns:{' '}
            {((data.recent_patterns as string[]) ?? []).join(', ') || 'None in last 3 sessions'}
          </p>
          {data.pattern_forecast != null && (
            <pre>{JSON.stringify(data.pattern_forecast, null, 2)}</pre>
          )}
          <DataTable rows={(data.pattern_stats as Record<string, unknown>[]) ?? []} />
        </>
      )}

      {subTab === 'C' && (
        <>
          <Plot
            data={[
              { x: histDates, y: histCloses, type: 'scatter', mode: 'lines+markers', name: 'History' },
              {
                x: fcDates,
                y: ((data.arima as Record<string, unknown>[]) ?? []).map((r) => r.o_mean as number),
                type: 'scatter',
                mode: 'lines+markers',
                name: 'ARIMA',
              },
            ]}
            layout={{ title: 'ARIMA forecast', height: 400 }}
            style={{ width: '100%' }}
          />
          <DataTable rows={(data.arima as Record<string, unknown>[]) ?? []} />
        </>
      )}

      {subTab === 'D' && (
        <>
          <Plot
            data={[
              { x: histDates, y: histCloses, type: 'scatter', mode: 'lines+markers', name: 'History' },
              {
                x: fcDates,
                y: ((data.random_forest as Record<string, unknown>[]) ?? []).map(
                  (r) => r.o_predicted as number,
                ),
                type: 'scatter',
                mode: 'lines+markers',
                name: 'RF',
              },
            ]}
            layout={{ title: 'Random Forest forecast', height: 400 }}
            style={{ width: '100%' }}
          />
          <DataTable rows={(data.random_forest as Record<string, unknown>[]) ?? []} />
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// What-If
// ---------------------------------------------------------------------------
export function WhatIfTab({ form, contract }: { form: ContractForm; contract: ContractLookup | null }) {
  const [targetPrice, setTargetPrice] = useState(150)
  const [targetMmdd, setTargetMmdd] = useState('')
  const [ivPct, setIvPct] = useState(30)
  const [data, setData] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (contract?.context?.spot) {
      setTargetPrice(Math.round(contract.context.spot * 100) / 100)
      setIvPct(Math.round((contract.context.sigma ?? 0.3) * 10000) / 100)
    }
  }, [contract])

  const run = () => {
    if (!contract) return
    setLoading(true)
    setError(null)
    api
      .whatIf(form, targetPrice, targetMmdd, ivPct)
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  if (!contract) return <p className="info">Load a contract from the sidebar first.</p>

  const sens = data?.sensitivity as Record<string, number[]> | undefined
  const greeks = data?.greeks as Record<string, number> | undefined
  const scn = data?.scenario as Record<string, number> | undefined

  return (
    <div>
      <div className="form-row">
        <label>
          Target price ($)
          <input
            type="number"
            value={targetPrice}
            onChange={(e) => setTargetPrice(parseFloat(e.target.value))}
          />
        </label>
        <label>
          Target date (MM/DD)
          <input value={targetMmdd} onChange={(e) => setTargetMmdd(e.target.value)} placeholder="06/10" />
        </label>
        <label>
          Scenario IV (%)
          <input type="number" value={ivPct} onChange={(e) => setIvPct(parseFloat(e.target.value))} />
        </label>
        <button type="button" className="btn primary" onClick={run} disabled={loading}>
          Run scenario
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {greeks && (
        <div className="metrics">
          <span>Δ {greeks.delta?.toFixed(4)}</span>
          <span>Γ {greeks.gamma?.toFixed(4)}</span>
          <span>Θ ${greeks.theta_per_day?.toFixed(4)}/d</span>
          <span>V {greeks.vega_per_pct?.toFixed(4)}/%</span>
          <span>ρ {greeks.rho_per_pct?.toFixed(4)}/%</span>
        </div>
      )}
      {scn && (
        <div className="metrics">
          <span>Current: ${scn.current_price?.toFixed(2)}</span>
          <span>Greeks est: ${scn.greeks_estimate?.toFixed(2)}</span>
          <span>BS reprice: ${scn.bs_reprice?.toFixed(2)}</span>
        </div>
      )}
      {sens && (
        <Plot
          data={[
            { x: sens.s_grid, y: sens.prices_today, type: 'scatter', name: 'Today' },
            { x: sens.s_grid, y: sens.prices_target, type: 'scatter', name: 'Target date', line: { dash: 'dash' } },
          ]}
          layout={{ title: 'Sensitivity — option vs underlying', height: 380 }}
          style={{ width: '100%' }}
        />
      )}
      {data && <DataTable rows={(data.pnl_attribution as Record<string, unknown>[]) ?? []} />}
      {data && <DataTable rows={(data.price_grid as Record<string, unknown>[]) ?? []} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Track the Best
// ---------------------------------------------------------------------------
export function TrackBestTab() {
  const [live, setLive] = useState(false)
  const [data, setData] = useState<MoversResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setError(null)
    api.movers(live).then(setData).catch((e: Error) => setError(e.message))
  }

  useEffect(() => {
    load()
  }, [live])

  return (
    <div>
      <DataModeBanner live={live} />
      <label className="checkbox">
        <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
        Fetch live data for watchlist
      </label>
      <button type="button" className="btn" onClick={load}>
        Refresh
      </button>
      {error && <p className="error">{error}</p>}
      <CacheHintBanner message={data?.cache_hint} />
      {data && !live && data.unavailable && data.unavailable.length > 0 && !data.cache_hint && (
        <div className="banner warn">
          No cached data for: {data.unavailable.join(', ')}. Check Fetch live data and Refresh.
        </div>
      )}
      {data && (
        <>
          <h4>Losers</h4>
          <DataTable rows={data.losers_table} />
          <h4>Gainers</h4>
          <DataTable rows={data.gainers_table} />
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Quick Summary
// ---------------------------------------------------------------------------
export function QuickSummaryTab() {
  const [live, setLive] = useState(false)
  const [rows, setRows] = useState<Record<string, unknown>[]>([])
  const [cacheHint, setCacheHint] = useState<string | null>(null)

  useEffect(() => {
    api.summary(live).then((d) => {
      setRows(d.rows)
      setCacheHint(d.cache_hint ?? null)
    })
  }, [live])

  return (
    <div>
      <DataModeBanner live={live} />
      <label className="checkbox">
        <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
        Fetch live data
      </label>
      <CacheHintBanner message={cacheHint} />
      <h4>50-day &amp; 200-day SMA — watchlist</h4>
      <DataTable rows={rows} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Check SMA
// ---------------------------------------------------------------------------
export function CheckSmaTab() {
  const [input, setInput] = useState('NVDA')
  const [live, setLive] = useState(false)
  const [result, setResult] = useState<{
    rows: Record<string, unknown>[]
    vertical: Record<string, unknown>[]
    weekly_trends: { stock: string; text: string }[]
    cache_hint?: string | null
  } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = () => {
    setError(null)
    api
      .smaCheck(input, live)
      .then(setResult)
      .catch((e: Error) => setError(e.message))
  }

  return (
    <div>
      <DataModeBanner live={live} />
      <div className="form-row">
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="NVDA, MSFT" />
        <label className="checkbox">
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
          Fetch live data
        </label>
        <button type="button" className="btn primary" onClick={run}>
          Check
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      <CacheHintBanner message={result?.cache_hint} />
      {result && (
        <>
          <DataTable rows={result.vertical} />
          {result.weekly_trends.map((w) => (
            <div key={w.stock} className="weekly-block">
              <strong>{w.stock}</strong>
              <p>{w.text}</p>
            </div>
          ))}
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Calls vs Puts
// ---------------------------------------------------------------------------
export function CallsPutsTab() {
  const [ticker, setTicker] = useState('SPY')
  const [exp, setExp] = useState('')
  const [live, setLive] = useState(false)
  const [data, setData] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = () => {
    setError(null)
    api
      .putCall(ticker, exp, live)
      .then(setData)
      .catch((e: Error) => setError(e.message))
  }

  const stats = data?.stats as Record<string, unknown> | undefined

  return (
    <div>
      <DataModeBanner live={live} />
      <div className="form-row">
        <input value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} />
        <input value={exp} onChange={(e) => setExp(e.target.value)} placeholder="MM/DD" />
        <label className="checkbox">
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
          Fetch live data
        </label>
        <button type="button" className="btn primary" onClick={run}>
          Analyze
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {stats && (
        <>
          <div className="metrics">
            <span>Call vol: {Number(stats.call_volume).toLocaleString()}</span>
            <span>Put vol: {Number(stats.put_volume).toLocaleString()}</span>
            <span>P/C: {Number(stats.put_call_ratio_volume).toFixed(2)}</span>
            <span>Vol winner: {String(stats.volume_winner)}</span>
          </div>
          <Plot
            data={[
              {
                x: ['Calls', 'Puts'],
                y: [stats.call_volume, stats.put_volume],
                type: 'bar',
                marker: { color: ['#26a69a', '#ef5350'] },
                name: 'Volume',
              },
            ]}
            layout={{ title: 'Volume', height: 320 }}
            style={{ width: '100%' }}
          />
          <h4>Top call strikes</h4>
          <DataTable rows={(data?.top_call_strikes as Record<string, unknown>[]) ?? []} />
          <h4>Top put strikes</h4>
          <DataTable rows={(data?.top_put_strikes as Record<string, unknown>[]) ?? []} />
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Weekday sessions — last 10 Mon/Tue/Wed/Thu/Fri bars
// ---------------------------------------------------------------------------
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'] as const
type WeekdayName = (typeof WEEKDAYS)[number]

function formatMoney(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  return `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function formatDelta(delta: number): string {
  const sign = delta >= 0 ? '+' : '−'
  return `${sign}$${Math.abs(delta).toFixed(2)}`
}

function formatCloseChange(delta: number, prevClose: number): string {
  const pct = (delta / prevClose) * 100
  const pctSign = pct >= 0 ? '+' : '−'
  return `${formatDelta(delta)} (${pctSign}${Math.abs(pct).toFixed(2)}%)`
}

function closeDirection(
  close: number,
  prevClose: number | null,
): 'up' | 'down' | 'flat' | 'unknown' {
  if (prevClose == null || Number.isNaN(prevClose)) return 'unknown'
  if (close > prevClose) return 'up'
  if (close < prevClose) return 'down'
  return 'flat'
}

function WeekdaySessionsTable({
  rows,
}: {
  rows: import('../api').WeekdaySessionsResponse['rows']
}) {
  if (!rows.length) return <p className="muted">No sessions.</p>

  return (
    <div className="table-wrap weekday-table">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Weekday</th>
            <th>Prev Close</th>
            <th>High</th>
            <th>Low</th>
            <th>Close</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const dir = closeDirection(row.Close, row['Prev Close'])
            const delta =
              row['Prev Close'] != null ? row.Close - row['Prev Close'] : null
            return (
              <tr key={row.Date}>
                <td>{row.Date}</td>
                <td>{row.Weekday}</td>
                <td>{formatMoney(row['Prev Close'])}</td>
                <td>{formatMoney(row.High)}</td>
                <td>{formatMoney(row.Low)}</td>
                <td
                  className={
                    dir === 'up'
                      ? 'close-up'
                      : dir === 'down'
                        ? 'close-down'
                        : 'close-flat'
                  }
                >
                  {formatMoney(row.Close)}
                  {dir === 'up' && delta != null && row['Prev Close'] != null && (
                    <span className="close-delta">
                      {' '}
                      ▲ {formatCloseChange(delta, row['Prev Close'])}
                    </span>
                  )}
                  {dir === 'down' && delta != null && row['Prev Close'] != null && (
                    <span className="close-delta">
                      {' '}
                      ▼ {formatCloseChange(delta, row['Prev Close'])}
                    </span>
                  )}
                  {dir === 'flat' && <span className="close-delta"> — unchanged</span>}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function WeekdaySessionsTab() {
  const [ticker, setTicker] = useState('SPY')
  const [weekday, setWeekday] = useState<WeekdayName>('Monday')
  const [live, setLive] = useState(false)
  const [data, setData] = useState<import('../api').WeekdaySessionsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = () => {
    setLoading(true)
    setError(null)
    api
      .weekdaySessions(ticker, weekday, live, 10)
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  return (
    <div>
      <h3>Weekday Sessions — Prev Close, High, Low, Close</h3>
      <p className="muted">
        Pull the last <strong>10 sessions</strong> for a chosen weekday (Mon–Fri only).
        <strong> Prev Close</strong> is the prior trading day&apos;s close before each session.
        <strong> Close</strong> is <span className="close-up-inline">green</span> when above prev close,{' '}
        <span className="close-down-inline">red</span> when below.
      </p>

      <DataModeBanner live={live} />

      <div className="form-row">
        <label>
          Ticker
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            placeholder="SPY"
          />
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
          Fetch live data
        </label>
        <button type="button" className="btn primary" onClick={load} disabled={loading}>
          {loading ? 'Loading…' : 'Pull sessions'}
        </button>
      </div>

      <p className="weekday-label">Select weekday</p>
      <div className="weekday-buttons">
        {WEEKDAYS.map((day) => (
          <button
            key={day}
            type="button"
            className={`weekday-btn ${weekday === day ? 'active' : ''}`}
            onClick={() => setWeekday(day)}
          >
            {day.slice(0, 3)}
          </button>
        ))}
      </div>

      {error && <p className="error">{error}</p>}

      {data && (
        <>
          <p className="muted">
            {data.ticker} · {data.weekday} · {data.sessions_returned} session(s) ·{' '}
            {data.data_source === 'live' ? 'live' : 'cache'}
          </p>
          <WeekdaySessionsTable rows={data.rows} />
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Stocks on Watchlist — user list for tomorrow + 50/200 MA signal
// ---------------------------------------------------------------------------
function signalClass(signal: string | undefined): string {
  if (signal === 'Bullish') return 'signal-bullish'
  if (signal === 'Bearish') return 'signal-bearish'
  if (signal === 'Mixed') return 'signal-mixed'
  return 'signal-unknown'
}

export function StocksOnWatchlistTab() {
  const [live, setLive] = useState(false)
  const [input, setInput] = useState('')
  const [data, setData] = useState<import('../api').TomorrowWatchlistResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)

  const load = () => {
    setError(null)
    api
      .tomorrowWatchlist(live)
      .then(setData)
      .catch((e: Error) => setError(e.message))
  }

  useEffect(() => {
    load()
  }, [live])

  const addTicker = () => {
    const t = input.trim().toUpperCase()
    if (!t) return
    setAdding(true)
    setError(null)
    api
      .addTomorrowWatchlist(t)
      .then(() => {
        setInput('')
        load()
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setAdding(false))
  }

  const removeTicker = (symbol: string) => {
    setError(null)
    api
      .removeTomorrowWatchlist(symbol)
      .then(load)
      .catch((e: Error) => setError(e.message))
  }

  return (
    <div>
      <h3>Stocks on Watchlist — for tomorrow</h3>
      <p className="muted">
        Build your personal list. Each row shows whether price is{' '}
        <strong>Bullish</strong> (above 50-day &amp; 200-day SMA),{' '}
        <strong>Bearish</strong> (below both), or <strong>Mixed</strong>.
      </p>

      <DataModeBanner live={live} />

      <div className="form-row">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value.toUpperCase())}
          placeholder="e.g. NVDA, AMD, ^SPX"
          onKeyDown={(e) => e.key === 'Enter' && addTicker()}
        />
        <button type="button" className="btn primary" onClick={addTicker} disabled={adding}>
          {adding ? 'Adding…' : 'Add to watchlist'}
        </button>
        <label className="checkbox">
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
          Fetch live data
        </label>
        <button type="button" className="btn" onClick={load}>
          Refresh
        </button>
      </div>

      {error && <p className="error">{error}</p>}
      <CacheHintBanner message={data?.cache_hint} />

      {!data?.rows?.length ? (
        <p className="info">
          No tickers yet — type a symbol above and click <strong>Add to watchlist</strong>.
        </p>
      ) : (
        <div className="table-wrap">
          <table className="watchlist-table">
            <thead>
              <tr>
                <th>Stock</th>
                <th>Price</th>
                <th>50-day SMA</th>
                <th>vs 50-day</th>
                <th>200-day SMA</th>
                <th>vs 200-day</th>
                <th>MA Signal</th>
                <th>Overall</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={row.Stock}>
                  <td><strong>{row.Stock}</strong></td>
                  <td>{row['Price (approx.)'] != null ? `$${Number(row['Price (approx.)']).toFixed(2)}` : '—'}</td>
                  <td>{row['50-day SMA price'] != null ? `$${Number(row['50-day SMA price']).toFixed(2)}` : '—'}</td>
                  <td>{row['vs 50-day SMA'] ?? '—'}</td>
                  <td>{row['200-day SMA price'] != null ? `$${Number(row['200-day SMA price']).toFixed(2)}` : '—'}</td>
                  <td>{row['vs 200-day SMA'] ?? '—'}</td>
                  <td>
                    <span className={`signal-pill ${signalClass(row['MA Signal'])}`}>
                      {row['MA Signal'] ?? '—'}
                    </span>
                  </td>
                  <td>{row['Overall Trend'] ?? '—'}</td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-sm danger"
                      onClick={() => removeTicker(row.Stock)}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Cached Data
// ---------------------------------------------------------------------------
export function CachedDataTab({
  onLoadContract,
}: {
  onLoadContract: (ticker: string, optionType: 'Call' | 'Put', exp: string, strike: number) => void
}) {
  const [contracts, setContracts] = useState<Record<string, unknown>[]>([])
  const [selected, setSelected] = useState('')
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null)

  useEffect(() => {
    api.cacheContracts().then(setContracts)
  }, [])

  useEffect(() => {
    if (!selected) return
    api.cacheContract(selected).then(setDetail)
  }, [selected])

  return (
    <div>
      <h4>Cached option contracts on disk</h4>
      <select value={selected} onChange={(e) => setSelected(e.target.value)}>
        <option value="">Select a contract…</option>
        {contracts.map((c) => (
          <option key={String(c.contract_symbol)} value={String(c.contract_symbol)}>
            {String(c.ticker)} {String(c.option_type)} {String(c.strike)} exp {String(c.expiration)}
          </option>
        ))}
      </select>
      {detail && (
        <>
          <DataTable rows={(detail.sessions as Record<string, unknown>[]) ?? []} />
          <PriceChart
            sessions={(detail.sessions as import('../types').SessionRow[]) ?? []}
            title="Cached contract history"
          />
          <button
            type="button"
            className="btn primary"
            onClick={() => {
              const exp = String(detail.expiration)
              const [, mm, dd] = exp.split('-')
              onLoadContract(
                String(detail.ticker),
                detail.option_type as 'Call' | 'Put',
                `${mm}/${dd}`,
                Number(detail.strike),
              )
            }}
          >
            Load into sidebar form
          </button>
        </>
      )}
    </div>
  )
}
