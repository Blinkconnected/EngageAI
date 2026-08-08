import { useEffect, useState } from 'react'

/** A clock that re-renders its caller, for durations that must stay true.
 *
 * "Waiting 4m" rendered once and left alone still says 4m twenty minutes
 * later. On an operations screen that is not a stale label, it is a
 * wrong one — somebody decides what to pick up next by reading it.
 *
 * Ticking every 30 seconds rather than every second: nothing here is
 * measured in seconds, and a per-second re-render of the conversation
 * header would be sixty wasted renders a minute for a figure that
 * changes twice.
 *
 * @param intervalMs - how often to tick. Default 30s.
 * @returns epoch milliseconds, changing on each tick.
 */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs])

  return now
}
