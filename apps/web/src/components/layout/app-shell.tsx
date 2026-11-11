"use client";

import { Menu, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Sidebar } from "./sidebar";

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
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
        className={`${open ? "block" : "hidden"} border-b border-[var(--border)] bg-[var(--surface)] lg:sticky lg:top-0 lg:block lg:h-dvh lg:border-r lg:border-b-0`}
      >
        <div className="hidden h-14 items-center px-6 font-semibold lg:flex">SellerScope</div>
        <div onClick={() => setOpen(false)}>
          <Sidebar />
        </div>
      </aside>
      <main className="min-w-0 px-4 py-6 sm:px-8">{children}</main>
    </div>
  );
}
