"use client";

import { useQuery } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";

import { api } from "@/lib/api";
import type { Meta } from "@/lib/types";

/** Unmissable warning whenever the server generates MOCK (fake) marketplace data. */
export function MockBanner() {
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api<Meta>("/meta"), staleTime: 5 * 60_000 });
  if (!meta.data?.mock_connector_enabled) return null;
  return (
    <div role="alert" className="flex items-center gap-2 bg-red-600 px-4 py-2 text-sm font-medium text-white">
      <TriangleAlert aria-hidden className="size-4 shrink-0" />
      MOCK DATA: scans in this environment produce generated test data, not real Amazon.in offers.
    </div>
  );
}

export function MockBadge() {
  return (
    <span
      title="Generated test data, not real marketplace data"
      className="ml-1 inline-block rounded bg-red-600 px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-white"
    >
      MOCK
    </span>
  );
}
