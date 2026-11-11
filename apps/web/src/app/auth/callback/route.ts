import { NextResponse, type NextRequest } from "next/server";

import { safeNext } from "@/lib/routes";
import { supabaseServer } from "@/lib/supabase/server";

/**
 * Landing point for links in auth emails (sign-up confirmation, password recovery).
 * Exchanges the one-time PKCE code for a session cookie, then continues to `next`.
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = request.nextUrl;
  const code = searchParams.get("code");
  const next = safeNext(searchParams.get("next"));

  if (code) {
    const supabase = await supabaseServer();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) return NextResponse.redirect(new URL(next, origin));
  }
  return NextResponse.redirect(new URL("/login?error=link_invalid", origin));
}
