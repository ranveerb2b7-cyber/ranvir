"use client";

import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";

import { publicConfig } from "@/lib/config";

let client: SupabaseClient | undefined;

/** Browser Supabase client (auth only). The session lives in cookies managed by @supabase/ssr. */
export function supabaseBrowser(): SupabaseClient {
  client ??= createBrowserClient(publicConfig.supabaseUrl, publicConfig.supabaseAnonKey);
  return client;
}
