"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useSession } from "@/components/session/session-provider";
import { api } from "@/lib/api";
import { NAV_ITEMS } from "@/lib/navigation";
import type { AlertSummary } from "@/lib/types";

export function Sidebar() {
  const pathname = usePathname();
  const { org } = useSession();
  const alerts = useQuery({
    queryKey: ["tenant", org.id, "alerts", "summary"],
    queryFn: () => api<AlertSummary>("/alerts/summary", { orgId: org.id }),
    refetchInterval: 60_000,
  });
  const openAlerts = alerts.data?.open ?? 0;
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
            {href === "/alerts" && openAlerts > 0 && (
              <span className="ml-auto rounded-full bg-red-600 px-1.5 text-xs font-semibold text-white tabular-nums">
                {openAlerts > 99 ? "99+" : openAlerts}
                <span className="sr-only"> open alerts</span>
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}
