import { describe, expect, it } from 'vitest';
import { KEEP_ALIVE_MS, SERVER_IDLE_MS, healthQueryOptions } from './keepAlive';

describe('keep-alive', () => {
  it('keeps pinging while the tab is hidden, or reading another tab would stop the app', () => {
    expect(healthQueryOptions.refetchIntervalInBackground).toBe(true);
  });

  it('pings often enough that a throttled background tab still lands inside the limit', () => {
    // A hidden tab's timers may only run once a minute: the worst gap is the interval
    // rounded up to the next minute, and that must leave room before the server gives up.
    const worstGap = Math.ceil(KEEP_ALIVE_MS / 60_000) * 60_000;
    expect(worstGap).toBeLessThanOrEqual(SERVER_IDLE_MS / 2);
    expect(healthQueryOptions.refetchInterval).toBe(KEEP_ALIVE_MS);
  });

  it('checks the app is still there when the tab is looked at again', () => {
    expect(healthQueryOptions.refetchOnWindowFocus).toBe(true);
  });

  it('does not call one failed ping a stopped app', () => {
    expect(healthQueryOptions.retry).toBeGreaterThanOrEqual(2);
  });
});
