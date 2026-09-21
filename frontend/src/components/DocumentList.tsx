import { Loader2, X } from 'lucide-react';
import type { DocumentSummary } from '../api';
import { VerdictBadge } from './VerdictBadge';

interface Props {
  documents: DocumentSummary[];
  selected: string | null;
  onSelect: (id: string) => void;
  onRemove: (id: string) => void;
}

function Progress({ doc }: { doc: DocumentSummary }) {
  const label =
    doc.status === 'queued'
      ? 'Waiting'
      : doc.page_total > 0
        ? `Checking page ${Math.min(doc.page_done + 1, doc.page_total)} of ${doc.page_total}`
        : 'Checking';
  return (
    <span className="inline-flex items-center gap-1 text-xs text-slate-500">
      <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> {label}
    </span>
  );
}

function counts(doc: DocumentSummary): string {
  const parts = [];
  if (doc.counts.recoverable) parts.push(`${doc.counts.recoverable} recoverable`);
  if (doc.counts.pi) parts.push(`${doc.counts.pi} PI`);
  if (doc.counts.low_confidence) parts.push(`${doc.counts.low_confidence} read poorly`);
  if (doc.counts.context) parts.push(`${doc.counts.context} context`);
  return parts.join(' · ');
}

export function DocumentList({ documents, selected, onSelect, onRemove }: Props) {
  if (documents.length === 0) return null;
  return (
    <ul className="divide-y divide-slate-200 overflow-hidden rounded-lg border border-slate-200 bg-white">
      {documents.map((doc) => (
        <li
          key={doc.id}
          className={`group flex items-start gap-1 ${doc.id === selected ? 'bg-slate-100' : ''}`}
        >
          <button
            type="button"
            onClick={() => onSelect(doc.id)}
            aria-current={doc.id === selected}
            className="min-w-0 flex-1 px-3 py-2 text-left"
          >
            <span className="block truncate text-sm font-medium" title={doc.name}>
              {doc.name}
            </span>
            <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
              {doc.verdict ? <VerdictBadge verdict={doc.verdict} small /> : <Progress doc={doc} />}
              {doc.verdict && <span className="text-xs text-slate-500">{counts(doc)}</span>}
            </span>
          </button>
          <button
            type="button"
            onClick={() => onRemove(doc.id)}
            aria-label={`Remove ${doc.name} from this session`}
            title="Remove from this session (the file itself is untouched)"
            className="m-1 rounded p-1 text-slate-400 opacity-0 hover:bg-slate-200 hover:text-slate-700 focus:opacity-100 group-hover:opacity-100"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </li>
      ))}
    </ul>
  );
}
