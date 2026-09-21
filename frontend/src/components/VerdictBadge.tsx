import { CircleHelp, EyeOff, FileX, Search, ShieldAlert } from 'lucide-react';
import type { Verdict } from '../api';
import { VERDICTS } from '../lib/verdicts';

const ICONS = {
  FAIL_RECOVERABLE: ShieldAlert,
  PI_VISIBLE: EyeOff,
  REVIEW_LOW_CONFIDENCE: CircleHelp,
  NOT_CHECKED: FileX,
  NO_ISSUES_FOUND: Search,
} as const;

/** A verdict as a label with an icon: never colour alone, and never the word "safe". */
export function VerdictBadge({ verdict, small = false }: { verdict: Verdict; small?: boolean }) {
  const style = VERDICTS[verdict];
  const Icon = ICONS[verdict];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full font-medium ring-1 ring-inset ${style.badge} ${
        small ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm'
      }`}
    >
      <Icon className={small ? 'h-3 w-3' : 'h-4 w-4'} aria-hidden />
      {style.label}
    </span>
  );
}
