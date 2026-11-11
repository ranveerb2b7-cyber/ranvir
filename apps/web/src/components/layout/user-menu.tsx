"use client";

import { LogOut } from "lucide-react";

import { useSession } from "@/components/session/session-provider";
import { ROLE_LABELS } from "@/lib/types";

export function UserMenu() {
  const { me, org, signOut } = useSession();
  return (
    <div className="flex items-center justify-between gap-2 border-t border-[var(--border)] p-3">
      <div className="min-w-0">
        <div className="truncate text-sm font-medium" title={me.email}>
          {me.full_name ?? me.email}
        </div>
        <div className="text-xs text-[var(--text-muted)]">{ROLE_LABELS[org.role]}</div>
      </div>
      <button
        type="button"
        onClick={() => void signOut()}
        aria-label="Sign out"
        title="Sign out"
        className="rounded-md p-2 text-[var(--text-muted)] hover:bg-black/5 hover:text-[var(--text)] dark:hover:bg-white/5"
      >
        <LogOut className="size-4" />
      </button>
    </div>
  );
}
