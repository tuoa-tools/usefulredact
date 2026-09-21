/** Left alone with documents loaded, the app closes the session by itself: what it found
 *  is personal information on a screen nobody is watching, and copies of the documents on
 *  disk. UsefulText, which shares the rest of this machinery, does the opposite on purpose
 *  and waits for its person to come back; here the documents are the sensitive thing.
 *
 *  The clock runs only while there is something to protect and nothing in progress: a
 *  session holding documents, none of them still being checked. It is the wall clock, so
 *  an hour with the lid closed counts as an hour away. */

import { useEffect, useRef, useState } from 'react';

/** How long the session may be left untouched before it is closed. */
export const UNATTENDED_MS = 30 * 60_000;
/** How long before that the page asks whether anyone is still there. */
export const WARNING_MS = 2 * 60_000;

export interface UnattendedState {
  /** Left too long: close the session. */
  expired: boolean;
  /** Close to it: ask. */
  warning: boolean;
  secondsLeft: number;
}

const ATTENDED: UnattendedState = { expired: false, warning: false, secondsLeft: 0 };

export function unattendedState(
  now: number,
  lastActivity: number,
  holding: boolean
): UnattendedState {
  if (!holding) return ATTENDED;
  const left = UNATTENDED_MS - (now - lastActivity);
  if (left <= 0) return { expired: true, warning: false, secondsLeft: 0 };
  if (left <= WARNING_MS)
    return { expired: false, warning: true, secondsLeft: Math.ceil(left / 1000) };
  return ATTENDED;
}

/** Anything a person does to the page. Reading is scrolling and pointing, so those count. */
const ACTIVITY = ['pointerdown', 'pointermove', 'keydown', 'wheel', 'touchstart'] as const;

/** Watches for the session being left alone. `holding` is whether there is anything to
 *  protect; `onExpire` runs once when the time is up. `stay` is the "I'm still here" button,
 *  though any activity does the same. */
export function useUnattended(holding: boolean, onExpire: () => void) {
  const lastActivity = useRef(0); // set when the clock starts, below: never read before
  const expire = useRef(onExpire);
  const fired = useRef(false);
  const [state, setState] = useState<UnattendedState>(ATTENDED);

  useEffect(() => {
    expire.current = onExpire;
  }, [onExpire]);

  useEffect(() => {
    // The clock starts when there is first something to protect, not when the page opened.
    lastActivity.current = Date.now();
    fired.current = false;
    if (!holding) return;

    const touch = () => {
      lastActivity.current = Date.now();
    };
    const tick = () => {
      const next = unattendedState(Date.now(), lastActivity.current, true);
      setState((prev) =>
        prev.expired === next.expired &&
        prev.warning === next.warning &&
        prev.secondsLeft === next.secondsLeft
          ? prev
          : next
      );
      if (next.expired && !fired.current) {
        fired.current = true;
        expire.current();
      }
    };
    for (const name of ACTIVITY) window.addEventListener(name, touch, { passive: true });
    const timer = window.setInterval(tick, 1000);
    return () => {
      for (const name of ACTIVITY) window.removeEventListener(name, touch);
      window.clearInterval(timer);
      setState(ATTENDED);
    };
  }, [holding]);

  return {
    ...state,
    stay: () => {
      lastActivity.current = Date.now();
      setState(ATTENDED);
    },
  };
}

export function minutesAndSeconds(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
