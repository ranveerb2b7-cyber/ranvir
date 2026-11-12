import { describe, expect, it } from "vitest";

import { contentSecurityPolicy } from "@/lib/csp";

describe("contentSecurityPolicy", () => {
  it("allows only nonce'd scripts and our API/auth origins in production", () => {
    const csp = contentSecurityPolicy("abc123", {
      dev: false,
      apiUrl: "https://api.example.com/api/v1",
      authUrl: "https://auth.example.com",
    });
    expect(csp).toContain("script-src 'self' 'nonce-abc123' 'strict-dynamic'");
    expect(csp).not.toContain("unsafe-eval");
    expect(csp).not.toMatch(/script-src[^;]*'unsafe-inline'/);
    expect(csp).toContain("connect-src 'self' https://api.example.com https://auth.example.com");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("upgrade-insecure-requests");
  });

  it("allows eval and websockets only in development (hot reload)", () => {
    const csp = contentSecurityPolicy("n", { dev: true });
    expect(csp).toContain("'unsafe-eval'");
    expect(csp).toContain("connect-src 'self' ws:");
    expect(csp).not.toContain("upgrade-insecure-requests");
  });
});
