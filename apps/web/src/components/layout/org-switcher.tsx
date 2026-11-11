"use client";

import { useSession } from "@/components/session/session-provider";

export function OrgSwitcher() {
  const { me, org, switchOrg } = useSession();
  if (me.memberships.length < 2) {
    return <div className="truncate text-sm font-medium" title={org.name}>{org.name}</div>;
  }
  return (
    <label className="block">
      <span className="sr-only">Organization</span>
      <select
        value={org.id}
        onChange={(e) => switchOrg(e.target.value)}
        className="w-full truncate rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1.5 text-sm"
      >
        {me.memberships.map((m) => (
          <option key={m.organization_id} value={m.organization_id}>
            {m.organization_name}
          </option>
        ))}
      </select>
    </label>
  );
}
