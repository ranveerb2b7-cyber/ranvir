"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { Alert } from "@/components/ui/form";
import { api, ApiError } from "@/lib/api";
import { supabaseBrowser } from "@/lib/supabase/client";
import type { Me, Organization } from "@/lib/types";

export const ORG_STORAGE_KEY = "sellerscope.currentOrg";

interface SessionState {
  me: Me;
  org: Organization;
  can: (permission: string) => boolean;
  switchOrg: (orgId: string) => void;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<SessionState | null>(null);

export function useSession(): SessionState {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside <SessionProvider>");
  return ctx;
}

export function rememberOrg(orgId: string) {
  try {
    window.localStorage.setItem(ORG_STORAGE_KEY, orgId);
  } catch {
    // Storage unavailable (private mode): the selection just won't persist.
  }
}

function storedOrg(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(ORG_STORAGE_KEY);
  } catch {
    return null;
  }
}

/** Loads the signed-in user and the selected organization for all app pages. */
export function SessionProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(storedOrg);

  const meQuery = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/me") });
  const me = meQuery.data;
  const membership =
    me?.memberships.find((m) => m.organization_id === selected) ?? me?.memberships[0];
  const orgId = membership?.organization_id;

  const orgQuery = useQuery({
    queryKey: ["org", orgId],
    queryFn: () => api<Organization>("/organizations/current", { orgId }),
    enabled: Boolean(orgId),
  });

  const unauthorized = meQuery.error instanceof ApiError && meQuery.error.status === 401;
  // Only act on fresh data: a stale cached answer may predate joining an organization.
  const noOrganizations =
    me !== undefined && me.memberships.length === 0 && !meQuery.isFetching;

  useEffect(() => {
    if (unauthorized) router.replace(`/login?next=${encodeURIComponent(window.location.pathname)}`);
    else if (noOrganizations) router.replace("/onboarding");
  }, [unauthorized, noOrganizations, router]);

  useEffect(() => {
    if (orgId) rememberOrg(orgId);
  }, [orgId]);

  const org = orgQuery.data;
  const value = useMemo<SessionState | null>(() => {
    if (!me || !org) return null;
    return {
      me,
      org,
      can: (permission) => org.permissions.includes(permission),
      switchOrg: (id) => {
        rememberOrg(id);
        setSelected(id);
        // Drop cached data of the previous organization.
        queryClient.removeQueries({ predicate: (q) => q.queryKey[0] === "tenant" });
      },
      refresh: async () => {
        await queryClient.invalidateQueries();
      },
      signOut: async () => {
        await supabaseBrowser().auth.signOut();
        queryClient.clear();
        router.replace("/login");
        router.refresh();
      },
    };
  }, [me, org, queryClient, router]);

  const error = (!unauthorized && meQuery.error) || orgQuery.error;
  if (error) {
    return (
      <div className="m-8">
        <Alert>
          {error.message}{" "}
          <button type="button" className="underline" onClick={() => void queryClient.invalidateQueries()}>
            Retry
          </button>
        </Alert>
      </div>
    );
  }
  if (!value) {
    return <div className="p-8 text-sm text-[var(--text-muted)]">Loading…</div>;
  }
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
