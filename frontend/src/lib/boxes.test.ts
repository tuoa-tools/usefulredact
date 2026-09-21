import { describe, expect, it } from 'vitest';
import { drawnBoxes, percentBox } from './boxes';

describe('percentBox', () => {
  it('places a box as percentages of the page, so it follows the picture at any size', () => {
    expect(percentBox([59.5, 84.2, 119, 168.4], 595, 842, 0)).toEqual({
      left: '10%',
      top: '10%',
      width: '10%',
      height: '10%',
    });
  });

  it('pads the box and keeps it on the page', () => {
    const box = percentBox([0, 0, 595, 842], 595, 842, 5);
    expect(box).toEqual({ left: '0%', top: '0%', width: '100%', height: '100%' });
  });
});

describe('drawnBoxes', () => {
  it('draws one box per line when the finding has them', () => {
    const lines: [number, number, number, number][] = [
      [1, 1, 5, 2],
      [1, 3, 4, 4],
    ];
    expect(drawnBoxes({ boxes: lines, bbox: [1, 1, 5, 4] })).toEqual(lines);
  });

  it('falls back to the outer box, and to nothing for a finding with no place', () => {
    expect(drawnBoxes({ boxes: [], bbox: [1, 1, 5, 4] })).toEqual([[1, 1, 5, 4]]);
    expect(drawnBoxes({ boxes: [], bbox: null })).toEqual([]);
  });
});
