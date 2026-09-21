import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, Lock, Power, Trash2 } from 'lucide-react';
import { api, exportUrl, type Session } from './api';
import { DocumentList } from './components/DocumentList';
import { DocumentView } from './components/DocumentView';
import { DropZone } from './components/DropZone';
import { ListsPanel } from './components/ListsPanel';
import { VerdictBadge } from './components/VerdictBadge';
import type { Dropped } from './lib/files';
import { healthQueryOptions } from './lib/keepAlive';
import { parseRoute, writeRoute } from './lib/route';
import { VERDICTS } from './lib/verdicts';

const POLL_MS = 700;

function Welcome() {
  const order = [
    'FAIL_RECOVERABLE',
    'PI_VISIBLE',
    'REVIEW_LOW_CONFIDENCE',
    'NO_ISSUES_FOUND',
  ] as const;
  return (
    <div className="mx-auto max-w-2xl p-8">
      <h2 className="text-xl font-semibold">Does the redaction actually hold?</h2>
      <p className="mt-2 text-slate-700">
        A black box drawn over text hides it from the eye and leaves it in the file. Drop in
        documents you are about to send, and this checks what can still be pulled out: text under
        boxes, annotations and pasted images, text a marker pen let through on a scan, and personal
        information left in plain view.
      </p>
      <ul className="mt-5 space-y-3">
        {order.map((verdict) => (
          <li key={verdict} className="flex items-start gap-3">
            <span className="w-60 shrink-0">
              <VerdictBadge verdict={verdict} small />
            </span>
            <span className="text-sm text-slate-700">{VERDICTS[verdict].explain}</span>
          </li>
        ))}
      </ul>
      <p className="mt-6 rounded-md border border-slate-300 bg-white p-3 text-sm text-slate-700">
        <strong>It is a checker, not a guarantee.</strong> It never says a document is safe, and it
        never changes a file. It misses things: handwriting, faces, kinds of personal information it
        has no rule for, names the model does not know. Every finding is shown on the page so a
        person can decide.
      </p>
    </div>
  );
}

/** The server has gone without being asked to: the window it was started from was closed,
 * it stopped by itself after the tab was left, or it was killed. Whatever is behind this
 * was checked earlier, so it is covered and made inert rather than left to be read as a
 * verdict that still stands. It does not say the copies were deleted: a stop of this kind
 * deletes them, a kill cannot, and from in here there is no telling which happened. */
function ServerStopped() {
  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="stopped-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-8"
    >
      <div className="max-w-md rounded-lg border border-slate-300 bg-white p-6 shadow-lg">
        <h2 id="stopped-title" className="text-lg font-semibold">
          UsefulRedact is no longer running
        </h2>
        <p className="mt-2 text-sm text-slate-700">
          The app behind this tab has stopped – its window was closed, or it stopped by itself after
          the tab had been left for a while.
        </p>
        <p className="mt-3 text-sm text-slate-700">
          What is on this page was checked earlier and is no longer live. Nothing more can be
          checked here. Start UsefulRedact again to go on.
        </p>
      </div>
    </div>
  );
}

export default function App() {
  const queryClient = useQueryClient();
  const [selected, setSelectedState] = useState<string | null>(
    () => parseRoute(window.location.hash).doc
  );
  const setSelected = (doc: string | null) => {
    setSelectedState(doc);
    writeRoute({ doc, finding: null });
  };
  const [notice, setNotice] = useState<string | null>(null);

  const health = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    ...healthQueryOptions, // also the keep-alive: see lib/keepAlive.ts
  });
  const session = useQuery({
    queryKey: ['session'],
    queryFn: api.session,
    refetchInterval: (query) => (query.state.data?.checking ? POLL_MS : false),
  });

  const put = (data: Session) => queryClient.setQueryData(['session'], data);
  const fail = (error: Error) => setNotice(error.message);
  const add = useMutation({
    mutationFn: api.addFiles,
    onError: fail,
    onSuccess: (data) => {
      put(data);
      if (!selected && data.documents.length > 0) setSelected(data.documents[0].id);
    },
  });
  const lists = useMutation({
    mutationFn: (v: { watchlist: string; ignore: string }) => api.setLists(v.watchlist, v.ignore),
    onSuccess: put,
    onError: fail,
  });
  const remove = useMutation({ mutationFn: api.remove, onSuccess: put, onError: fail });
  const clear = useMutation({ mutationFn: api.clear, onSuccess: put, onError: fail });
  const quit = useMutation({
    mutationFn: api.quit,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['health'] }),
  });

  function onFiles(dropped: Dropped) {
    setNotice(
      dropped.skipped.length > 0
        ? `Left out (not PDF, PNG or JPG): ${dropped.skipped.slice(0, 5).join(', ')}${
            dropped.skipped.length > 5 ? '…' : ''
          }`
        : null
    );
    if (dropped.files.length > 0) add.mutate(dropped.files);
  }

  const documents = session.data?.documents ?? [];
  const current = documents.find((d) => d.id === selected) ?? null;
  const checked = documents.filter((d) => d.status === 'done').length;

  if (health.data?.quit_requested || quit.isSuccess) {
    return (
      <div className="flex h-screen items-center justify-center p-8 text-center">
        <p className="text-slate-700">
          UsefulRedact has stopped, and this session’s copies and results are deleted.
          <br />
          You can close this tab.
        </p>
      </div>
    );
  }

  // Only once the retries in lib/keepAlive.ts are spent: one failed ping is not a stopped app.
  const stopped = health.isError;

  return (
    <>
      <div className="flex h-screen flex-col" inert={stopped}>
        <header className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-slate-200 bg-white px-4 py-2">
          <h1 className="text-lg font-semibold">UsefulRedact</h1>
          <p className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-700">
            <Lock className="h-3.5 w-3.5" aria-hidden />
            Runs locally – nothing is uploaded, and nothing is kept when you quit
          </p>
          <span className="ml-auto text-xs text-slate-500">
            {health.data ? `v${health.data.version}` : ''}
            {health.data?.ocr === false && ' · OCR unavailable: scans cannot be read'}
            {health.data?.ner === false && ' · name model unavailable'}
          </span>
          {health.data?.desktop && (
            <button
              type="button"
              onClick={() => quit.mutate()}
              className="inline-flex items-center gap-1 rounded-md border border-slate-300 px-2.5 py-1 text-sm hover:bg-slate-50"
            >
              <Power className="h-4 w-4" aria-hidden /> Quit
            </button>
          )}
        </header>

        {session.error && (
          <p role="alert" className="bg-red-50 px-4 py-2 text-sm text-red-800">
            {session.error.message}
          </p>
        )}

        <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[22rem_minmax(0,1fr)]">
          <aside className="min-h-0 space-y-3 overflow-auto border-r border-slate-200 p-3">
            <DropZone onFiles={onFiles} busy={add.isPending} />
            {notice && (
              <p role="status" className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900">
                {notice}
              </p>
            )}
            <ListsPanel
              key={`${session.data?.watchlist}|${session.data?.ignore}`}
              watchlist={session.data?.watchlist ?? ''}
              ignore={session.data?.ignore ?? ''}
              hasDocuments={documents.length > 0}
              onApply={(watchlist, ignore) => lists.mutate({ watchlist, ignore })}
            />
            <DocumentList
              documents={documents}
              selected={selected}
              onSelect={setSelected}
              onRemove={(id) => {
                if (id === selected) setSelected(null);
                remove.mutate(id);
              }}
            />
            {documents.length > 0 && (
              <section className="rounded-lg border border-slate-200 bg-white p-3">
                <h2 className="text-sm font-medium">Export the report</h2>
                <div className="mt-2 flex flex-wrap gap-2">
                  {(
                    [
                      ['json', 'JSON'],
                      ['findings', 'Findings CSV'],
                      ['documents', 'Documents CSV'],
                    ] as const
                  ).map(([kind, label]) => (
                    <a
                      key={kind}
                      href={checked > 0 ? exportUrl(kind) : undefined}
                      aria-disabled={checked === 0}
                      className={`inline-flex items-center gap-1 rounded-md border border-slate-300 px-2.5 py-1 text-sm ${
                        checked > 0 ? 'hover:bg-slate-50' : 'pointer-events-none opacity-40'
                      }`}
                    >
                      <Download className="h-4 w-4" aria-hidden /> {label}
                    </a>
                  ))}
                </div>
                <p className="mt-2 text-xs text-slate-500">
                  A report contains the personal information that was found: that is the evidence.
                  Keep it where you keep the documents.
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setSelected(null);
                    clear.mutate();
                  }}
                  className="mt-3 inline-flex items-center gap-1 text-xs text-slate-600 hover:text-slate-900"
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden /> Clear this session (your files are
                  untouched)
                </button>
              </section>
            )}
          </aside>

          <main className="min-h-0 overflow-auto">
            {current ? <DocumentView key={current.id} summary={current} /> : <Welcome />}
          </main>
        </div>
      </div>
      {stopped && <ServerStopped />}
    </>
  );
}
