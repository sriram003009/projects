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

/** e.g. Friday, July 10, 2026 at 10:10 AM Central */
export function formatCentralDateTime(iso: string): string {
  const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(iso) ? iso : `${iso}Z`
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return iso

  const datePart = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Chicago',
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  }).format(date)

  const timePart = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Chicago',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }).format(date)

  return `${datePart} at ${timePart} Central`
}

interface CacheUpdatedProps {
  live: boolean
  cacheUpdatedAt?: string | null
}

export function CacheUpdatedBanner({ live, cacheUpdatedAt }: CacheUpdatedProps) {
  if (live || !cacheUpdatedAt) return null
  return (
    <p className="cache-updated muted">
      Last updated: <strong>{formatCentralDateTime(cacheUpdatedAt)}</strong>
    </p>
  )
}
