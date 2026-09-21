import '@testing-library/jest-dom/vitest';

// vitest without `globals` never registers Testing Library's automatic cleanup, so renders
// from one test would still be in the document during the next.
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => cleanup());
