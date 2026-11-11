"use client";

import { Menu, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { SessionProvider } from "@/components/session/session-provider";

import { OrgSwitcher } from "./org-switcher";
import { Sidebar } from "./sidebar";
import { UserMenu } from "./user-menu";

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <SessionProvider>
      <div className="min-h-dvh lg:grid lg:grid-cols-[240px_1fr]">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-[var(--border)] bg-[var(--surface)] px-4 lg:hidden">
          <span className="font-semibold">SellerScope</span>
          <button
            type="button"
            aria-label={open ? "Close navigation" : "Open navigation"}
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
            className="rounded-md p-2 hover:bg-black/5 dark:hover:bg-white/5"
          >
            {open ? <X className="size-5" /> : <Menu className="size-5" />}
          </button>
        </header>
        <aside
          className={`${open ? "flex" : "hidden"} flex-col border-b border-[var(--border)] bg-[var(--surface)] lg:sticky lg:top-0 lg:flex lg:h-dvh lg:border-r lg:border-b-0`}
        >
          <div className="hidden h-14 items-center px-6 font-semibold lg:flex">SellerScope</div>
          <div className="px-3 pt-3 lg:pt-0">
            <OrgSwitcher />
          </div>
          <div className="flex-1 overflow-y-auto" onClick={() => setOpen(false)}>
            <Sidebar />
          </div>
          <UserMenu />
        </aside>
        <main className="min-w-0 px-4 py-6 sm:px-8">{children}</main>
      </div>
    </SessionProvider>
  );
}
