// TEST-ONLY stand-in for Supabase Auth (GoTrue), used by the local end-to-end run.
// Implements just the endpoints supabase-js calls in our flows, with auto-confirmed sign-up.
// It is NOT a substitute for verifying against real Supabase Auth.
//
// Usage: STUB_JWT_SECRET=... STUB_PORT=9999 node e2e/stub-auth.mjs
import { createHmac, randomBytes, randomUUID } from "node:crypto";
import { createServer } from "node:http";

const PORT = Number(process.env.STUB_PORT ?? 9999);
const SECRET = process.env.STUB_JWT_SECRET;
if (!SECRET) throw new Error("STUB_JWT_SECRET is required");
const ISSUER = `http://127.0.0.1:${PORT}/auth/v1`;

const users = new Map(); // email -> { user, password }
const refreshTokens = new Map(); // refresh token -> email

const b64url = (data) => Buffer.from(data).toString("base64url");

function sign(user) {
  const now = Math.floor(Date.now() / 1000);
  const header = b64url(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const payload = b64url(
    JSON.stringify({
      sub: user.id,
      email: user.email,
      aud: "authenticated",
      role: "authenticated",
      iss: ISSUER,
      iat: now,
      exp: now + 3600,
      is_anonymous: false,
    }),
  );
  const signature = createHmac("sha256", SECRET).update(`${header}.${payload}`).digest("base64url");
  return `${header}.${payload}.${signature}`;
}

function verify(token) {
  const [header, payload, signature] = (token ?? "").split(".");
  if (!signature) return null;
  const expected = createHmac("sha256", SECRET).update(`${header}.${payload}`).digest("base64url");
  if (expected !== signature) return null;
  const claims = JSON.parse(Buffer.from(payload, "base64url").toString());
  if (claims.exp < Date.now() / 1000) return null;
  return users.get(claims.email)?.user ?? null;
}

function session(user) {
  const refresh = randomBytes(16).toString("hex");
  refreshTokens.set(refresh, user.email);
  return {
    access_token: sign(user),
    token_type: "bearer",
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    refresh_token: refresh,
    user,
  };
}

function send(res, status, body, origin) {
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": origin ?? "*",
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info, x-supabase-api-version",
    "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
  });
  res.end(body === undefined ? "" : JSON.stringify(body));
}

const error = (res, status, msg, origin) =>
  send(res, status, { code: status, error_code: "stub_error", msg, message: msg }, origin);

createServer(async (req, res) => {
  const origin = req.headers.origin;
  if (req.method === "OPTIONS") return send(res, 204, undefined, origin);
  const url = new URL(req.url, `http://127.0.0.1:${PORT}`);
  const path = url.pathname.replace(/^\/auth\/v1/, "");
  let body = {};
  if (req.method === "POST" || req.method === "PUT") {
    const chunks = [];
    for await (const c of req) chunks.push(c);
    body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString() || "{}") : {};
  }
  const bearer = (req.headers.authorization ?? "").replace(/^Bearer /i, "");

  if (path === "/signup" && req.method === "POST") {
    const email = String(body.email).toLowerCase();
    if (users.has(email)) return error(res, 422, "User already registered", origin);
    const now = new Date().toISOString();
    const user = {
      id: randomUUID(),
      aud: "authenticated",
      role: "authenticated",
      email,
      email_confirmed_at: now,
      app_metadata: { provider: "email" },
      user_metadata: {},
      identities: [],
      created_at: now,
      updated_at: now,
    };
    users.set(email, { user, password: body.password });
    return send(res, 200, session(user), origin);
  }
  if (path === "/token" && url.searchParams.get("grant_type") === "password") {
    const record = users.get(String(body.email).toLowerCase());
    if (!record || record.password !== body.password) return error(res, 400, "Invalid login credentials", origin);
    return send(res, 200, session(record.user), origin);
  }
  if (path === "/token" && url.searchParams.get("grant_type") === "refresh_token") {
    const email = refreshTokens.get(body.refresh_token);
    if (!email) return error(res, 400, "Invalid Refresh Token", origin);
    refreshTokens.delete(body.refresh_token);
    return send(res, 200, session(users.get(email).user), origin);
  }
  if (path === "/user" && req.method === "GET") {
    const user = verify(bearer);
    return user ? send(res, 200, user, origin) : error(res, 401, "invalid JWT", origin);
  }
  if (path === "/user" && req.method === "PUT") {
    const user = verify(bearer);
    if (!user) return error(res, 401, "invalid JWT", origin);
    if (body.password) users.get(user.email).password = body.password;
    return send(res, 200, user, origin);
  }
  if (path === "/recover" && req.method === "POST") return send(res, 200, {}, origin);
  if (path === "/logout") return send(res, 204, undefined, origin);
  return error(res, 404, `stub: ${req.method} ${path} not implemented`, origin);
}).listen(PORT, "127.0.0.1", () => console.log(`stub auth on ${ISSUER}`));
