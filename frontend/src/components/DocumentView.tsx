import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, Download, Loader2 } from 'lucide-react';
import {
  api,
  exportUrl,
  pageImageUrl,
  type DocumentSummary,
  type Finding,
  type Kind,
  type PageInfo,
} from '../api';
import { drawnBoxes, percentBox } from '../lib/boxes';
import { parseRoute, writeRoute } from '../lib/route';
import { KIND_ORDER, KINDS, VERDICTS, detectorLabel, sourceLabel } from '../lib/verdicts';
import { VerdictBadge } from './VerdictBadge';

/** Detectors that are annotations: drawing the page without them shows what they cover. */
const ANNOTATION_MARKS = new Set([
  'annotation',
  'see_through_annotation',
  'ink_annotation',
  'unapplied_redaction',
]);

interface PageProps {
  docId: string;
  page: PageInfo;
  findings: Finding[];
  selected: number | null;
  annotations: boolean;
  onSelect: (id: number) => void;
}

/** The page as a picture with a box on every finding. Boxes are percentages of the page,
 *  so they follow the picture at any width. */
function PagePicture({ docId, page, findings, selected, annotations, onSelect }: PageProps) {
  const selectedBox = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    selectedBox.current?.scrollIntoView?.({ block: 'center', behavior: 'smooth' });
  }, [selected, page.number]);

  return (
    <div className="relative mx-auto w-full max-w-4xl bg-white shadow ring-1 ring-slate-300">
      <img
        src={pageImageUrl(docId, page.number, annotations)}
        alt={`Page ${page.number}`}
        className="block w-full select-none"
        style={{ aspectRatio: `${page.width} / ${page.height}` }}
        draggable={false}
      />
      {findings.flatMap((finding) =>
        drawnBoxes(finding).map((box, index) => {
          const isSelected = finding.id === selected;
          const style = KINDS[finding.kind];
          return (
            <button
              key={`${finding.id}-${index}`}
              ref={isSelected && index === 0 ? selectedBox : undefined}
              type="button"
              onClick={() => onSelect(finding.id)}
              title={`${detectorLabel(finding.detector)}: ${finding.text}`}
              aria-label={`${KINDS[finding.kind].label}: ${detectorLabel(finding.detector)}`}
              aria-pressed={isSelected}
              data-kind={finding.kind}
              className={`absolute cursor-pointer rounded-sm border-2 ${
                isSelected ? style.boxSelected : style.box
              }`}
              style={percentBox(box, page.width, page.height)}
            />
          );
        })
      )}
    </div>
  );
}

interface RowProps {
  finding: Finding;
  selected: boolean;
  onSelect: (id: number) => void;
}

function FindingRow({ finding, selected, onSelect }: RowProps) {
  const row = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (selected) row.current?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
  }, [selected]);
  const style = KINDS[finding.kind];
  return (
    <li>
      <button
        ref={row}
        type="button"
        onClick={() => onSelect(finding.id)}
        aria-pressed={selected}
        className={`w-full rounded-md border px-2.5 py-2 text-left ${
          selected ? 'border-slate-900 bg-white shadow' : 'border-transparent hover:bg-white'
        }`}
      >
        <span className="flex flex-wrap items-center gap-1.5">
          <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${style.chip}`}>
            {detectorLabel(finding.detector)}
          </span>
          <span className="text-xs text-slate-500">
            {finding.page > 0 ? `p. ${finding.page}` : 'the file itself'} ·{' '}
            {sourceLabel(finding.source)}
          </span>
        </span>
        {finding.text && (
          <span className="mt-1 block font-mono text-sm break-words">
            {finding.kind === 'recoverable' && (
              <span className="font-sans text-xs text-slate-500">recovered: </span>
            )}
            {finding.text}
          </span>
        )}
        {finding.holds.length > 0 && (
          <span className="mt-0.5 block text-xs font-medium text-slate-800">
            Holds: {finding.holds.map(detectorLabel).join(', ').toLowerCase()}
          </span>
        )}
        {finding.detail && (
          <span className="mt-0.5 block text-xs text-slate-600">{finding.detail}</span>
        )}
        {finding.also.length > 0 && (
          <span className="mt-0.5 block text-xs text-slate-500">
            Also matched by: {finding.also.map(detectorLabel).join(', ').toLowerCase()}
          </span>
        )}
      </button>
    </li>
  );
}

export function DocumentView({ summary }: { summary: DocumentSummary }) {
  const stamp = `${summary.status}:${summary.verdict}:${JSON.stringify(summary.counts)}`;
  const detail = useQuery({
    queryKey: ['document', summary.id, stamp],
    queryFn: () => api.document(summary.id),
    enabled: summary.status === 'done',
  });
  const [pageNumber, setPageNumber] = useState(1);
  const [selected, setSelected] = useState<number | null>(() => {
    const route = parseRoute(window.location.hash);
    return route.doc === summary.id ? route.finding : null;
  });
  const [hidden, setHidden] = useState<Set<Kind>>(new Set());
  const [annotations, setAnnotations] = useState(true);

  const findings = useMemo(() => detail.data?.findings ?? [], [detail.data]);
  const pages = detail.data?.page_list ?? [];
  const page = pages.find((p) => p.number === pageNumber) ?? pages[0];
  const shown = findings.filter((f) => !hidden.has(f.kind));
  const isPdf = summary.name.toLowerCase().endsWith('.pdf');
  const hasAnnotationMarks = findings.some((f) => ANNOTATION_MARKS.has(f.detector));

  function select(id: number) {
    setSelected(id);
    writeRoute({ doc: summary.id, finding: id });
    const finding = findings.find((f) => f.id === id);
    if (finding && finding.page > 0) setPageNumber(finding.page);
  }

  // A finding opened from the address bar may be on a later page.
  const linked = findings.find((f) => f.id === selected);
  const [followed, setFollowed] = useState(false);
  if (!followed && linked) {
    setFollowed(true);
    if (linked.page > 0 && linked.page !== pageNumber) setPageNumber(linked.page);
  }

  if (summary.status !== 'done' || !summary.verdict) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-slate-500">
        <Loader2 className="h-5 w-5 animate-spin" aria-hidden /> Checking {summary.name}…
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="border-b border-slate-200 bg-white px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h2 className="min-w-0 truncate text-base font-semibold" title={summary.name}>
            {summary.name}
          </h2>
          <VerdictBadge verdict={summary.verdict} />
          <a
            href={exportUrl('json', summary.id)}
            className="ml-auto inline-flex items-center gap-1 rounded-md border border-slate-300 px-2.5 py-1 text-sm hover:bg-slate-50"
          >
            <Download className="h-4 w-4" aria-hidden /> This document (JSON)
          </a>
        </div>
        <p className="mt-1 text-sm text-slate-600">
          {summary.error || VERDICTS[summary.verdict].explain}
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {KIND_ORDER.filter((kind) => summary.counts[kind] > 0).map((kind) => {
            const off = hidden.has(kind);
            return (
              <button
                key={kind}
                type="button"
                aria-pressed={!off}
                onClick={() => {
                  const next = new Set(hidden);
                  if (off) next.delete(kind);
                  else next.add(kind);
                  setHidden(next);
                }}
                className={`rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ring-slate-300 ${
                  off ? 'bg-white text-slate-400 line-through' : KINDS[kind].chip
                }`}
              >
                {KINDS[kind].label} · {summary.counts[kind]}
              </button>
            );
          })}
          {isPdf && hasAnnotationMarks && (
            <label className="ml-auto inline-flex items-center gap-1.5 text-xs text-slate-700">
              <input
                type="checkbox"
                checked={!annotations}
                onChange={(e) => setAnnotations(!e.target.checked)}
              />
              Draw the page without its annotations
            </label>
          )}
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-h-0 overflow-auto bg-slate-200 p-4">
          {pages.length > 1 && page && (
            <div className="mb-3 flex items-center justify-center gap-2 text-sm">
              <button
                type="button"
                aria-label="Previous page"
                disabled={page.number <= 1}
                onClick={() => setPageNumber(page.number - 1)}
                className="rounded border border-slate-300 bg-white p-1 disabled:opacity-40"
              >
                <ChevronLeft className="h-4 w-4" aria-hidden />
              </button>
              Page {page.number} of {pages.length}
              <button
                type="button"
                aria-label="Next page"
                disabled={page.number >= pages.length}
                onClick={() => setPageNumber(page.number + 1)}
                className="rounded border border-slate-300 bg-white p-1 disabled:opacity-40"
              >
                <ChevronRight className="h-4 w-4" aria-hidden />
              </button>
            </div>
          )}
          {page ? (
            <>
              <PagePicture
                docId={summary.id}
                page={page}
                findings={shown.filter((f) => f.page === page.number)}
                selected={selected}
                annotations={annotations}
                onSelect={select}
              />
              <p className="mx-auto mt-2 max-w-4xl text-xs text-slate-500">
                Read from the {page.source === 'ocr' ? 'picture by OCR' : 'text layer'}
                {page.ocr_mean_conf !== null &&
                  ` · read quality ${page.ocr_mean_conf.toFixed(2)} over ${page.ocr_regions} lines`}
                {page.enhanced_pass &&
                  ' · dark strokes found, so a contrast-stretched copy was read too'}
              </p>
            </>
          ) : (
            <p className="text-center text-sm text-slate-500">
              {detail.isLoading ? 'Loading…' : 'There is no page to show for this file.'}
            </p>
          )}
        </div>

        <aside className="min-h-0 overflow-auto border-l border-slate-200 bg-slate-50 p-2">
          <h3 className="px-2 py-1 text-xs font-semibold tracking-wide text-slate-500 uppercase">
            Findings · {shown.length}
          </h3>
          {shown.length === 0 ? (
            <p className="px-2 py-3 text-sm text-slate-600">
              Nothing was detected in this document. That is not a guarantee: read the limitations
              before relying on it.
            </p>
          ) : (
            <ul className="space-y-1">
              {shown.map((finding) => (
                <FindingRow
                  key={finding.id}
                  finding={finding}
                  selected={finding.id === selected}
                  onSelect={select}
                />
              ))}
            </ul>
          )}
        </aside>
      </div>
    </div>
  );
}
