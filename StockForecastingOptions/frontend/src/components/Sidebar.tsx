import type { ContractForm } from '../types'

interface Props {
  form: ContractForm
  onChange: (form: ContractForm) => void
  onSubmit: () => void
  loading: boolean
  cacheSummary: { num_files?: number; total_kb?: number } | null
  onClearCache: () => void
}

export function Sidebar({
  form,
  onChange,
  onSubmit,
  loading,
  cacheSummary,
  onClearCache,
}: Props) {
  return (
    <aside className="sidebar">
      <h2>Contract Inputs</h2>
      <label>
        Stock Ticker
        <input
          value={form.ticker}
          onChange={(e) => onChange({ ...form, ticker: e.target.value.toUpperCase() })}
          placeholder="AAPL"
        />
      </label>
      <fieldset>
        <legend>Option Type</legend>
        {(['Call', 'Put'] as const).map((t) => (
          <label key={t} className="radio">
            <input
              type="radio"
              checked={form.optionType === t}
              onChange={() => onChange({ ...form, optionType: t })}
            />
            {t}
          </label>
        ))}
      </fieldset>
      <label>
        Expiration (MM/DD)
        <input
          value={form.expirationMmdd}
          onChange={(e) => onChange({ ...form, expirationMmdd: e.target.value })}
          placeholder="06/20"
        />
      </label>
      <label>
        Strike Price
        <input
          type="number"
          step="0.5"
          min={0}
          value={form.strike}
          onChange={(e) => onChange({ ...form, strike: parseFloat(e.target.value) || 0 })}
        />
      </label>
      <button type="button" className="btn primary" onClick={onSubmit} disabled={loading}>
        {loading ? 'Fetching…' : 'Fetch Data'}
      </button>

      <hr />
      <h3>Data source</h3>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={form.liveFetch}
          onChange={(e) => onChange({ ...form, liveFetch: e.target.checked })}
        />
        Fetch live data
      </label>
      <p className="hint">
        <strong>Unchecked (default):</strong> read from disk cache only — no Yahoo Finance
        calls. If nothing is cached yet, you will see &quot;No cached data — enable Fetch live
        data&quot;.
      </p>
      <p className="hint">
        <strong>Checked:</strong> download or refresh from Yahoo Finance, then save to cache.
      </p>

      {cacheSummary && (
        <p className="hint">
          Cache: {cacheSummary.num_files ?? 0} files · {cacheSummary.total_kb ?? 0} KB
        </p>
      )}
      <button type="button" className="btn danger" onClick={onClearCache}>
        Clear all cached data
      </button>
    </aside>
  )
}
