interface Props {
  rows: Record<string, unknown>[]
  className?: string
}

export function DataTable({ rows, className = '' }: Props) {
  if (!rows.length) return <p className="muted">No data.</p>
  const cols = Object.keys(rows[0])

  return (
    <div className={`table-wrap ${className}`}>
      <table>
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td key={c}>{formatCell(row[c])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function formatCell(v: unknown): string {
  if (v == null) return '—'
  if (typeof v === 'number') {
    if (Math.abs(v) >= 1000 && Number.isInteger(v)) return v.toLocaleString()
    return Number.isInteger(v) ? String(v) : v.toFixed(2)
  }
  return String(v)
}
