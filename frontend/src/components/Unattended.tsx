import { minutesAndSeconds, UNATTENDED_MS } from '../lib/unattended';

const MINUTES = Math.round(UNATTENDED_MS / 60_000);

/** Asks before the session is closed for having been left alone. */
export function StillThere({ secondsLeft, onStay }: { secondsLeft: number; onStay: () => void }) {
  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="still-there-title"
      className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/60 p-8"
    >
      <div className="max-w-md rounded-lg border border-slate-300 bg-white p-6 shadow-lg">
        <h2 id="still-there-title" className="text-lg font-semibold">
          Still there?
        </h2>
        <p className="mt-2 text-sm text-slate-700">
          Nothing here has been touched for a while. In{' '}
          <strong className="tabular-nums">{minutesAndSeconds(secondsLeft)}</strong> UsefulRedact
          will close this session and delete its copies of your documents, so that what it found is
          not left on a screen nobody is watching. Your own files are untouched.
        </p>
        <button
          type="button"
          autoFocus
          onClick={onStay}
          className="mt-4 rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700"
        >
          I’m still here
        </button>
      </div>
    </div>
  );
}

export type ClosedOutcome = 'stopped' | 'cleared' | 'unreachable';

const AFTER: Record<ClosedOutcome, string> = {
  stopped:
    'UsefulRedact closed it, deleted its copies of the documents and what it had found, and stopped. You can close this tab, and start UsefulRedact again to check more.',
  cleared:
    'UsefulRedact closed it and deleted its copies of the documents and what it had found. Reload the page to check more.',
  // Said plainly, because it is the one case where the copies may still be there.
  unreachable:
    'What it had found has been taken off this page, but UsefulRedact could not be reached to close the session. If the app is still running, quit it from the window it was started in; its copies of the documents are deleted when it stops, or the next time it starts.',
};

/** What is left on the page once that has happened: nothing that was found. */
export function ClosedUnattended({ outcome }: { outcome: ClosedOutcome }) {
  return (
    <div className="flex h-screen items-center justify-center p-8 text-center">
      <p className="max-w-md text-slate-700">
        This session was left alone for {MINUTES} minutes. {AFTER[outcome]}
        <br />
        <br />
        Your own files are untouched.
      </p>
    </div>
  );
}
