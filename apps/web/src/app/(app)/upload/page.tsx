"use client";

import { useQuery } from "@tanstack/react-query";
import { FileSpreadsheet, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState, type DragEvent } from "react";

import { useSession } from "@/components/session/session-provider";
import { BatchStatusBadge } from "@/components/uploads/batch-status";
import { Alert, Button, errorMessage } from "@/components/ui/form";
import { api, apiDownload, apiUpload } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { Batch, Page } from "@/lib/types";
import { formatBytes, precheckFile } from "@/lib/upload-checks";

export default function UploadPage() {
  const { org, can } = useSession();
  const router = useRouter();
  const canWrite = can("products.write");
  const input = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const history = useQuery({
    queryKey: ["tenant", org.id, "uploads"],
    queryFn: () => api<Page<Batch>>("/uploads?page_size=50", { orgId: org.id }),
  });

  async function send(file: File) {
    const problem = precheckFile(file);
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    setProgress(0);
    try {
      const batch = await apiUpload<Batch>("/uploads", file, org.id, setProgress);
      router.push(`/upload/${batch.id}`);
    } catch (e) {
      setError(errorMessage(e));
      setProgress(null);
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file) void send(file);
  }

  async function template(format: "csv" | "xlsx") {
    try {
      await apiDownload(`/uploads/template?format=${format}`, null, `sellerscope-products.${format}`);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <section className="max-w-5xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Upload Products</h1>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          Add many Amazon.in products at once from an Excel (.xlsx) or CSV file. You&apos;ll review every row before
          anything is added.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <FileSpreadsheet aria-hidden className="size-4 text-[var(--text-muted)]" />
        <span>Template:</span>
        <Button variant="secondary" onClick={() => void template("xlsx")}>
          Excel template
        </Button>
        <Button variant="secondary" onClick={() => void template("csv")}>
          CSV template
        </Button>
        <span className="text-[var(--text-muted)]">Columns: ASIN (or Amazon.in link), Product name, Brand.</span>
      </div>

      {error && <Alert>{error}</Alert>}

      {canWrite ? (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`rounded-lg border-2 border-dashed p-8 text-center transition-colors ${
            dragging ? "border-brand-600 bg-brand-50 dark:bg-brand-700/10" : "border-[var(--border)] bg-[var(--surface)]"
          }`}
        >
          {progress === null ? (
            <>
              <Upload aria-hidden className="mx-auto size-8 text-[var(--text-muted)]" />
              <p className="mt-3 text-sm">Drag a file here, or</p>
              <Button className="mt-3" onClick={() => input.current?.click()}>
                Choose file
              </Button>
              <p className="mt-3 text-xs text-[var(--text-muted)]">.csv or .xlsx · up to 10 MB · up to 50,000 rows</p>
              <input
                ref={input}
                type="file"
                accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                aria-label="Product file"
                className="sr-only"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (file) void send(file);
                }}
              />
            </>
          ) : (
            <div className="mx-auto max-w-sm">
              <p className="text-sm">Uploading… {Math.round(progress * 100)}%</p>
              <div
                role="progressbar"
                aria-label="Upload progress"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(progress * 100)}
                className="mt-2 h-2 overflow-hidden rounded-full bg-black/10 dark:bg-white/10"
              >
                <div className="bg-brand-600 h-full transition-all" style={{ width: `${progress * 100}%` }} />
              </div>
            </div>
          )}
        </div>
      ) : (
        <Alert tone="info">Your role can view uploads but not add products.</Alert>
      )}

      <div>
        <h2 className="text-lg font-semibold">Upload history</h2>
        {history.error && <Alert>{errorMessage(history.error)}</Alert>}
        {history.data && history.data.items.length === 0 && (
          <p className="mt-2 text-sm text-[var(--text-muted)]">No uploads yet.</p>
        )}
        {history.data && history.data.items.length > 0 && (
          <div className="mt-3 overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--surface)]">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-[var(--border)] text-xs text-[var(--text-muted)]">
                <tr>
                  <th className="px-4 py-2 font-medium">File</th>
                  <th className="px-4 py-2 font-medium">Uploaded</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 text-right font-medium">Rows</th>
                  <th className="px-4 py-2 text-right font-medium">Added</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {history.data.items.map((b) => (
                  <tr key={b.id} className="border-b border-[var(--border)] last:border-0">
                    <td className="px-4 py-2">
                      <div className="max-w-xs truncate font-medium" title={b.original_filename}>
                        {b.original_filename}
                      </div>
                      <div className="text-xs text-[var(--text-muted)]">{formatBytes(b.file_size_bytes)}</div>
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap">{formatDateTime(b.created_at)}</td>
                    <td className="px-4 py-2">
                      <BatchStatusBadge status={b.status} />
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      {b.status === "failed" || b.status === "uploaded" || b.status === "parsing" ? "—" : b.total_rows}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">{b.status === "committed" ? b.committed_rows : "—"}</td>
                    <td className="px-4 py-2 text-right">
                      <Link href={`/upload/${b.id}`} className="text-brand-600 text-xs hover:underline">
                        {b.status === "preview_ready" ? "Review" : "View"}
                        <span className="sr-only"> {b.original_filename}</span>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
