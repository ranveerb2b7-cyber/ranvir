import { createHash } from "node:crypto";

import { describe, expect, it } from "vitest";

import { challengeFor, newVerifier } from "../src/lib/pkce";

describe("PKCE", () => {
  it("creates a random RFC 7636 verifier and its S256 challenge", async () => {
    const verifier = newVerifier();
    expect(verifier).toMatch(/^[A-Za-z0-9_-]{43,128}$/);
    expect(newVerifier()).not.toBe(verifier);
    const expected = createHash("sha256").update(verifier).digest("base64url");
    expect(await challengeFor(verifier)).toBe(expected);
  });
});
