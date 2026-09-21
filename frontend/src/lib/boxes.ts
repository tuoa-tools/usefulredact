/** Where a finding's box goes on a picture of its page. Boxes and the page share one
 *  unit (points or pixels), so positions are plain percentages and the overlay follows
 *  the picture at any size without measuring it. */

import type { Box } from '../api';

export interface PercentBox {
  left: string;
  top: string;
  width: string;
  height: string;
}

const pct = (value: number) => `${Math.round(value * 1e4) / 100}%`;

/** A box as CSS percentages of the page, grown by `pad` page-units and kept on the page. */
export function percentBox(box: Box, pageWidth: number, pageHeight: number, pad = 1): PercentBox {
  const x0 = Math.max(0, box[0] - pad);
  const y0 = Math.max(0, box[1] - pad);
  const x1 = Math.min(pageWidth, box[2] + pad);
  const y1 = Math.min(pageHeight, box[3] + pad);
  return {
    left: pct(x0 / pageWidth),
    top: pct(y0 / pageHeight),
    width: pct(Math.max(0, x1 - x0) / pageWidth),
    height: pct(Math.max(0, y1 - y0) / pageHeight),
  };
}

/** The boxes to draw for a finding: one per line when it has them, else its outer box. */
export function drawnBoxes(finding: { boxes: Box[]; bbox: Box | null }): Box[] {
  if (finding.boxes.length > 0) return finding.boxes;
  return finding.bbox ? [finding.bbox] : [];
}
