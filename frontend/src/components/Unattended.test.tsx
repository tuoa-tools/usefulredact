import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ClosedUnattended, StillThere } from './Unattended';

describe('left alone', () => {
  it('asks first, says what will happen and when, and takes yes for an answer', () => {
    const onStay = vi.fn();
    render(<StillThere secondsLeft={95} onStay={onStay} />);
    const dialog = screen.getByRole('alertdialog');
    expect(dialog).toHaveTextContent('1:35');
    expect(dialog).toHaveTextContent(/delete its copies of your documents/);
    expect(dialog).toHaveTextContent(/Your own files are untouched/);
    fireEvent.click(screen.getByRole('button', { name: /still here/i }));
    expect(onStay).toHaveBeenCalled();
  });

  it('says afterwards what was done, in words that promise nothing about the documents', () => {
    const { container, rerender } = render(<ClosedUnattended outcome="stopped" />);
    expect(container).toHaveTextContent(/left alone for 30 minutes/);
    expect(container).toHaveTextContent(/deleted its copies .* and stopped/);
    rerender(<ClosedUnattended outcome="cleared" />);
    expect(container).toHaveTextContent(/Reload the page/);
    for (const outcome of ['stopped', 'cleared', 'unreachable'] as const) {
      rerender(<ClosedUnattended outcome={outcome} />);
      expect(container.textContent?.toLowerCase()).not.toMatch(
        /\bsafe\b|\bsecure\b|\bclean\b|\bpassed\b/
      );
    }
  });

  it('does not claim the copies were deleted when the app could not be reached', () => {
    const { container } = render(<ClosedUnattended outcome="unreachable" />);
    expect(container).toHaveTextContent(/could not be reached/);
    expect(container.textContent).not.toMatch(/deleted its copies/);
  });
});
