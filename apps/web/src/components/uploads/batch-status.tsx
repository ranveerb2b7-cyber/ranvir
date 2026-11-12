import clsx from "clsx";

import { BATCH_STATUS_LABELS, type BatchStatus } from "@/lib/types";

const STYLE: Record<BatchStatus, string> = {
  uploaded: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  parsing: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  preview_ready: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  committed: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  discarded: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
};

export function BatchStatusBadge({ status }: { status: BatchStatus }) {
  return (
    <span className={clsx("inline-block rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap", STYLE[status])}>
      {BATCH_STATUS_LABELS[status]}
    </span>
  );
}
