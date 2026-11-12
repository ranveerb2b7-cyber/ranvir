"use client";

import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { NOT_AVAILABLE } from "@/lib/format";

export interface TrendSeries {
  key: string;
  label: string;
  /** CSS variable name of a validated categorical slot, in fixed order. */
  color: "--series-1" | "--series-2" | "--series-3";
}

type Row = Record<string, number | string | null>;

const dateFmt = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" });
const dateTimeFmt = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" });

/**
 * Line chart over scan time. Unknown values are null and render as GAPS (never as 0).
 * One y-axis only; a table view is always available (accessibility + exact values).
 */
export function TrendChart({
  title,
  data,
  series,
  format,
  zeroBaseline = true,
}: {
  /** Counts start at zero; prices use a fitted range so movement stays visible. */
  zeroBaseline?: boolean;
  title: string;
  data: Row[];
  series: TrendSeries[];
  format: (v: number) => string;
}) {
  const [asTable, setAsTable] = useState(false);
  const color = (s: TrendSeries) => `var(${s.color})`;

  return (
    <figure className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <figcaption className="text-sm font-medium">{title}</figcaption>
        <button type="button" className="text-brand-600 text-xs hover:underline" onClick={() => setAsTable((v) => !v)}>
          {asTable ? "Show chart" : "Show as table"}
        </button>
      </div>
      {data.length < 2 && !asTable ? (
        <p className="py-8 text-center text-sm text-[var(--text-muted)]">
          A trend appears after at least two successful scans.
        </p>
      ) : asTable ? (
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-[var(--surface)] text-[var(--text-muted)]">
              <tr>
                <th className="py-1 pr-3 font-medium">Scanned</th>
                {series.map((s) => (
                  <th key={s.key} className="py-1 pr-3 text-right font-medium">
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((row) => (
                <tr key={String(row.t)} className="border-t border-[var(--border)]">
                  <td className="py-1 pr-3">{dateTimeFmt.format(new Date(Number(row.t)))}</td>
                  {series.map((s) => (
                    <td key={s.key} className="py-1 pr-3 text-right tabular-nums">
                      {row[s.key] == null ? <span className="text-[var(--text-muted)]">{NOT_AVAILABLE}</span> : format(Number(row[s.key]))}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="h-64" role="img" aria-label={`${title} chart; use "Show as table" for exact values`}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
              <XAxis
                dataKey="t"
                type="number"
                scale="time"
                domain={["dataMin", "dataMax"]}
                tickFormatter={(t: number) => dateFmt.format(new Date(t))}
                stroke="var(--text-muted)"
                tick={{ fill: "var(--text-muted)", fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: "var(--chart-grid)" }}
              />
              <YAxis
                tickFormatter={(v: number) => format(v)}
                stroke="var(--text-muted)"
                tick={{ fill: "var(--text-muted)", fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                width={64}
                allowDecimals={false}
                domain={zeroBaseline ? [0, "auto"] : ["auto", "auto"]}
              />
              <Tooltip
                cursor={{ stroke: "var(--text-muted)", strokeDasharray: "3 3" }}
                contentStyle={{
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  color: "var(--text)",
                  fontSize: 12,
                }}
                labelFormatter={(t) => dateTimeFmt.format(new Date(Number(t)))}
                formatter={(value, name) => [value == null ? NOT_AVAILABLE : format(Number(value)), name]}
              />
              <Legend iconType="plainline" wrapperStyle={{ fontSize: 12, color: "var(--text-muted)" }} />
              {series.map((s) => (
                <Line
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  name={s.label}
                  stroke={color(s)}
                  strokeWidth={2}
                  dot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)", fill: color(s) }}
                  activeDot={{ r: 5, strokeWidth: 2, stroke: "var(--surface)" }}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </figure>
  );
}
