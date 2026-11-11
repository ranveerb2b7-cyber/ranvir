"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { useSession } from "@/components/session/session-provider";
import { Alert, Button, errorMessage, Field, Input, Select } from "@/components/ui/form";
import { api } from "@/lib/api";
import {
  ROLE_LABELS,
  type AssignableRole,
  type Invitation,
  type InvitationSent,
  type Member,
} from "@/lib/types";

const ASSIGNABLE: AssignableRole[] = ["admin", "analyst", "viewer"];
const dateFmt = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium" });

export default function TeamPage() {
  const { org, me, can, refresh } = useSession();
  const manage = can("members.manage");
  const queryClient = useQueryClient();
  const membersQuery = useQuery({
    queryKey: ["tenant", org.id, "members"],
    queryFn: () => api<Member[]>("/members", { orgId: org.id }),
  });
  const invitesQuery = useQuery({
    queryKey: ["tenant", org.id, "invitations"],
    queryFn: () => api<Invitation[]>("/invitations", { orgId: org.id }),
  });
  const members = membersQuery.data ?? null;
  const invites = invitesQuery.data ?? [];
  const [actionError, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const error = actionError ?? (membersQuery.error ?? invitesQuery.error)?.message ?? null;

  async function run(action: () => Promise<unknown>, success?: string) {
    setError(null);
    setNotice(null);
    try {
      await action();
      if (success) setNotice(success);
      await queryClient.invalidateQueries({ queryKey: ["tenant", org.id] });
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formEl = event.currentTarget;
    const form = new FormData(formEl);
    await run(async () => {
      const sent = await api<InvitationSent>("/invitations", {
        method: "POST",
        orgId: org.id,
        body: { email: String(form.get("email")), role: String(form.get("role")) },
      });
      formEl.reset();
      setNotice(
        sent.email_sent
          ? `Invitation sent to ${sent.email}.`
          : `Invitation created for ${sent.email}, but the email could not be delivered. Use "Resend".`,
      );
    });
  }

  return (
    <section className="max-w-4xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Team Management</h1>
        <p className="mt-1 text-sm text-[var(--text-muted)]">People with access to {org.name}.</p>
      </div>

      {error && <Alert>{error}</Alert>}
      {notice && <Alert tone="success">{notice}</Alert>}

      {manage && (
        <form onSubmit={invite} className="grid gap-4 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 sm:grid-cols-[1fr_160px_auto] sm:items-end">
          <Field label="Invite by email" htmlFor="invite-email">
            <Input id="invite-email" name="email" type="email" required placeholder="colleague@company.com" />
          </Field>
          <Field label="Role" htmlFor="invite-role">
            <Select id="invite-role" name="role" defaultValue="analyst">
              {ASSIGNABLE.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABELS[r]}
                </option>
              ))}
            </Select>
          </Field>
          <Button type="submit">Send invite</Button>
        </form>
      )}

      <div className="overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--surface)]">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-[var(--border)] text-[var(--text-muted)]">
            <tr>
              <th className="px-4 py-2 font-medium">Member</th>
              <th className="px-4 py-2 font-medium">Role</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Joined</th>
              {manage && <th className="px-4 py-2" />}
            </tr>
          </thead>
          <tbody>
            {members === null && (
              <tr>
                <td className="px-4 py-3 text-[var(--text-muted)]" colSpan={5}>
                  Loading…
                </td>
              </tr>
            )}
            {members?.map((m) => {
              const editable = manage && m.role !== "owner" && m.user_id !== me.id;
              return (
                <tr key={m.user_id} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-4 py-3">
                    <div className="font-medium">{m.full_name ?? m.email}</div>
                    {m.full_name && <div className="text-xs text-[var(--text-muted)]">{m.email}</div>}
                  </td>
                  <td className="px-4 py-3">
                    {editable ? (
                      <Select
                        aria-label={`Role for ${m.email}`}
                        value={m.role}
                        onChange={(e) =>
                          void run(
                            () =>
                              api(`/members/${m.user_id}`, {
                                method: "PATCH",
                                orgId: org.id,
                                body: { role: e.target.value },
                              }),
                            `Updated ${m.email}.`,
                          )
                        }
                        className="w-32! min-w-32"
                      >
                        {ASSIGNABLE.map((r) => (
                          <option key={r} value={r}>
                            {ROLE_LABELS[r]}
                          </option>
                        ))}
                      </Select>
                    ) : (
                      ROLE_LABELS[m.role]
                    )}
                  </td>
                  <td className="px-4 py-3 capitalize">{m.status}</td>
                  <td className="px-4 py-3">{dateFmt.format(new Date(m.joined_at))}</td>
                  {manage && (
                    <td className="space-x-2 px-4 py-3 text-right whitespace-nowrap">
                      {org.role === "owner" && editable && m.status === "active" && (
                        <Button
                          variant="secondary"
                          onClick={() => {
                            if (window.confirm(`Make ${m.email} the owner? You will become an admin.`)) {
                              void run(async () => {
                                await api("/organizations/current/transfer-ownership", {
                                  method: "POST",
                                  orgId: org.id,
                                  body: { user_id: m.user_id },
                                });
                                await refresh();
                              }, `${m.email} is now the owner.`);
                            }
                          }}
                        >
                          Make owner
                        </Button>
                      )}
                      {editable && (
                        <Button
                          variant="secondary"
                          onClick={() => {
                            if (window.confirm(`Remove ${m.email} from ${org.name}?`)) {
                              void run(
                                () => api(`/members/${m.user_id}`, { method: "DELETE", orgId: org.id }),
                                `Removed ${m.email}.`,
                              );
                            }
                          }}
                        >
                          Remove
                        </Button>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div>
        <h2 className="text-lg font-semibold">Pending invitations</h2>
        {invites.length === 0 ? (
          <p className="mt-2 text-sm text-[var(--text-muted)]">No pending invitations.</p>
        ) : (
          <ul className="mt-3 divide-y divide-[var(--border)] rounded-lg border border-[var(--border)] bg-[var(--surface)]">
            {invites.map((i) => (
              <li key={i.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm">
                <div>
                  <div className="font-medium">{i.email}</div>
                  <div className="text-xs text-[var(--text-muted)]">
                    {ROLE_LABELS[i.role]} · expires {dateFmt.format(new Date(i.expires_at))}
                  </div>
                </div>
                {manage && (
                  <div className="flex gap-2">
                    <Button
                      variant="secondary"
                      onClick={() =>
                        void run(
                          () => api(`/invitations/${i.id}/resend`, { method: "POST", orgId: org.id }),
                          `Invitation resent to ${i.email}.`,
                        )
                      }
                    >
                      Resend
                    </Button>
                    <Button
                      variant="secondary"
                      onClick={() =>
                        void run(
                          () => api(`/invitations/${i.id}`, { method: "DELETE", orgId: org.id }),
                          `Invitation to ${i.email} cancelled.`,
                        )
                      }
                    >
                      Cancel
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
