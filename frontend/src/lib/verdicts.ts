/** How verdicts and findings are worded and coloured. Nothing here ever says "safe":
 *  the best a document can do is "No issues found", which is drawn in neutral grey, not
 *  green, because it means "nothing was detected" and not "this is fine to send". */

import type { Kind, Verdict } from '../api';

export interface VerdictStyle {
  label: string;
  /** One line under the label, for the document header. */
  explain: string;
  badge: string;
  dot: string;
}

export const VERDICTS: Record<Verdict, VerdictStyle> = {
  FAIL_RECOVERABLE: {
    label: 'Redaction fails',
    explain: 'Text can still be pulled out from under a redaction mark.',
    badge: 'bg-red-100 text-red-900 ring-red-300',
    dot: 'bg-red-600',
  },
  PI_VISIBLE: {
    label: 'Personal information visible',
    explain: 'Personal information was detected in text that can be read or OCR-read.',
    badge: 'bg-amber-100 text-amber-900 ring-amber-300',
    dot: 'bg-amber-500',
  },
  REVIEW_LOW_CONFIDENCE: {
    label: 'Needs a human look',
    explain: 'A page could not be read well enough to assess. Check it by eye.',
    badge: 'bg-violet-100 text-violet-900 ring-violet-300',
    dot: 'bg-violet-500',
  },
  NOT_CHECKED: {
    label: 'Not checked',
    explain: 'The file could not be read, so nothing was checked.',
    badge: 'bg-slate-800 text-white ring-slate-800',
    dot: 'bg-slate-800',
  },
  NO_ISSUES_FOUND: {
    label: 'No issues found',
    explain: 'Nothing was detected. This is not a guarantee.',
    badge: 'bg-slate-100 text-slate-700 ring-slate-300',
    dot: 'bg-slate-400',
  },
};

export interface KindStyle {
  label: string;
  /** Box on the page: border and a see-through fill. */
  box: string;
  boxSelected: string;
  chip: string;
}

export const KINDS: Record<Kind, KindStyle> = {
  recoverable: {
    label: 'Recoverable under a mark',
    box: 'border-red-600 bg-red-500/15',
    boxSelected: 'border-red-700 bg-red-500/30 ring-2 ring-red-600 ring-offset-1',
    chip: 'bg-red-100 text-red-900',
  },
  pi: {
    label: 'Personal information',
    box: 'border-amber-500 bg-amber-400/20',
    boxSelected: 'border-amber-600 bg-amber-400/35 ring-2 ring-amber-500 ring-offset-1',
    chip: 'bg-amber-100 text-amber-900',
  },
  context: {
    label: 'Context',
    box: 'border-sky-500 border-dashed bg-sky-400/10',
    boxSelected: 'border-sky-600 border-dashed bg-sky-400/25 ring-2 ring-sky-500 ring-offset-1',
    chip: 'bg-sky-100 text-sky-900',
  },
  low_confidence: {
    label: 'Read poorly',
    box: 'border-violet-500 bg-violet-400/10',
    boxSelected: 'border-violet-600 bg-violet-400/25 ring-2 ring-violet-500',
    chip: 'bg-violet-100 text-violet-900',
  },
};

export const KIND_ORDER: Kind[] = ['recoverable', 'pi', 'low_confidence', 'context'];

const DETECTORS: Record<string, string> = {
  drawn_shape: 'Shape drawn over text',
  see_through_shape: 'See-through shape',
  annotation: 'Annotation over text',
  see_through_annotation: 'See-through highlight',
  ink_annotation: 'Ink stroke over text',
  unapplied_redaction: 'Redaction never applied',
  pasted_image: 'Image placed over text',
  hidden_text: 'Hidden text',
  email: 'Email',
  phone_au: 'Phone number',
  dob: 'Date of birth',
  medicare: 'Medicare number',
  tfn: 'Tax file number',
  address_au: 'Street address',
  locality_au: 'Suburb and postcode',
  name_label: 'Name',
  ner_person: 'Name (model)',
  ner_gpe: 'Place name',
  ner_loc: 'Place name',
  watchlist: 'Watchlist',
  metadata_author: 'File author',
  ocr_confidence: 'Low read quality',
  ocr_no_text: 'Nothing readable',
  ocr_unavailable: 'OCR unavailable',
};

export function detectorLabel(detector: string): string {
  return DETECTORS[detector] ?? detector.replace(/_/g, ' ');
}

const SOURCES: Record<string, string> = {
  text_layer: 'text layer',
  ocr: 'OCR',
  ocr_enhanced: 'OCR after contrast stretch',
  metadata: 'file metadata',
  form_field: 'form field or comment',
};

export function sourceLabel(source: string): string {
  return SOURCES[source] ?? source;
}
