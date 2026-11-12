import clsx from "clsx";
import { AlertOctagon, AlertTriangle, Info } from "lucide-react";

import { SEVERITY_LABELS } from "@/lib/alerts";
import type { AlertSeverity } from "@/lib/types";

const STYLE: Record<AlertSeverity, string> = {
  critical: "border-red-300 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200",
  warning: "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200",
  info: "border-[var(--border)] bg-[var(--surface)] text-[var(--text-muted)]",
};

const ICON = { critical: AlertOctagon, warning: AlertTriangle, info: Info } as const;

/** Severity is always shown as icon + text, never color alone. */
export function SeverityBadge({ severity }: { severity: AlertSeverity }) {
  const Icon = ICON[severity];
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium", STYLE[severity])}>
      <Icon aria-hidden className="size-3" />
      {SEVERITY_LABELS[severity]}
    </span>
  );
}
