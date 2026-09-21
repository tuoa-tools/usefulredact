/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend origin; empty in dev (Vite proxies /api) and in the packaged app (same origin). */
  readonly VITE_API_URL?: string;
}
