/** Files dropped or chosen in the browser: folders unpacked, unsupported ones left out.
 *  (UsefulText's helper, with this app's file types.) */

export const SUPPORTED = ['pdf', 'png', 'jpg', 'jpeg', 'tif', 'tiff', 'bmp', 'webp'];
export const ACCEPT = SUPPORTED.map((e) => `.${e}`).join(',');

export function isSupported(name: string): boolean {
  const ext = name.split('.').pop()?.toLowerCase() ?? '';
  return !name.startsWith('.') && name.includes('.') && SUPPORTED.includes(ext);
}

function byName(a: File, b: File): number {
  return a.name.localeCompare(b.name, undefined, { numeric: true });
}

async function readEntry(entry: FileSystemEntry): Promise<File[]> {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) =>
      (entry as FileSystemFileEntry).file(resolve, reject)
    );
    return [file];
  }
  if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    const out: File[] = [];
    for (;;) {
      const batch = await new Promise<FileSystemEntry[]>((resolve, reject) =>
        reader.readEntries(resolve, reject)
      );
      if (batch.length === 0) break;
      for (const e of batch) out.push(...(await readEntry(e)));
    }
    return out;
  }
  return [];
}

export interface Dropped {
  files: File[];
  /** Names left out because the type is not one the checker reads. */
  skipped: string[];
}

function sort(files: File[]): Dropped {
  return {
    files: files.filter((f) => isSupported(f.name)).sort(byName),
    skipped: files
      .filter((f) => !isSupported(f.name) && !f.name.startsWith('.'))
      .map((f) => f.name),
  };
}

/** What a drop contained; a dropped folder is walked. */
export async function filesFromDataTransfer(dt: DataTransfer): Promise<Dropped> {
  const entries = Array.from(dt.items ?? [])
    .map((item) => (item.webkitGetAsEntry ? item.webkitGetAsEntry() : null))
    .filter((e): e is FileSystemEntry => e !== null);
  if (!entries.some((e) => e.isDirectory)) return sort(Array.from(dt.files));
  const files: File[] = [];
  for (const e of entries) files.push(...(await readEntry(e)));
  return sort(files);
}

export function filesFromInput(list: FileList | null): Dropped {
  return sort(Array.from(list ?? []));
}
