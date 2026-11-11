import { isPublicPath, safeNext } from "@/lib/routes";

describe("safeNext (open-redirect protection)", () => {
  it.each([
    ["/team", "/team"],
    ["/accept-invite?token=abc", "/accept-invite?token=abc"],
    [null, "/dashboard"],
    ["", "/dashboard"],
    ["https://evil.example", "/dashboard"],
    ["//evil.example", "/dashboard"],
    ["/\\evil.example", "/dashboard"],
    ["javascript:alert(1)", "/dashboard"],
  ])("%s -> %s", (input, expected) => {
    expect(safeNext(input)).toBe(expected);
  });
});

describe("isPublicPath", () => {
  it("allows auth pages without a session", () => {
    expect(isPublicPath("/login")).toBe(true);
    expect(isPublicPath("/auth/callback")).toBe(true);
  });
  it("protects app pages and invitation acceptance", () => {
    expect(isPublicPath("/dashboard")).toBe(false);
    expect(isPublicPath("/team")).toBe(false);
    expect(isPublicPath("/accept-invite")).toBe(false);
    expect(isPublicPath("/login-evil")).toBe(false);
  });
});
