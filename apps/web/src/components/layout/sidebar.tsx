"use client";

import clsx from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV_ITEMS } from "@/lib/navigation";

export function Sidebar() {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="flex flex-col gap-1 p-3">
      {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={clsx(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
              active
                ? "bg-brand-50 text-brand-700 dark:bg-brand-700/20 dark:text-brand-100"
                : "text-[var(--text-muted)] hover:bg-black/5 hover:text-[var(--text)] dark:hover:bg-white/5",
            )}
          >
            <Icon aria-hidden className="size-4 shrink-0" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
