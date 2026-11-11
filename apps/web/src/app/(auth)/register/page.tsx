"use client";

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import { AuthCard } from "@/components/layout/auth-card";
import { Alert, Button, Field, Input } from "@/components/ui/form";
import { safeNext } from "@/lib/routes";
import { supabaseBrowser } from "@/lib/supabase/client";

const MIN_PASSWORD_LENGTH = 10;

function RegisterForm() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const params = useSearchParams();
  const next = safeNext(params.get("next"), "/onboarding");
  const [error, setError] = useState<string | null>(null);
  const [checkEmail, setCheckEmail] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password"));
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Use at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    setBusy(true);
    setError(null);
    const { data, error: signUpError } = await supabaseBrowser().auth.signUp({
      email: String(form.get("email")),
      password,
      options: {
        emailRedirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`,
      },
    });
    setBusy(false);
    if (signUpError) {
      setError(signUpError.message);
      return;
    }
    if (data.session) {
      // Email confirmation disabled (local development): signed in immediately.
      queryClient.clear(); // never show a previous user's cached data
      router.replace(next);
      router.refresh();
    } else {
      setCheckEmail(true);
    }
  }

  if (checkEmail) {
    return (
      <AuthCard title="Check your email" subtitle="We sent you a confirmation link.">
        <p className="text-sm text-[var(--text-muted)]">
          Open the link in the email to activate your account, then continue here.
        </p>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Create your account"
      footer={
        <>
          Already have an account?{" "}
          <Link className="font-medium text-brand-600" href={`/login?next=${encodeURIComponent(next)}`}>
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4">
        {error && <Alert>{error}</Alert>}
        <Field label="Work email" htmlFor="email">
          <Input id="email" name="email" type="email" autoComplete="email" required />
        </Field>
        <Field label="Password" htmlFor="password" hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}>
          <Input
            id="password"
            name="password"
            type="password"
            autoComplete="new-password"
            minLength={MIN_PASSWORD_LENGTH}
            required
          />
        </Field>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </AuthCard>
  );
}

export default function RegisterPage() {
  return (
    <Suspense>
      <RegisterForm />
    </Suspense>
  );
}
