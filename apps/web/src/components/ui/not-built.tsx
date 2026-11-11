import { Construction } from "lucide-react";

/** Honest placeholder for screens whose milestone has not been delivered yet. */
export function NotBuilt({ title, milestone }: { title: string; milestone: string }) {
  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <div className="mt-6 flex items-start gap-3 rounded-lg border border-dashed border-[var(--border)] bg-[var(--surface)] p-6 text-sm text-[var(--text-muted)]">
        <Construction aria-hidden className="mt-0.5 size-5 shrink-0" />
        <p>
          This screen is not built yet. It is scheduled for milestone <strong>{milestone}</strong>.
          No data is shown here until it is backed by real scans.
        </p>
      </div>
    </section>
  );
}
