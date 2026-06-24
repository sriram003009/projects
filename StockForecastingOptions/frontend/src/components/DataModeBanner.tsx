interface Props {
  live: boolean
  label?: string
}

/** Shows whether the UI is in cache-only or live-fetch mode. */
export function DataModeBanner({ live, label = 'Data mode' }: Props) {
  return (
    <p className={`data-mode ${live ? 'live' : 'cache'}`}>
      {label}:{' '}
      {live ? (
        <strong>Live fetch</strong>
      ) : (
        <strong>Cache only</strong>
      )}
      {!live && (
        <span className="data-mode-note">
          {' '}
          — uses disk cache only; no network unless you check Fetch live data.
        </span>
      )}
    </p>
  )
}

interface HintProps {
  message: string | null | undefined
}

export function CacheHintBanner({ message }: HintProps) {
  if (!message) return null
  return <div className="banner warn">{message}</div>
}
