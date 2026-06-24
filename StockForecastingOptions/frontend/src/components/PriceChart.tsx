import Plot from 'react-plotly.js'
import type { SessionRow } from '../types'

interface Props {
  sessions: SessionRow[]
  title?: string
}

export function PriceChart({ sessions, title = 'Price Movement' }: Props) {
  if (!sessions.length) return null

  const dates = sessions.map((r) => r.Date)

  return (
    <Plot
      data={[
        {
          type: 'candlestick',
          x: dates,
          open: sessions.map((r) => r.Open),
          high: sessions.map((r) => r.High),
          low: sessions.map((r) => r.Low),
          close: sessions.map((r) => r.Close),
          name: 'OHLC',
          increasing: { line: { color: '#26a69a' } },
          decreasing: { line: { color: '#ef5350' } },
        },
        {
          type: 'scatter',
          mode: 'lines+markers',
          x: dates,
          y: sessions.map((r) => r.Close),
          name: 'Close',
          line: { color: '#42a5f5', width: 2 },
          yaxis: 'y',
        },
        {
          type: 'bar',
          x: dates,
          y: sessions.map((r) => r.Volume),
          name: 'Volume',
          marker: { color: '#90a4ae' },
          yaxis: 'y2',
        },
      ]}
      layout={{
        title,
        height: 520,
        grid: { rows: 2, columns: 1, pattern: 'independent', roworder: 'top to bottom' },
        xaxis: { domain: [0, 1], anchor: 'y', rangeslider: { visible: false } },
        yaxis: { domain: [0.28, 1], title: 'Price (USD)' },
        xaxis2: { domain: [0, 1], anchor: 'y2' },
        yaxis2: { domain: [0, 0.22], title: 'Volume' },
        hovermode: 'x unified',
        margin: { l: 50, r: 20, t: 40, b: 40 },
        legend: { orientation: 'h', y: 1.08 },
      }}
      config={{ responsive: true, displayModeBar: true }}
      style={{ width: '100%' }}
    />
  )
}
