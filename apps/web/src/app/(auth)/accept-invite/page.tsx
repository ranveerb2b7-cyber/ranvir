"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { AuthCard } from "@/components/layout/auth-card";
import { rememberOrg } from "@/components/session/session-provider";
import { Alert, Button } from "@/components/ui/form";
import { api } from "@/lib/api";
import { supabaseBrowser } from "@/lib/supabase/client";
import { ROLE_LABELS, type InvitationPreview } from "@/lib/types";

const STATUS_MESSAGES: Record<Exclude<InvitationPreview["status"], "pending">, string> = {
  accepted: "This invitation has already been used.",
  revoked: "This invitation was cancelled by the organization.",
  expired: "This invitation has expired. Ask the person who invited you to resend it.",
};

function AcceptInvite() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const token = useSearchParams().get("token") ?? "";

  const preview = useQuery({
    queryKey: ["invitation-preview", token],
    queryFn: () =>
      api<InvitationPreview>("/invitations/preview", { method: "POST", body: { token } }),
    enabled: token.length > 0,
  });

  const accept = useMutation({
    mutationFn: () =>
      api<{ organization_id: string }>("/invitations/accept", { method: "POST", body: { token } }),
    onSuccess: ({ organization_id }) => {
      rememberOrg(organization_id);
      queryClient.removeQueries({ queryKey: ["me"] });
      router.replace("/dashboard");
    },
  });

  async function switchAccount() {
    await supabaseBrowser().auth.signOut();
    router.replace(`/login?next=${encodeURIComponent(`/accept-invite?token=${token}`)}`);
  }

  const error = !token ? "This invitation link is incomplete." : (preview.error ?? accept.error)?.message;
  if (error) {
    return (
      <AuthCard title="Invitation">
        <Alert>{error}</Alert>
      </AuthCard>
    );
  }
  const data = preview.data;
  if (!data) {
    return <AuthCard title="Invitation">Loading…</AuthCard>;
  }
  if (data.status !== "pending") {
    return (
      <AuthCard title="Invitation">
        <Alert>{STATUS_MESSAGES[data.status]}</Alert>
      </AuthCard>
    );
  }
  return (
    <AuthCard title={`Join ${data.organization_name}`}>
      <p className="text-sm">
        You were invited as <strong>{ROLE_LABELS[data.role]}</strong>.
      </p>
      {data.email_matches ? (
        <Button onClick={() => accept.mutate()} disabled={accept.isPending} className="mt-6 w-full">
          {accept.isPending ? "Joining…" : "Accept invitation"}
        </Button>
      ) : (
        <div className="mt-4 space-y-4">
          <Alert>
            This invitation was sent to <strong>{data.email}</strong>. Sign in with that email to accept it.
          </Alert>
          <Button variant="secondary" onClick={() => void switchAccount()} className="w-full">
            Sign in with a different account
          </Button>
        </div>
      )}
    </AuthCard>
  );
}

export default function AcceptInvitePage() {
  return (
    <Suspense>
      <AcceptInvite />
    </Suspense>
  );
}
