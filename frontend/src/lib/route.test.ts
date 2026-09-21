import { describe, expect, it } from 'vitest';
import { formatRoute, parseRoute } from './route';

describe('route', () => {
  it('reads a document and a finding from the hash', () => {
    expect(parseRoute('#0a1b2c3d4e5f')).toEqual({ doc: '0a1b2c3d4e5f', finding: null });
    expect(parseRoute('#0a1b2c3d4e5f:12')).toEqual({ doc: '0a1b2c3d4e5f', finding: 12 });
  });

  it('ignores anything that is not an id', () => {
    expect(parseRoute('')).toEqual({ doc: null, finding: null });
    expect(parseRoute('#../etc/passwd:1')).toEqual({ doc: null, finding: null });
    expect(parseRoute('#0a1b2c3d4e5f:x')).toEqual({ doc: '0a1b2c3d4e5f', finding: null });
  });

  it('round-trips', () => {
    expect(formatRoute(parseRoute('#0a1b2c3d4e5f:3'))).toBe('#0a1b2c3d4e5f:3');
    expect(formatRoute({ doc: null, finding: 3 })).toBe('');
  });
});
