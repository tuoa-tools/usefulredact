import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import {
  UNATTENDED_MS,
  WARNING_MS,
  minutesAndSeconds,
  unattendedState,
  useUnattended,
} from './unattended';

const MIN = 60_000;

describe('unattendedState', () => {
  it('never runs while there is nothing to protect, or while documents are being checked', () => {
    expect(unattendedState(10 * UNATTENDED_MS, 0, false)).toEqual({
      expired: false,
      warning: false,
      secondsLeft: 0,
    });
  });

  it('asks two minutes before, and gives up at thirty', () => {
    expect(unattendedState(27 * MIN, 0, true).warning).toBe(false);
    expect(unattendedState(28.5 * MIN, 0, true)).toEqual({
      expired: false,
      warning: true,
      secondsLeft: 90,
    });
    expect(unattendedState(30 * MIN, 0, true).expired).toBe(true);
    expect(UNATTENDED_MS - WARNING_MS).toBe(28 * MIN);
  });

  it('counts an hour with the lid closed as an hour away', () => {
    expect(unattendedState(Date.UTC(2026, 0, 1, 13), Date.UTC(2026, 0, 1, 12), true).expired).toBe(
      true
    );
  });

  it('shows the time left as minutes and seconds', () => {
    expect(minutesAndSeconds(90)).toBe('1:30');
    expect(minutesAndSeconds(5)).toBe('0:05');
  });
});

describe('useUnattended', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T12:00:00Z'));
  });
  afterEach(() => vi.useRealTimers());

  it('warns, then closes the session once, when nobody touches the page', () => {
    const onExpire = vi.fn();
    const { result } = renderHook(() => useUnattended(true, onExpire));
    act(() => vi.advanceTimersByTime(27 * MIN));
    expect(result.current.warning).toBe(false);
    act(() => vi.advanceTimersByTime(2 * MIN));
    expect(result.current.warning).toBe(true);
    expect(onExpire).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(2 * MIN));
    expect(onExpire).toHaveBeenCalledTimes(1);
  });

  it('starts again whenever the page is used, or "still here" is pressed', () => {
    const onExpire = vi.fn();
    const { result } = renderHook(() => useUnattended(true, onExpire));
    act(() => vi.advanceTimersByTime(29 * MIN));
    expect(result.current.warning).toBe(true);
    act(() => {
      window.dispatchEvent(new Event('keydown'));
      vi.advanceTimersByTime(1000);
    });
    expect(result.current.warning).toBe(false);
    act(() => vi.advanceTimersByTime(29 * MIN));
    act(() => result.current.stay());
    expect(result.current.warning).toBe(false);
    act(() => vi.advanceTimersByTime(27 * MIN));
    expect(onExpire).not.toHaveBeenCalled();
  });

  it('does not run with no documents loaded, and starts when there are some', () => {
    const onExpire = vi.fn();
    const { rerender } = renderHook(({ holding }) => useUnattended(holding, onExpire), {
      initialProps: { holding: false },
    });
    act(() => vi.advanceTimersByTime(3 * UNATTENDED_MS));
    expect(onExpire).not.toHaveBeenCalled();
    rerender({ holding: true });
    act(() => vi.advanceTimersByTime(29 * MIN)); // from now, not from when the page opened
    expect(onExpire).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(2 * MIN));
    expect(onExpire).toHaveBeenCalledTimes(1);
  });
});
