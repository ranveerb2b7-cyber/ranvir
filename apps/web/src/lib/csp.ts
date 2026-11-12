/**
 * Content Security Policy for the web app. Scripts need a per-request nonce (no
 * 'unsafe-inline' for scripts); network access is limited to our API and the auth server.
 */
export function contentSecurityPolicy(nonce: string, opts: { dev: boolean; apiUrl?: string; authUrl?: string }): string {
  const origins = [opts.apiUrl, opts.authUrl]
    .filter((u): u is string => Boolean(u))
    .map((u) => new URL(u).origin);
  const directives: Record<string, string[]> = {
    "default-src": ["'self'"],
    // 'strict-dynamic' lets Next's nonce'd bootstrap load its own chunks; dev needs eval for HMR.
    "script-src": ["'self'", `'nonce-${nonce}'`, "'strict-dynamic'", ...(opts.dev ? ["'unsafe-eval'"] : [])],
    // Inline style attributes (charts, Next) are needed; styles can't run code.
    "style-src": ["'self'", "'unsafe-inline'"],
    "img-src": ["'self'", "data:", "blob:"],
    "font-src": ["'self'", "data:"],
    "connect-src": ["'self'", ...origins, ...(opts.dev ? ["ws:"] : [])],
    "object-src": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
    "frame-ancestors": ["'none'"],
  };
  const policy = Object.entries(directives).map(([k, v]) => `${k} ${v.join(" ")}`);
  if (!opts.dev) policy.push("upgrade-insecure-requests");
  return policy.join("; ");
}
