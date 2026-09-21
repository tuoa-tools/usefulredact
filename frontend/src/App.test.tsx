import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import type { DocumentDetail, Health, Session } from './api';

const health: Health = {
  status: 'ok',
  version: '0.1.0',
  desktop: false,
  ocr: true,
  ocr_error: null,
  ner: true,
  ner_error: null,
  checking: 0,
  quit_requested: false,
};

const summary = {
  id: 'abc',
  name: 'letter.pdf',
  status: 'done' as const,
  page_done: 1,
  page_total: 1,
  verdict: 'FAIL_RECOVERABLE' as const,
  meaning: 'Text is still extractable under a redaction mark',
  error: '',
  pages: 1,
  counts: { recoverable: 1, pi: 1, context: 0, low_confidence: 0 },
};

const detail: DocumentDetail = {
  ...summary,
  page_list: [
    {
      number: 1,
      width: 595,
      height: 842,
      source: 'text_layer',
      ocr_mean_conf: null,
      ocr_regions: 0,
      enhanced_pass: false,
    },
  ],
  findings: [
    {
      id: 0,
      page: 1,
      kind: 'recoverable',
      detector: 'drawn_shape',
      text: 'Kylie Nguyen',
      bbox: [100, 100, 200, 112],
      boxes: [[100, 100, 200, 112]],
      source: 'text_layer',
      detail: 'a filled shape drawn over the text',
      score: null,
      covered: false,
      holds: ['name_label', 'dob'],
      also: [],
    },
    {
      id: 1,
      page: 1,
      kind: 'pi',
      detector: 'phone_au',
      text: '0412 345 678',
      bbox: [100, 300, 180, 312],
      boxes: [[100, 300, 180, 312]],
      source: 'text_layer',
      detail: '',
      score: null,
      covered: false,
      holds: [],
      also: ['ner_person'],
    },
  ],
};

function serve(session: Session) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.endsWith('/api/health')
        ? health
        : url.endsWith('/api/session')
          ? session
          : url.includes('/api/documents/abc')
            ? detail
            : {};
      return new Response(JSON.stringify(body), { status: 200 });
    })
  );
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  );
}

beforeEach(() => serve({ watchlist: '', ignore: '', checking: 0, documents: [] }));
afterEach(() => vi.unstubAllGlobals());

describe('App', () => {
  it('says up front that it runs locally and is not a guarantee', async () => {
    show();
    expect(await screen.findByText(/Runs locally – nothing is uploaded/)).toBeInTheDocument();
    expect(screen.getByText(/It is a checker, not a guarantee/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/\bsafe to\b/i);
  });

  it('shows a verdict badge per file, and a box on the page for every finding', async () => {
    serve({ watchlist: '', ignore: '', checking: 0, documents: [summary] });
    show();
    const row = await screen.findByRole('button', { name: /^letter\.pdf/ });
    expect(within(row).getByText('Redaction fails')).toBeInTheDocument();
    fireEvent.click(row);

    const box = await screen.findByRole('button', {
      name: /Recoverable under a mark: Shape drawn over text/,
    });
    expect(box).toHaveStyle({ left: '16.64%' });
    expect(screen.getByRole('button', { name: /Personal information: Phone number/ })).toBeTruthy();
    expect(screen.getByText('Kylie Nguyen')).toBeInTheDocument();
    expect(screen.getByText('Holds: name, date of birth')).toBeInTheDocument(); // plain words
    expect(screen.getByAltText('Page 1')).toHaveAttribute(
      'src',
      '/api/documents/abc/pages/1/image?width=1400'
    );
  });

  it('selects the same finding from the page or from the list', async () => {
    serve({ watchlist: '', ignore: '', checking: 0, documents: [summary] });
    show();
    fireEvent.click(await screen.findByRole('button', { name: /^letter\.pdf/ }));
    const box = await screen.findByRole('button', {
      name: /Recoverable under a mark: Shape drawn over text/,
    });
    fireEvent.click(box);
    expect(box).toHaveAttribute('aria-pressed', 'true');
    const listRow = screen.getByText('Kylie Nguyen').closest('button')!;
    expect(listRow).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(screen.getByText('0412 345 678').closest('button')!);
    expect(box).toHaveAttribute('aria-pressed', 'false');
  });

  it('says the app has stopped, and will not let what it found be read as current', async () => {
    // The tab is fine; the app behind it is gone. The session answers from cache so the
    // findings are still on the page underneath - which is the case that matters.
    const documents = { watchlist: '', ignore: '', checking: 0, documents: [summary] };
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith('/api/health')) throw new TypeError('Failed to fetch');
        const body = url.endsWith('/api/session')
          ? documents
          : url.includes('/api/documents/abc')
            ? detail
            : {};
        return new Response(JSON.stringify(body), { status: 200 });
      })
    );
    show();

    // Long enough for the retries in App.tsx to be spent; a single failed ping must not do it.
    const dialog = await screen.findByRole('alertdialog', {}, { timeout: 8000 });
    expect(within(dialog).getByText(/no longer running/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/checked earlier and is no longer live/i)).toBeInTheDocument();

    // Nothing behind it can be reached, so a stale verdict cannot be clicked into.
    expect(document.querySelector('[inert]')).toBeTruthy();

    // It must not say the copies were deleted: from here there is no telling whether the app
    // stopped tidily or was killed.
    expect(dialog.textContent).not.toMatch(/deleted/i);
    expect(dialog.textContent?.toLowerCase()).not.toMatch(
      /\bsafe\b|\bsecure\b|\bclean\b|\bpassed\b/
    );
  }, 15000);

  it('hides a kind of finding from the page and the list', async () => {
    serve({ watchlist: '', ignore: '', checking: 0, documents: [summary] });
    show();
    fireEvent.click(await screen.findByRole('button', { name: /^letter\.pdf/ }));
    await screen.findByText('0412 345 678');
    fireEvent.click(screen.getByRole('button', { name: /Personal information · 1/ }));
    expect(screen.queryByText('0412 345 678')).not.toBeInTheDocument();
    expect(screen.getByText('Kylie Nguyen')).toBeInTheDocument();
  });
});
