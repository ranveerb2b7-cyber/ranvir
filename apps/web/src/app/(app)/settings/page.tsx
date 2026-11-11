"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { useSession } from "@/components/session/session-provider";
import { Alert, Button, errorMessage, Field, Input } from "@/components/ui/form";
import { api } from "@/lib/api";

export default function SettingsPage() {
  const router = useRouter();
  const { me, org, can, refresh } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>, success: string) {
    setError(null);
    setNotice(null);
    try {
      await action();
      setNotice(success);
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fullName = String(new FormData(event.currentTarget).get("full_name")).trim();
    void run(
      () => api("/me", { method: "PATCH", body: { full_name: fullName || null } }),
      "Profile saved.",
    );
  }

  function saveOrg(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget).get("org_name")).trim();
    void run(
      () => api("/organizations/current", { method: "PATCH", orgId: org.id, body: { name } }),
      "Organization renamed.",
    );
  }

  async function leave() {
    if (!window.confirm(`Leave ${org.name}? You will lose access to its data.`)) return;
    try {
      await api("/members/me", { method: "DELETE", orgId: org.id });
      await refresh();
      router.replace("/dashboard");
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function deleteOrg() {
    const typed = window.prompt(`Type the organization name to delete it: ${org.name}`);
    if (typed !== org.name) return;
    try {
      await api("/organizations/current", { method: "DELETE", orgId: org.id });
      await refresh();
      router.replace("/dashboard");
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <section className="max-w-2xl space-y-8">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
      {error && <Alert>{error}</Alert>}
      {notice && <Alert tone="success">{notice}</Alert>}

      <form onSubmit={saveProfile} className="space-y-4 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
        <h2 className="font-semibold">Your profile</h2>
        <Field label="Email" htmlFor="email" hint="Managed by your sign-in account.">
          <Input id="email" value={me.email} disabled readOnly />
        </Field>
        <Field label="Full name" htmlFor="full_name">
          <Input id="full_name" name="full_name" defaultValue={me.full_name ?? ""} maxLength={120} />
        </Field>
        <Button type="submit">Save profile</Button>
      </form>

      <form onSubmit={saveOrg} className="space-y-4 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
        <h2 className="font-semibold">Organization</h2>
        <Field label="Name" htmlFor="org_name">
          <Input
            id="org_name"
            name="org_name"
            defaultValue={org.name}
            minLength={2}
            maxLength={80}
            required
            disabled={!can("org.manage")}
          />
        </Field>
        {can("org.manage") ? (
          <Button type="submit">Rename</Button>
        ) : (
          <p className="text-xs text-[var(--text-muted)]">Only owners and admins can rename the organization.</p>
        )}
      </form>

      <div className="space-y-3 rounded-lg border border-red-300 p-4 dark:border-red-900">
        <h2 className="font-semibold text-red-700 dark:text-red-400">Danger zone</h2>
        {org.role === "owner" ? (
          <>
            <p className="text-sm text-[var(--text-muted)]">
              To leave, first transfer ownership to another member. Deleting the organization removes access for everyone.
            </p>
            <Button variant="danger" onClick={() => void deleteOrg()}>
              Delete organization
            </Button>
          </>
        ) : (
          <Button variant="danger" onClick={() => void leave()}>
            Leave organization
          </Button>
        )}
      </div>
    </section>
  );
}
