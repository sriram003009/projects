import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, type CacheSummary } from './api'
import { DataModeBanner } from './components/DataModeBanner'
import { Sidebar } from './components/Sidebar'
import {
  CachedDataTab,
  CallsPutsTab,
  CheckSmaTab,
  ForecastsTab,
  QuickSummaryTab,
  RecentActivityTab,
  TrackBestTab,
  WhatIfTab,
  StocksOnWatchlistTab,
  WeekdaySessionsTab,
} from './components/TabPanels'
import type { ContractForm, ContractLookup } from './types'
import './App.css'

const TABS = [
  { id: 'recent', label: 'Recent Activity', row: 1, color: 'tab-blue' },
  { id: 'forecast', label: '5-Day Forecasts', row: 1, color: 'tab-orange' },
  { id: 'whatif', label: 'What-If Scenario', row: 1, color: 'tab-purple' },
  { id: 'movers', label: 'Track the Best', row: 1, color: 'tab-green' },
  { id: 'weekday', label: 'Weekday Sessions', row: 2, color: 'tab-cyan' },
  { id: 'watchlist', label: 'Stocks on Watchlist', row: 2, color: 'tab-amber' },
  { id: 'summary', label: 'Quick Summary', row: 2, color: 'tab-teal' },
  { id: 'sma', label: 'Check SMA', row: 2, color: 'tab-indigo' },
  { id: 'pcr', label: 'Calls vs Puts', row: 2, color: 'tab-rose' },
  { id: 'cached', label: 'Cached Data', row: 2, color: 'tab-stone' },
] as const

type TabId = (typeof TABS)[number]['id']

const DEFAULT_FORM: ContractForm = {
  ticker: 'AAPL',
  optionType: 'Call',
  expirationMmdd: '',
  strike: 150,
  liveFetch: false,
}

function App() {
  const [form, setForm] = useState<ContractForm>(DEFAULT_FORM)
  const [activeTab, setActiveTab] = useState<TabId>('movers')
  const [contract, setContract] = useState<ContractLookup | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cacheSummary, setCacheSummary] = useState<CacheSummary | null>(null)

  const [sourceNotice, setSourceNotice] = useState<string | null>(null)
  const prevLiveFetch = useRef(form.liveFetch)

  useEffect(() => {
    api.cacheSummary().then(setCacheSummary).catch(() => {})
  }, [])

  useEffect(() => {
    if (prevLiveFetch.current !== form.liveFetch) {
      setContract(null)
      setError(null)
      setSourceNotice(
        form.liveFetch
          ? 'Live fetch enabled — click Fetch Data to download from Yahoo Finance.'
          : 'Cache-only mode — click Fetch Data to load from disk (no network).',
      )
    }
    prevLiveFetch.current = form.liveFetch
  }, [form.liveFetch])

  const fetchContract = useCallback(async () => {
    setLoading(true)
    setError(null)
    setSourceNotice(null)
    try {
      const data = (await api.lookupContract(form)) as ContractLookup
      setContract(data)
      setActiveTab('recent')
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'Fetch failed'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }, [form])

  const loadFromCache = async (
    ticker: string,
    optionType: 'Call' | 'Put',
    exp: string,
    strike: number,
  ) => {
    const newForm = { ...form, ticker, optionType, expirationMmdd: exp, strike, liveFetch: false }
    setForm(newForm)
    setLoading(true)
    setError(null)
    setSourceNotice(null)
    try {
      const data = (await api.lookupContract(newForm)) as ContractLookup
      setContract(data)
      setActiveTab('recent')
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'Fetch failed'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  const clearCache = async () => {
    if (!window.confirm('Clear ALL cached data? This cannot be undone.')) return
    await api.clearCache(true)
    setCacheSummary(await api.cacheSummary())
  }

  return (
    <div className="app">
      <Sidebar
        form={form}
        onChange={setForm}
        onSubmit={fetchContract}
        loading={loading}
        cacheSummary={cacheSummary}
        onClearCache={clearCache}
      />

      <main className="main">
        <header>
          <h1>Options Lookup</h1>
          <p className="lead">
            Stock options dashboard — contract history, 5-day forecasts, what-if Greeks, watchlist
            scanners, SMA tools, put/call dominance, and cached contracts. Data via Yahoo Finance.
          </p>
          <p className="caption">
            <strong>Row 1 — Contract:</strong> Recent Activity · 5-Day Forecasts · What-If · Track the Best
            <br />
            <strong>Row 2 — Scanners:</strong> Weekday Sessions · Stocks on Watchlist · Quick Summary · Check SMA · Calls vs Puts · Cached Data
          </p>
        </header>

        <DataModeBanner live={form.liveFetch} label="Sidebar data source" />

        {sourceNotice && <div className="banner info">{sourceNotice}</div>}
        {error && <div className="banner error">{error}</div>}

        <div className="tab-grid">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={`tab-btn ${tab.color} ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <section className="tab-panel">
          {activeTab === 'recent' && <RecentActivityTab contract={contract} />}
          {activeTab === 'forecast' && <ForecastsTab form={form} contract={contract} />}
          {activeTab === 'whatif' && <WhatIfTab form={form} contract={contract} />}
          {activeTab === 'movers' && <TrackBestTab />}
          {activeTab === 'weekday' && <WeekdaySessionsTab />}
          {activeTab === 'watchlist' && <StocksOnWatchlistTab />}
          {activeTab === 'summary' && <QuickSummaryTab />}
          {activeTab === 'sma' && <CheckSmaTab />}
          {activeTab === 'pcr' && <CallsPutsTab />}
          {activeTab === 'cached' && <CachedDataTab onLoadContract={loadFromCache} />}
        </section>
      </main>
    </div>
  )
}

export default App
