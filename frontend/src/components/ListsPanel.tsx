import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

interface Props {
  watchlist: string;
  ignore: string;
  hasDocuments: boolean;
  onApply: (watchlist: string, ignore: string) => void;
}

/** The two optional lists. Both live in the running app's memory for this session only. */
export function ListsPanel({ watchlist, ignore, hasDocuments, onApply }: Props) {
  const [open, setOpen] = useState(false);
  const [watch, setWatch] = useState(watchlist);
  const [skip, setSkip] = useState(ignore);
  const changed = watch !== watchlist || skip !== ignore;
  const count = (text: string) => text.split('\n').filter((line) => line.trim()).length;
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center gap-1 px-3 py-2 text-left text-sm font-medium"
      >
        <Chevron className="h-4 w-4 text-slate-500" aria-hidden />
        <span className="whitespace-nowrap">Watchlist and ignore list</span>
        <span className="ml-auto text-xs font-normal whitespace-nowrap text-slate-500">
          {count(watchlist) + count(ignore) === 0
            ? 'optional'
            : `${count(watchlist)} · ${count(ignore)}`}
        </span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-slate-200 p-3">
          <label className="block text-xs font-medium text-slate-700">
            Names to look for, one per line
            <textarea
              value={watch}
              onChange={(e) => setWatch(e.target.value)}
              rows={3}
              placeholder="Benjamin Sampleton"
              className="mt-1 w-full rounded-md border border-slate-300 p-2 font-mono text-xs"
            />
            <span className="font-normal text-slate-500">
              Matched exactly, within OCR noise, and by one part of the name on its own.
            </span>
          </label>
          <label className="block text-xs font-medium text-slate-700">
            Leave alone, one per line
            <textarea
              value={skip}
              onChange={(e) => setSkip(e.target.value)}
              rows={3}
              placeholder={'Your organisation’s own address\n(03) 9000 0000'}
              className="mt-1 w-full rounded-md border border-slate-300 p-2 font-mono text-xs"
            />
            <span className="font-normal text-slate-500">
              The checker cannot tell your organisation’s address from a person’s. List it here.
            </span>
          </label>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={!changed}
              onClick={() => onApply(watch, skip)}
              className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-40"
            >
              {hasDocuments ? 'Apply and check again' : 'Apply'}
            </button>
            <span className="text-xs text-slate-500">Kept in memory for this session only.</span>
          </div>
        </div>
      )}
    </section>
  );
}
