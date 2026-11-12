import { NOT_AVAILABLE } from "@/lib/format";

/** Renders a formatted value, or an explicit "Not available" (never 0 or blank) when unknown. */
export function Value({ children, why }: { children: string | null; why?: string }) {
  if (children === null) {
    return (
      <span className="text-xs text-[var(--text-muted)]" title={why}>
        {NOT_AVAILABLE}
      </span>
    );
  }
  return <span className="tabular-nums">{children}</span>;
}
