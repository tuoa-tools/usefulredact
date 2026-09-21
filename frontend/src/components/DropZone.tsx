import { useRef, useState } from 'react';
import { FolderOpen, Upload } from 'lucide-react';
import { ACCEPT, filesFromDataTransfer, filesFromInput, type Dropped } from '../lib/files';

interface Props {
  onFiles: (dropped: Dropped) => void;
  busy: boolean;
}

/** Drop files or a folder, or choose them. "Add" here means "hand to the checker running
 *  on this machine": the page says so, because an upload box suggests otherwise. */
export function DropZone({ onFiles, busy }: Props) {
  const [over, setOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={async (e) => {
        e.preventDefault();
        setOver(false);
        onFiles(await filesFromDataTransfer(e.dataTransfer));
      }}
      className={`rounded-lg border-2 border-dashed p-4 text-center transition-colors ${
        over ? 'border-slate-700 bg-slate-200' : 'border-slate-300 bg-white'
      }`}
    >
      <Upload className="mx-auto h-6 w-6 text-slate-500" aria-hidden />
      <p className="mt-1 text-sm font-medium">Drop documents here</p>
      <p className="text-xs text-slate-500">PDF, PNG or JPG. Files are read, never changed.</p>
      <div className="mt-3 flex justify-center gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => fileInput.current?.click()}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
        >
          Choose files
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => folderInput.current?.click()}
          className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium hover:bg-slate-50 disabled:opacity-50"
        >
          <FolderOpen className="h-4 w-4" aria-hidden /> Folder
        </button>
      </div>
      <input
        ref={fileInput}
        type="file"
        multiple
        accept={ACCEPT}
        className="hidden"
        aria-label="Choose files to check"
        onChange={(e) => {
          onFiles(filesFromInput(e.target.files));
          e.target.value = '';
        }}
      />
      <input
        ref={folderInput}
        type="file"
        multiple
        className="hidden"
        aria-label="Choose a folder to check"
        // @ts-expect-error - a folder picker: not in React's types, supported by every browser
        webkitdirectory=""
        onChange={(e) => {
          onFiles(filesFromInput(e.target.files));
          e.target.value = '';
        }}
      />
    </div>
  );
}
