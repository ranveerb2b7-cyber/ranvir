"use client";

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import { AuthCard } from "@/components/layout/auth-card";
import { Alert, Button, Field, Input } from "@/components/ui/form";
import { safeNext } from "@/lib/routes";
import { supabaseBrowser } from "@/lib/supabase/client";

function LoginForm() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    const { error: signInError } = await supabaseBrowser().auth.signInWithPassword({
      email: String(form.get("email")),
      password: String(form.get("password")),
    });
    setBusy(false);
    if (signInError) {
      setError(signInError.message);
      return;
    }
    queryClient.clear(); // never show a previous user's cached data
    router.replace(next);
    router.refresh();
  }

  return (
    <AuthCard
      title="Sign in"
      subtitle="Monitor your sellers on Amazon.in"
      footer={
        <>
          New to SellerScope?{" "}
          <Link className="font-medium text-brand-600" href={`/register?next=${encodeURIComponent(next)}`}>
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4">
        {params.get("reset") === "1" && <Alert tone="success">Password updated. Sign in with your new password.</Alert>}
        {params.get("error") === "link_invalid" && (
          <Alert>That link is invalid or has expired. Please request a new one.</Alert>
        )}
        {error && <Alert>{error}</Alert>}
        <Field label="Email" htmlFor="email">
          <Input id="email" name="email" type="email" autoComplete="email" required />
        </Field>
        <Field label="Password" htmlFor="password">
          <Input id="password" name="password" type="password" autoComplete="current-password" required />
        </Field>
        <div className="flex items-center justify-between">
          <Link href="/forgot-password" className="text-sm text-brand-600">
            Forgot password?
          </Link>
          <Button type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </div>
      </form>
    </AuthCard>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
