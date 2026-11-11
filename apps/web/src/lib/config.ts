/**
 * Public (browser-visible) configuration. Only NEXT_PUBLIC_* values belong here; they are
 * inlined at build time. Never put secrets in NEXT_PUBLIC_* variables.
 */
function required(name: string, value: string | undefined): string {
  if (!value) throw new Error(`Missing environment variable ${name}`);
  return value;
}

export const publicConfig = {
  get supabaseUrl() {
    return required("NEXT_PUBLIC_SUPABASE_URL", process.env.NEXT_PUBLIC_SUPABASE_URL);
  },
  get supabaseAnonKey() {
    return required("NEXT_PUBLIC_SUPABASE_ANON_KEY", process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY);
  },
  get apiUrl() {
    return required("NEXT_PUBLIC_API_URL", process.env.NEXT_PUBLIC_API_URL);
  },
};
