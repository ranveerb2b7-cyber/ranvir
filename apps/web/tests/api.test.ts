import { parseProblem } from "@/lib/api";

describe("parseProblem", () => {
  it("reads RFC 9457 problem details", async () => {
    const res = new Response(
      JSON.stringify({ title: "Forbidden", status: 403, code: "forbidden", detail: "Your role (viewer) does not allow members.manage" }),
      { status: 403 },
    );
    expect(await parseProblem(res)).toMatchObject({
      status: 403,
      code: "forbidden",
      detail: "Your role (viewer) does not allow members.manage",
    });
  });

  it("joins validation messages when there is no detail", async () => {
    const res = new Response(
      JSON.stringify({ title: "Request validation failed", status: 422, code: "validation_error", errors: [{ loc: ["body", "email"], msg: "invalid email" }] }),
      { status: 422 },
    );
    expect((await parseProblem(res)).detail).toBe("invalid email");
  });

  it("survives non-JSON error bodies", async () => {
    const res = new Response("<html>Bad gateway</html>", { status: 502, statusText: "Bad Gateway" });
    expect(await parseProblem(res)).toEqual({ title: "Bad Gateway", status: 502, code: "http_error" });
  });
});
