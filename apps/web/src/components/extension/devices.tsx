"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, errorMessage } from "@/components/ui/form";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { ExtensionDevice } from "@/lib/types";

/** Browsers connected through the SellerScope extension, with revoke. */
export function ExtensionDevices({ orgId, seesAll }: { orgId: string; seesAll: boolean }) {
  const queryClient = useQueryClient();
  const devices = useQuery({
    queryKey: ["tenant", orgId, "extension-tokens"],
    queryFn: () => api<ExtensionDevice[]>("/extension/tokens", { orgId }),
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api(`/extension/tokens/${id}`, { method: "DELETE", orgId }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tenant", orgId, "extension-tokens"] }),
  });
  const [now] = useState(() => Date.now());
  const active = (devices.data ?? []).filter((d) => !d.revoked_at && new Date(d.expires_at).getTime() > now);

  return (
    <div className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
      <h2 className="font-semibold">Browser extension</h2>
      <p className="text-sm text-[var(--text-muted)]">
        The SellerScope Chrome extension shows your stored data for the Amazon.in product you&apos;re viewing. Connect it
        from the extension&apos;s &quot;Connect&quot; button. Connections expire after 90 days.
        {seesAll ? " As an admin you see everyone's connections." : ""}
      </p>
      {(devices.error ?? revoke.error) && <Alert>{errorMessage(devices.error ?? revoke.error)}</Alert>}
      {devices.data && active.length === 0 && <p className="text-sm text-[var(--text-muted)]">No connected browsers.</p>}
      {active.length > 0 && (
        <ul className="divide-y divide-[var(--border)] text-sm" aria-label="Connected browsers">
          {active.map((d) => (
            <li key={d.id} className="flex items-center justify-between gap-3 py-2">
              <div className="min-w-0">
                <div className="font-medium">{d.name ?? "Browser extension"}</div>
                <div className="text-xs text-[var(--text-muted)]">
                  {seesAll && `${d.user_email ?? "Former member"} · `}
                  Connected {formatDateTime(d.created_at)} · last used {formatDateTime(d.last_used_at) ?? "never"} · expires{" "}
                  {formatDateTime(d.expires_at)}
                </div>
              </div>
              <button
                type="button"
                className="shrink-0 text-xs text-red-700 hover:underline dark:text-red-300"
                onClick={() => revoke.mutate(d.id)}
                disabled={revoke.isPending}
              >
                Disconnect
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
