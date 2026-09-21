/** The address bar remembers which document (and finding) is open: `#<doc>` or
 *  `#<doc>:<finding>`. Ids only, never a file name: the hash ends up in browser history. */

export interface Route {
  doc: string | null;
  finding: number | null;
}

export function parseRoute(hash: string): Route {
  const [doc, finding] = hash.replace(/^#/, '').split(':');
  const id = /^[0-9a-f]{6,32}$/.test(doc ?? '') ? doc : null;
  const n = finding !== undefined && /^\d+$/.test(finding) ? Number(finding) : null;
  return { doc: id, finding: id ? n : null };
}

export function formatRoute(route: Route): string {
  if (!route.doc) return '';
  return route.finding === null ? `#${route.doc}` : `#${route.doc}:${route.finding}`;
}

export function writeRoute(route: Route): void {
  const next = formatRoute(route);
  if (next !== window.location.hash) {
    window.history.replaceState(null, '', next || window.location.pathname);
  }
}
