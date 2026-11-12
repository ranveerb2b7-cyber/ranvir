export interface MetricTileProps {
  label: string;
  /** null means the value is not available; it is never rendered as 0. */
  value: number | null;
  unavailableReason?: string;
  /** Extra context for a known value (e.g. what it excludes). */
  note?: string;
}

export function MetricTile({ label, value, unavailableReason, note }: MetricTileProps) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="text-sm text-[var(--text-muted)]">{label}</div>
      {value === null ? (
        <div className="mt-2">
          <div className="text-lg font-semibold text-[var(--text-muted)]">Not available</div>
          {unavailableReason && (
            <div className="mt-1 text-xs text-[var(--text-muted)]">{unavailableReason}</div>
          )}
        </div>
      ) : (
        <div className="mt-2">
          <div className="text-3xl font-semibold tabular-nums">{value.toLocaleString("en-IN")}</div>
          {note && <div className="mt-1 text-xs text-[var(--text-muted)]">{note}</div>}
        </div>
      )}
    </div>
  );
}
