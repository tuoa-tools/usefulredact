/** The health ping, which is also how the app knows this tab is still open: after two
 *  minutes without one, and with nothing being checked, it stops and deletes the session
 *  (IDLE_SECONDS in app/main.py). The settings live here, with a test, because each one
 *  guards against a way of getting that wrong. */

/** The server's limit, in ms. Keep in step with IDLE_SECONDS in app/main.py. */
export const SERVER_IDLE_MS = 120_000;

/** How often to ping. A browser lets a tab that has been hidden for a while run its timers
 *  only once a minute, so a ping due every 30 s lands at most 60 s after the last one and
 *  stays well inside the limit. At 60 s, two could land almost two minutes apart. */
export const KEEP_ALIVE_MS = 30_000;

// A ping that fails is not a stopped app: a request can be lost, and a machine waking from
// sleep drops whatever was in flight. Only after these does the app say it has gone. They
// are spelled out rather than left to the default, because what depends on them is a screen
// saying nothing here can be relied on.
export const HEALTH_RETRIES = 2;
export const HEALTH_RETRY_MS = 1_000;

export const healthQueryOptions = {
  refetchInterval: KEEP_ALIVE_MS,
  // Keep pinging while the tab is hidden. Without this the pings stop the moment another
  // tab is in front, and two minutes of reading something else ends the app and deletes
  // what it found.
  refetchIntervalInBackground: true,
  // Coming back to the tab is when a person is about to read a verdict, so that is when
  // to find out whether the app behind it is still there.
  refetchOnWindowFocus: true,
  retry: HEALTH_RETRIES,
  retryDelay: HEALTH_RETRY_MS,
} as const;
