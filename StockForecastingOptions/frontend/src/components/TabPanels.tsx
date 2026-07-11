import { useEffect, useState } from 'react'
import Plot from 'react-plotly.js'
import { api, type MoversResponse, type VixSpySignalResponse } from '../api'
import { CacheHintBanner, CacheUpdatedBanner, DataModeBanner } from './DataModeBanner'
import type { ContractForm, ContractLookup } from '../types'
import { DataTable } from './DataTable'
import { PriceChart } from './PriceChart'

// ---------------------------------------------------------------------------
// Last 30 sessions — contract OHLC (Recent Activity + Cached Data)
// ---------------------------------------------------------------------------
function withPrevClose(
  sessions: import('../types').SessionRow[],
): (import('../types').SessionRow & { 'Prev Close': number | null })[] {
  return sessions.map((row, i) => ({
    ...row,
    'Prev Close': i > 0 ? sessions[i - 1].Close : null,
  }))
}

function formatClosePct(delta: number, prevClose: number): string {
  const pct = (delta / prevClose) * 100
  const sign = pct >= 0 ? '+' : '−'
  return `(${sign}${Math.abs(pct).toFixed(2)} %)`
}

function ContractSessionsTable({ sessions }: { sessions: import('../types').SessionRow[] }) {
  const rows = withPrevClose(sessions)
  if (!rows.length) return <p className="muted">No sessions.</p>

  return (
    <div className="table-wrap weekday-table">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Open</th>
            <th>High</th>
            <th>Low</th>
            <th>Close</th>
            <th>Stock Close</th>
            <th>Volume</th>
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
                <td>{formatMoney(row.Open)}</td>
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
                  {delta != null && row['Prev Close'] != null && dir !== 'unknown' && (
                    <span className="close-delta">
                      {' '}
                      {formatClosePct(delta, row['Prev Close'])}
                    </span>
                  )}
                </td>
                <td>{formatMoney(row['Stock Close'])}</td>
                <td>{row.Volume?.toLocaleString() ?? '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <SessionCloseSummary rows={rows} />
    </div>
  )
}

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
      <p className="muted">
        OHLCV is for the <strong>option contract</strong>. <strong>Close</strong> is{' '}
        <span className="close-up-inline">green</span> when above the prior session&apos;s close,{' '}
        <span className="close-down-inline">red</span> when below.
      </p>
      <ContractSessionsTable sessions={contract.sessions} />
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
// VIX term structure → SPY Call / Put / No Trade signal
// ---------------------------------------------------------------------------
function vixSignalClass(signal: string): string {
  if (signal === 'BUY CALL') return 'signal-bullish vix-signal-call'
  if (signal === 'BUY PUT') return 'signal-bearish vix-signal-put'
  return 'signal-unknown vix-signal-none'
}

function vixHeroClass(signal: string): string {
  if (signal === 'BUY CALL') return 'vix-signal-hero vix-hero-call'
  if (signal === 'BUY PUT') return 'vix-signal-hero vix-hero-put'
  return 'vix-signal-hero vix-hero-none'
}

function trendLabelClass(trend: string): string {
  if (trend === 'Bullish') return 'close-up-inline'
  if (trend === 'Bearish') return 'close-down-inline'
  return 'session-row-cache-inline'
}

function stressLabelClass(stress: string): string {
  if (stress === 'EXTREME_HIGH') return 'close-down-inline'
  if (stress === 'EXTREME_LOW') return 'close-up-inline'
  return 'session-row-cache-inline'
}

function biasClass(bias: string): string {
  if (bias === 'Call') return 'close-up-inline'
  if (bias === 'Put') return 'close-down-inline'
  return 'session-row-cache-inline'
}

function VixSignalHelpPopup({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  if (!open) return null

  return (
    <div className="help-modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="help-modal vix-help-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-labelledby="vix-help-title"
        aria-modal="true"
      >
        <div className="help-modal-header">
          <h4 id="vix-help-title">When does it say CALL, PUT, or NO TRADE?</h4>
          <button type="button" className="help-modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="help-modal-body">
          <p>The computer only picks a trade when all three checks fit one of these rows:</p>
          <table className="help-table">
            <thead>
              <tr>
                <th>Mood of VIX</th>
                <th>Fear level</th>
                <th>SPY direction</th>
                <th>Answer</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Calm (Contango)</td>
                <td>Normal</td>
                <td>Up (Bullish)</td>
                <td><span className="vix-highlight-call">BUY CALL</span></td>
              </tr>
              <tr>
                <td>Calm (Contango)</td>
                <td>Normal</td>
                <td>Down (Bearish)</td>
                <td><span className="vix-highlight-put">BUY PUT</span></td>
              </tr>
              <tr>
                <td>Scared (Backwardation)</td>
                <td>Very high fear</td>
                <td>Up (Bullish)</td>
                <td><span className="vix-highlight-call">BUY CALL (bounce)</span></td>
              </tr>
              <tr>
                <td>Scared (Backwardation)</td>
                <td>Very high fear</td>
                <td>Down (Bearish)</td>
                <td><span className="vix-highlight-none">NO TRADE (too wild)</span></td>
              </tr>
              <tr>
                <td>Any</td>
                <td>Very low fear</td>
                <td>Down (Bearish)</td>
                <td><span className="vix-highlight-put">BUY PUT</span></td>
              </tr>
              <tr>
                <td>Anything else</td>
                <td>—</td>
                <td>Not clear</td>
                <td><span className="vix-highlight-none">NO TRADE</span></td>
              </tr>
            </tbody>
          </table>
          <p className="muted">
            Example: SPY trend can be <strong>Bullish</strong> but you still get{' '}
            <strong>NO TRADE</strong> if fear is <strong>very low</strong> (complacency) — that
            combo is not in the table above.
          </p>
        </div>
        <div className="help-modal-footer">
          <button type="button" className="btn primary" onClick={onClose}>
            Got it
          </button>
        </div>
      </div>
    </div>
  )
}

function VixSignalHelpNotes() {
  return (
    <div className="vix-help-notes">
      <h4>Notes — how to read this (simple version)</h4>
      <ul>
        <li>
          <strong>VIX price today</strong> is shown at the top after you run the signal. Rough
          guide: <span className="close-up-inline">under ~15</span> = calm (SPY often steady),{' '}
          <span className="close-down-inline">over ~25</span> = scared (SPY often jumpy or down).
        </li>
        <li>
          <strong>SPY</strong> is like a big basket of US stocks. When its trend is{' '}
          <span className="close-up-inline">Bullish</span>, price has been going <em>up</em> lately.
          <span className="close-down-inline"> Bearish</span> means the opposite.
        </li>
        <li>
          <strong>VIX</strong> is the &quot;fear meter.&quot; High VIX = people are nervous. Low VIX
          = people are relaxed — sometimes <em>too</em> relaxed.
        </li>
        <li>
          <span className="vix-highlight-call">BUY CALL</span> = green light to look for SPY going{' '}
          <em>up</em>. <span className="vix-highlight-put">BUY PUT</span> = red light for SPY going{' '}
          <em>down</em>. <span className="vix-highlight-none">NO TRADE</span> = wait.
        </li>
        <li>
          There are <strong>three checks</strong>: (1) VIX term structure — calm vs scared, (2) VIX
          stress — fear very high, very low, or normal, (3) SPY trend — up, down, or unclear.
        </li>
        <li>
          <strong>Why &quot;Bullish&quot; but NO TRADE?</strong> Trend is only one check. Example:
          SPY looks strong, but VIX can be <strong>extremely low</strong> (complacency). The rules
          won&apos;t say BUY CALL until fear is &quot;normal,&quot; and won&apos;t say BUY PUT until
          SPY turns bearish.
        </li>
        <li>
          <strong>Confidence %</strong> is like a grade: more checks agreeing = higher score. This
          is a rules-based hint, not a promise — always ask an adult before real money.
        </li>
      </ul>
    </div>
  )
}

export function VixSpySignalTab() {
  const [live, setLive] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [data, setData] = useState<VixSpySignalResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const run = () => {
    setLoading(true)
    setError(null)
    api
      .vixSpySignal(live)
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (!helpOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setHelpOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [helpOpen])

  return (
    <div>
      <h3>VIX → SPY Call / Put Signal</h3>
      <p className="muted">
        Three-layer rules engine: <strong>VIX term structure</strong> (VIX / VIX3M),{' '}
        <strong>VIX z-score stress</strong>, and <strong>SPY trend</strong> (VWAP, EMA9/20, RSI).
        Outputs <strong>BUY CALL</strong>, <strong>BUY PUT</strong>, or <strong>NO TRADE</strong>.
        Thresholds are tunable starting points for backtesting.
      </p>

      <DataModeBanner live={live} />
      <div className="form-row">
        <label className="checkbox">
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
          Fetch live data
        </label>
        <button type="button" className="btn primary" onClick={run} disabled={loading}>
          {loading ? 'Computing…' : 'Run signal'}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {data && (
        <>
          <div className={vixHeroClass(data.signal)}>
            <span className={`signal-pill vix-signal-pill ${vixSignalClass(data.signal)}`}>
              {data.signal}
            </span>
            <span className="vix-confidence muted">
              Confidence: <strong>{data.confidence_pct}%</strong> ({data.confidence_label})
            </span>
            <p className="vix-summary">{data.summary}</p>
            <p className="muted vix-scores">
              Regime: <strong>{data.regime}</strong> · Stress:{' '}
              <span className={stressLabelClass(data.stress)}>{data.stress}</span> · Trend:{' '}
              <span className={trendLabelClass(data.trend)}>{data.trend}</span>
              {data.data_source ? ` · ${data.data_source}` : ''}
            </p>
            {data.signal === 'NO TRADE' && data.context_note && (
              <p className="banner info vix-context-note">{data.context_note}</p>
            )}
          </div>

          <div className="vix-spotlight">
            <div className="vix-spotlight-main">
              <h4>VIX today — fear meter</h4>
              <p className="vix-spotlight-price">{data.vix_detail.close.toFixed(2)}</p>
              <p className="muted">
                Level: <strong>{data.vix_detail.level}</strong>
                {data.vix_detail.change_1d_pct != null && (
                  <>
                    {' '}
                    · 1d{' '}
                    <span
                      className={
                        data.vix_detail.change_1d_pct >= 0
                          ? 'close-down-inline'
                          : 'close-up-inline'
                      }
                    >
                      {data.vix_detail.change_1d_pct >= 0 ? '+' : ''}
                      {data.vix_detail.change_1d_pct.toFixed(1)}%
                    </span>
                  </>
                )}
                {' '}
                · 20d avg {data.vix_detail.vs_20d_avg.toFixed(2)}
              </p>
              <p className="vix-level-note">{data.vix_detail.level_note}</p>
            </div>
            <div className="vix-spotlight-spy">
              <h4>What this VIX means for SPY</h4>
              <p>{data.vix_detail.spy_implication}</p>
              <p className="muted">
                SPY now: <strong>{formatMoney(data.spy_technicals.close)}</strong> · VIX3M{' '}
                {data.term_structure.vix3m_close.toFixed(2)} · ratio{' '}
                {data.term_structure.ratio.toFixed(3)} ({data.regime})
              </p>
            </div>
          </div>

          <div className="vix-metrics-grid">
            <div className="vix-metric-card">
              <h4>Term structure</h4>
              <p className="vix-metric-value">{data.term_structure.ratio.toFixed(3)}</p>
              <p className="muted">
                VIX {data.term_structure.vix_close.toFixed(2)} ÷ VIX3M{' '}
                {data.term_structure.vix3m_close.toFixed(2)}
              </p>
              <p className="muted">
                Regime: <strong>{data.regime}</strong> (threshold &gt;{' '}
                {data.term_structure.backwardation_threshold.toFixed(2)} = backwardation)
              </p>
            </div>
            <div className="vix-metric-card">
              <h4>VIX stress (z-score)</h4>
              <p className="vix-metric-value">
                <span className={stressLabelClass(data.stress)}>
                  {data.vix_stress.zscore >= 0 ? '+' : ''}
                  {data.vix_stress.zscore.toFixed(2)}
                </span>
              </p>
              <p className="muted">
                Level: <span className={stressLabelClass(data.stress)}>{data.stress}</span> ·{' '}
                {data.vix_stress.lookback_days}d μ={data.vix_stress.mean.toFixed(2)} σ=
                {data.vix_stress.std.toFixed(2)}
              </p>
              <p className="muted">
                High &gt; {data.vix_stress.extreme_high_threshold} · Low &lt;{' '}
                {data.vix_stress.extreme_low_threshold}
              </p>
            </div>
            <div className="vix-metric-card">
              <h4>SPY trend</h4>
              <p className="vix-metric-value">{formatMoney(data.spy_technicals.close)}</p>
              <p className="muted">
                Trend: <span className={trendLabelClass(data.trend)}>{data.trend}</span>
                {data.spy_technicals.rsi14 != null
                  ? ` · RSI ${data.spy_technicals.rsi14.toFixed(1)}`
                  : ''}
              </p>
              <p className="muted">
                VWAP {formatMoney(data.spy_technicals.vwap)} · EMA9{' '}
                {formatMoney(data.spy_technicals.ema9)} · EMA20{' '}
                {formatMoney(data.spy_technicals.ema20)}
              </p>
            </div>
          </div>

          {data.suggested_strike && (
            <div
              className={`vix-strike-box ${
                data.suggested_strike.option_type === 'Call'
                  ? 'vix-strike-call'
                  : 'vix-strike-put'
              }`}
            >
              <h4>
                Suggested strike —{' '}
                <span
                  className={
                    data.suggested_strike.option_type === 'Call'
                      ? 'vix-highlight-call'
                      : 'vix-highlight-put'
                  }
                >
                  BUY {data.suggested_strike.option_type.toUpperCase()}
                </span>
              </h4>
              <p>
                <strong>{data.suggested_strike.option_type}</strong> · example strike{' '}
                <strong>${data.suggested_strike.example_strike}</strong> (ATM ${data.suggested_strike.atm_strike})
                · delta band <strong>{data.suggested_strike.delta_band}</strong>
              </p>
              <p className="muted">{data.suggested_strike.notes}</p>
            </div>
          )}

          {data.reasons.length > 0 && (
            <div className="pivot-summary vix-reasons">
              <h4>Why this signal</h4>
              <ul>
                {data.reasons.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
          )}

          <h4>Layer alignment (confidence)</h4>
          <div className="table-wrap vix-checks-table">
            <table>
              <thead>
                <tr>
                  <th>Layer</th>
                  <th>Reading</th>
                  <th>Bias</th>
                  <th>Aligned</th>
                </tr>
              </thead>
              <tbody>
                {data.layers.map((row) => (
                  <tr key={row.Layer}>
                    <td>{row.Layer}</td>
                    <td>
                      {row.Reading === 'Bullish' || row.Reading === 'Bearish' ? (
                        <span className={trendLabelClass(row.Reading)}>{row.Reading}</span>
                      ) : row.Reading === 'EXTREME_HIGH' || row.Reading === 'EXTREME_LOW' ? (
                        <span className={stressLabelClass(row.Reading)}>{row.Reading}</span>
                      ) : (
                        row.Reading
                      )}
                    </td>
                    <td>
                      <span className={biasClass(row.Bias)}>{row.Bias}</span>
                    </td>
                    <td>
                      {row.Aligned ? (
                        <span className="vix-aligned-yes">✓ yes</span>
                      ) : (
                        <span className="vix-aligned-no">— no</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="muted vix-disclaimer">{data.disclaimer}</p>
          {data.thresholds && (
            <p className="muted vix-thresholds">
              Active thresholds: term ratio &gt; {data.thresholds.term_structure_backwardation} →
              backwardation · z high &gt; {data.thresholds.vix_zscore_extreme_high} · z low &lt;{' '}
              {data.thresholds.vix_zscore_extreme_low}
            </p>
          )}
        </>
      )}

      <VixSignalHelpNotes />
      <div className="pivot-help-footer">
        <button type="button" className="btn-sm pivot-help-btn" onClick={() => setHelpOpen(true)}>
          Help — When does it say CALL, PUT, or NO TRADE?
        </button>
      </div>
      <VixSignalHelpPopup open={helpOpen} onClose={() => setHelpOpen(false)} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Weekday sessions — last 20 Mon/Tue/Wed/Thu/Fri bars
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

function formatPctChange(delta: number, prevClose: number): string {
  const pct = (delta / prevClose) * 100
  const sign = pct >= 0 ? '+' : '−'
  return `(${sign}${Math.abs(pct).toFixed(2)})`
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

function sessionRowClassName(row: {
  'Is Current Session'?: boolean
  'Row Source'?: string
}): string {
  if (!row['Is Current Session']) return ''
  return row['Row Source'] === 'live' ? 'session-row-live' : 'session-row-cache'
}

function countSessionCloseColors(
  rows: { Close: number; 'Prev Close': number | null }[],
): { green: number; red: number; flat: number } {
  let green = 0
  let red = 0
  let flat = 0
  for (const row of rows) {
    const dir = closeDirection(row.Close, row['Prev Close'])
    if (dir === 'up') green += 1
    else if (dir === 'down') red += 1
    else if (dir === 'flat') flat += 1
  }
  return { green, red, flat }
}

function SessionCloseSummary({
  rows,
}: {
  rows: { Close: number; 'Prev Close': number | null }[]
}) {
  const { green, red } = countSessionCloseColors(rows)
  return (
    <div className="session-close-summary">
      <p>
        <span className="close-up-inline">Green</span> = {green}
      </p>
      <p>
        <span className="close-down-inline">Red</span> = {red}
      </p>
    </div>
  )
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
              <tr key={row.Date} className={sessionRowClassName(row)}>
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
      <SessionCloseSummary rows={rows} />
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
      .weekdaySessions(ticker, weekday, live, 20)
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  return (
    <div>
      <h3>Weekday Sessions — Prev Close, High, Low, Close</h3>
      <p className="muted">
        Pull the last <strong>20 sessions</strong> for a chosen weekday (Mon–Fri only).
        <strong> Prev Close</strong> is the prior trading day&apos;s close before each session.
        <strong> Close</strong> is <span className="close-up-inline">green</span> when above prev close,{' '}
        <span className="close-down-inline">red</span> when below.
        Today&apos;s session uses the <strong>live last price</strong> when fetched live;{' '}
        <span className="session-row-live-inline">blue row</span> = live,{' '}
        <span className="session-row-cache-inline">grey row</span> = cached snapshot.
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
          <CacheUpdatedBanner
            live={live}
            cacheUpdatedAt={data.cache_meta?.cache_updated_at}
          />
          <WeekdaySessionsTable rows={data.rows} />
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Last 20 days — consecutive trading sessions OHLC
// ---------------------------------------------------------------------------
function Last20DaysTable({
  rows,
}: {
  rows: import('../api').RecentSessionsResponse['rows']
}) {
  if (!rows.length) return <p className="muted">No sessions.</p>

  return (
    <div className="table-wrap weekday-table">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Weekday</th>
            <th>Open</th>
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
              <tr key={row.Date} className={sessionRowClassName(row)}>
                <td>{row.Date}</td>
                <td>{row.Weekday}</td>
                <td>{formatMoney(row.Open)}</td>
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
                  {delta != null && row['Prev Close'] != null && dir !== 'unknown' && (
                    <span className="close-delta">
                      {' '}
                      {formatPctChange(delta, row['Prev Close'])}
                    </span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <SessionCloseSummary rows={rows} />
    </div>
  )
}

export function Last20DaysTab() {
  const [ticker, setTicker] = useState('SPY')
  const [live, setLive] = useState(false)
  const [data, setData] = useState<import('../api').RecentSessionsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = () => {
    setLoading(true)
    setError(null)
    api
      .recentSessions(ticker, live, 20)
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  return (
    <div>
      <h3>Last 20 Days — Open, High, Low, Close</h3>
      <p className="muted">
        Pull the last <strong>20 trading sessions</strong> (Mon–Fri working days with a bar).
        <strong> Close</strong> is <span className="close-up-inline">green</span> when above the
        prior session&apos;s close, <span className="close-down-inline">red</span> when below, with
        percent change shown as <strong>(+0.10)</strong> or <strong>(−0.10)</strong>.
        Today&apos;s session uses the <strong>live last price</strong> when fetched live;{' '}
        <span className="session-row-live-inline">blue row</span> = live,{' '}
        <span className="session-row-cache-inline">grey row</span> = cached snapshot.
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

      {error && <p className="error">{error}</p>}

      {data && (
        <>
          <p className="muted">
            {data.ticker} · {data.sessions_returned} session(s) ·{' '}
            {data.data_source === 'live' ? 'live' : 'cache'}
          </p>
          <CacheUpdatedBanner
            live={live}
            cacheUpdatedAt={data.cache_meta?.cache_updated_at}
          />
          <Last20DaysTable rows={data.rows} />
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// SPX / floor-trader pivot levels
// ---------------------------------------------------------------------------
function pivotKindClass(kind: string): string {
  if (kind === 'resistance') return 'level-resistance'
  if (kind === 'pivot') return 'level-pivot'
  return 'level-support'
}

function PivotLevelsTable({ levels }: { levels: import('../api').PivotLevelRow[] }) {
  return (
    <div className="table-wrap pivot-table">
      <table>
        <thead>
          <tr>
            <th>Level</th>
            <th>Price</th>
            <th>Notes</th>
            <th>Today vs level</th>
          </tr>
        </thead>
        <tbody>
          {levels.map((row) => (
            <tr key={`${row.Label}-${row.Price}`} className={pivotKindClass(row.Kind)}>
              <td>{row.Label}</td>
              <td>{formatMoney(row.Price)}</td>
              <td className="muted-cell">{row.Notes}</td>
              <td>{row.Today ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PivotLevelsHelpPopup({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  if (!open) return null

  return (
    <div className="help-modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="help-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-labelledby="pivot-help-title"
        aria-modal="true"
      >
        <div className="help-modal-header">
          <h4 id="pivot-help-title">Floor trader pivots — PP, R1–R3, S1–S3</h4>
          <button type="button" className="help-modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="help-modal-body">
          <p>
            All levels come from the <strong>prior session</strong> high (H), low (L), and close
            (C). They are the same formulas many &quot;key levels&quot; newsletters use.
          </p>
          <p className="help-formula">
            <strong>PP (Pivot)</strong> = (H + L + C) ÷ 3 — the center line for the next session.
          </p>
          <table className="help-table">
            <thead>
              <tr>
                <th>Level</th>
                <th>Formula</th>
                <th>Role</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>R1</td>
                <td>2×PP − L</td>
                <td>First resistance above pivot</td>
              </tr>
              <tr>
                <td>R2</td>
                <td>PP + (H − L)</td>
                <td>Second resistance — common rejection zone</td>
              </tr>
              <tr>
                <td>R3</td>
                <td>H + 2×(PP − L)</td>
                <td>Third resistance — extension if R2 breaks</td>
              </tr>
              <tr>
                <td>S1</td>
                <td>2×PP − H</td>
                <td>First support below pivot</td>
              </tr>
              <tr>
                <td>S2</td>
                <td>PP − (H − L)</td>
                <td>Second support</td>
              </tr>
              <tr>
                <td>S3</td>
                <td>L − 2×(H − PP)</td>
                <td>Third support — deep extension</td>
              </tr>
            </tbody>
          </table>
          <p className="muted">
            The tab also shows <strong>Prior High</strong>, <strong>Prior Close</strong>, and{' '}
            <strong>Prior Low</strong> — yesterday&apos;s actual prices on the same ladder, not
            separate formulas.
          </p>
          <p className="muted">
            <strong>How to read it:</strong> rallies often stall at R1/R2; losing PP can accelerate
            selling toward S1/S2/S3. Prior high and prior close often matter as much as the
            calculated levels. The <strong>Today vs level</strong> column shows whether today&apos;s
            session touched each price — supports below today&apos;s low show{' '}
            <strong>not reached</strong> until price drops there.
          </p>
        </div>
        <div className="help-modal-footer">
          <button type="button" className="btn primary" onClick={onClose}>
            Got it
          </button>
        </div>
      </div>
    </div>
  )
}

export function SpxPivotsTab() {
  const [ticker, setTicker] = useState('^GSPC')
  const [live, setLive] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [data, setData] = useState<import('../api').PivotLevelsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = () => {
    setLoading(true)
    setError(null)
    api
      .pivotLevels(ticker, live)
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (!helpOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setHelpOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [helpOpen])

  return (
    <div>
      <h3>SPX Pivots — Floor Trader Key Levels</h3>
      <p className="muted">
        Classic floor-trader pivots from the <strong>prior session</strong> high, low, and close:{' '}
        <strong>PP = (H + L + C) / 3</strong>, then R1–R3 above and S1–S3 below. Prior day H/L/C
        are listed too — same math newsletters use. The <strong>Today vs level</strong> column
        describes how today&apos;s range interacted with each price (blank means no meaningful
        touch). Default is <strong>^GSPC</strong> (S&P 500 index); try <strong>SPY</strong> to
        match your sheet.
      </p>

      <DataModeBanner live={live} />

      <div className="form-row">
        <label>
          Symbol
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            placeholder="^GSPC"
          />
        </label>
        <div className="quick-tickers">
          <button type="button" className="btn-sm" onClick={() => setTicker('^GSPC')}>
            SPX
          </button>
          <button type="button" className="btn-sm" onClick={() => setTicker('SPY')}>
            SPY
          </button>
        </div>
        <label className="checkbox">
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
          Fetch live data
        </label>
        <button type="button" className="btn primary" onClick={load} disabled={loading}>
          {loading ? 'Loading…' : 'Compute levels'}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {data && (
        <>
          <p className="muted">
            {data.display_name} ({data.ticker}) · {data.data_source === 'live' ? 'live' : 'cache'}
            {data.session_date ? ` · session ${data.session_date}` : ''}
          </p>
          <CacheUpdatedBanner live={live} cacheUpdatedAt={data.cache_meta?.cache_updated_at} />

          <div className="pivot-prior-box">
            <h4>Prior session — {data.prior_session.Weekday} {data.prior_session.Date}</h4>
            <p>
              High {formatMoney(data.prior_session.High)} · Low{' '}
              {formatMoney(data.prior_session.Low)} · Close{' '}
              {formatMoney(data.prior_session.Close)}
            </p>
            <p className="muted formula">{data.formula}</p>
          </div>

          {data.today && (
            <div
              className={`pivot-today-box ${
                data.today['Row Source'] === 'live' ? 'session-row-live' : 'session-row-cache'
              }`}
            >
              <h4>
                Today — {data.today.Weekday} {data.today.Date}
                {data.today['Row Source'] === 'live' ? ' (live)' : ' (cache)'}
              </h4>
              <p>
                Open {formatMoney(data.today.Open)} · High {formatMoney(data.today.High)} · Low{' '}
                {formatMoney(data.today.Low)} · Close {formatMoney(data.today.Close)}
              </p>
            </div>
          )}

          <h4 className="pivot-section-title">Key levels (high → low)</h4>
          <PivotLevelsTable levels={data.levels} />

          {(data.summary_lines.length > 0 || data.next_resistance) && (
            <div className="pivot-summary">
              <h4>Today vs levels</h4>
              {data.next_resistance && (
                <p className="pivot-next-resistance">
                  <strong>Next resistance to watch:</strong>{' '}
                  {data.next_resistance.Label} at {formatMoney(data.next_resistance.Price)}
                  {' '}
                  ({formatMoney(data.next_resistance.Distance)} /{' '}
                  {data.next_resistance['Distance Pct'] >= 0 ? '+' : ''}
                  {data.next_resistance['Distance Pct'].toFixed(2)}% above close)
                  {data.next_resistance.Kind === 'pivot' && (
                    <span className="muted"> — pivot acts as resistance from here</span>
                  )}
                </p>
              )}
              <ul>
                {data.summary_lines
                  .filter(
                    (line) =>
                      !line.startsWith('Next resistance to watch:') &&
                      !line.startsWith('Next resistance ') &&
                      !line.startsWith('Next pivot '),
                  )
                  .map((line) => (
                    <li key={line}>{line}</li>
                  ))}
              </ul>
            </div>
          )}
        </>
      )}

      <div className="pivot-help-footer">
        <button type="button" className="btn-sm pivot-help-btn" onClick={() => setHelpOpen(true)}>
          Help — What are PP, R1–R3, and S1–S3?
        </button>
      </div>
      <PivotLevelsHelpPopup open={helpOpen} onClose={() => setHelpOpen(false)} />
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
          <ContractSessionsTable
            sessions={(detail.sessions as import('../types').SessionRow[]) ?? []}
          />
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
