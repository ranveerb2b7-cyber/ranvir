import clsx from "clsx";

import { formatCount } from "@/lib/format";
import { ITEM_STATUS_LABELS, JOB_STATUS_LABELS, type ItemStatus, type JobStatus, type ScanJob } from "@/lib/types";

const JOB_STYLE: Record<JobStatus, string> = {
  queued: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  running: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  completed: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
  completed_with_errors: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  cancelled: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
};

const ITEM_STYLE: Record<ItemStatus, string> = {
  pending: "text-[var(--text-muted)]",
  processing: "text-blue-700 dark:text-blue-300",
  completed: "text-green-700 dark:text-green-400",
  partial: "text-amber-700 dark:text-amber-400",
  unavailable: "text-amber-700 dark:text-amber-400",
  failed: "text-red-700 dark:text-red-400",
  cancelled: "text-[var(--text-muted)]",
};

export function JobStatusBadge({ status }: { status: JobStatus }) {
  return (
    <span className={clsx("inline-block rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap", JOB_STYLE[status])}>
      {JOB_STATUS_LABELS[status]}
    </span>
  );
}

export function ItemStatusText({ status }: { status: ItemStatus }) {
  return <span className={clsx("text-xs font-medium", ITEM_STYLE[status])}>{ITEM_STATUS_LABELS[status]}</span>;
}

export function finishedCount(job: ScanJob): number {
  return job.completed_items + job.failed_items + job.unavailable_items + job.cancelled_items;
}

export function JobProgress({ job }: { job: ScanJob }) {
  const done = finishedCount(job);
  const pct = job.total_items ? Math.round((done / job.total_items) * 100) : 0;
  return (
    <div className="min-w-32">
      <div
        role="progressbar"
        aria-label="Scan progress"
        aria-valuemin={0}
        aria-valuemax={job.total_items}
        aria-valuenow={done}
        className="h-1.5 overflow-hidden rounded-full bg-black/10 dark:bg-white/10"
      >
        <div className="bg-brand-600 h-full transition-all" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-1 text-xs text-[var(--text-muted)] tabular-nums">
        {formatCount(done)} of {formatCount(job.total_items)}
      </div>
    </div>
  );
}
