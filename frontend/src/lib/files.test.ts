import { describe, expect, it } from 'vitest';
import { filesFromInput, isSupported } from './files';

function list(...names: string[]): FileList {
  const files = names.map((n) => new File(['x'], n));
  return Object.assign(files, { item: (i: number) => files[i] }) as unknown as FileList;
}

describe('files', () => {
  it('knows what the checker reads', () => {
    expect(isSupported('letter.PDF')).toBe(true);
    expect(isSupported('scan.jpeg')).toBe(true);
    expect(isSupported('notes.docx')).toBe(false);
    expect(isSupported('.DS_Store')).toBe(false);
  });

  it('keeps supported files in name order and reports the rest', () => {
    const dropped = filesFromInput(list('page10.png', 'page2.png', 'notes.docx', '.DS_Store'));
    expect(dropped.files.map((f) => f.name)).toEqual(['page2.png', 'page10.png']);
    expect(dropped.skipped).toEqual(['notes.docx']);
  });
});
