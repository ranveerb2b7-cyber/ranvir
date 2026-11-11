"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AuthCard } from "@/components/layout/auth-card";
import { Alert, Button, Field, Input } from "@/components/ui/form";
import { supabaseBrowser } from "@/lib/supabase/client";

const MIN_PASSWORD_LENGTH = 10;

/** Reached from the reset email via /auth/callback, which establishes a recovery session. */
export default function ResetPasswordPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password"));
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Use at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    if (password !== String(form.get("confirm"))) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    setError(null);
    const supabase = supabaseBrowser();
    const { error: updateError } = await supabase.auth.updateUser({ password });
    if (updateError) {
      setBusy(false);
      setError(updateError.message);
      return;
    }
    await supabase.auth.signOut();
    router.replace("/login?reset=1");
  }

  return (
    <AuthCard title="Choose a new password">
      <form onSubmit={onSubmit} className="space-y-4">
        {error && <Alert>{error}</Alert>}
        <Field label="New password" htmlFor="password" hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}>
          <Input id="password" name="password" type="password" autoComplete="new-password" required />
        </Field>
        <Field label="Confirm password" htmlFor="confirm">
          <Input id="confirm" name="confirm" type="password" autoComplete="new-password" required />
        </Field>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Saving…" : "Update password"}
        </Button>
      </form>
    </AuthCard>
  );
}
