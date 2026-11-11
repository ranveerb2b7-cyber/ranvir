"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AuthCard } from "@/components/layout/auth-card";
import { rememberOrg } from "@/components/session/session-provider";
import { Alert, Button, errorMessage, Field, Input } from "@/components/ui/form";
import { api } from "@/lib/api";
import type { Organization } from "@/lib/types";

/** First step after sign-up for users who are not yet in any organization. */
export default function OnboardingPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget).get("name")).trim();
    setBusy(true);
    setError(null);
    try {
      const org = await api<Organization>("/organizations", { method: "POST", body: { name } });
      rememberOrg(org.id);
      // Memberships changed: drop the cached "no organizations" answer.
      queryClient.removeQueries();
      router.replace("/dashboard");
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="Create your organization"
      subtitle="Your brand or company. You can invite your team next."
      footer="Were you invited? Open the link in your invitation email instead."
    >
      <form onSubmit={onSubmit} className="space-y-4">
        {error && <Alert>{error}</Alert>}
        <Field label="Organization name" htmlFor="name">
          <Input id="name" name="name" minLength={2} maxLength={80} required placeholder="Acme Brands Pvt Ltd" />
        </Field>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Creating…" : "Create organization"}
        </Button>
      </form>
    </AuthCard>
  );
}
