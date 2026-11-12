"use client";

import { useMutation } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { useSession } from "@/components/session/session-provider";
import { Alert, Button, errorMessage } from "@/components/ui/form";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { ExtensionPairing } from "@/lib/types";

const CHALLENGE = /^[A-Za-z0-9_-]{43,128}$/;

function Connect() {
  const { org, me } = useSession();
  const params = useSearchParams();
  const challenge = params.get("challenge") ?? "";
  const device = (params.get("device") ?? "Chrome extension").slice(0, 80);
  const approve = useMutation({
    mutationFn: () =>
      api<ExtensionPairing>("/extension/pair/start", {
        method: "POST",
        orgId: org.id,
        body: { code_challenge: challenge, device_name: device },
      }),
  });

  if (!CHALLENGE.test(challenge)) {
    return (
      <Alert>
        This page must be opened from the SellerScope browser extension. Open the extension and click &quot;Connect&quot;.
      </Alert>
    );
  }
  if (approve.data) {
    return (
      <div className="space-y-4 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6 text-center">
        <p className="text-sm text-[var(--text-muted)]">Enter this code in the extension:</p>
        <p className="font-mono text-4xl font-semibold tracking-[0.2em]" data-testid="pairing-code">
          {approve.data.pairing_code}
        </p>
        <p className="text-xs text-[var(--text-muted)]">
          Valid once, until {formatDateTime(approve.data.expires_at)}. It only works with the extension that opened this
          page. You can close this tab afterwards.
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-4 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6">
      <p>
        Connect <strong>{device}</strong> to <strong>{org.name}</strong> as {me.email}?
      </p>
      <ul className="list-disc space-y-1 pl-5 text-sm text-[var(--text-muted)]">
        <li>It shows the seller data SellerScope has stored for the Amazon.in product you&apos;re viewing.</li>
        <li>It can start a &quot;Check now&quot; scan if your role allows scans (counts toward your plan).</li>
        <li>It reads only the page address, never page content, and can be disconnected any time in Settings.</li>
      </ul>
      <p className="text-xs text-[var(--text-muted)]">To connect a different organization, switch organization first (sidebar).</p>
      {approve.error && <Alert>{errorMessage(approve.error)}</Alert>}
      <Button onClick={() => approve.mutate()} disabled={approve.isPending}>
        Approve and show code
      </Button>
    </div>
  );
}

export default function ExtensionConnectPage() {
  return (
    <section className="max-w-xl space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Connect the browser extension</h1>
      <Suspense>
        <Connect />
      </Suspense>
    </section>
  );
}
