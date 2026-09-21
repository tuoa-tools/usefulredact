import { describe, expect, it } from 'vitest';
import { KINDS, VERDICTS, detectorLabel } from './verdicts';

describe('wording', () => {
  it('never calls a document safe, and never colours the best verdict green', () => {
    const words = [...Object.values(VERDICTS), ...Object.values(KINDS)]
      .map((v) => JSON.stringify(v).toLowerCase())
      .join(' ');
    expect(words).not.toMatch(/\bsafe\b|\bsecure\b|\bclean\b|\bpassed\b/);
    expect(VERDICTS.NO_ISSUES_FOUND.badge).not.toMatch(/green|emerald/);
    expect(VERDICTS.NO_ISSUES_FOUND.explain).toMatch(/not a guarantee/i);
  });

  it('names detectors in plain words and copes with one it has not met', () => {
    expect(detectorLabel('unapplied_redaction')).toBe('Redaction never applied');
    expect(detectorLabel('some_new_rule')).toBe('some new rule');
  });
});
