import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { vi } from "vitest";

import TeamPage from "@/app/(app)/team/page";
import type { Member, Organization, Role } from "@/lib/types";

const members: Member[] = [
  { user_id: "u1", email: "owner@acme.in", full_name: "Owner", role: "owner", status: "active", joined_at: "2026-01-01T00:00:00Z" },
  { user_id: "u2", email: "analyst@acme.in", full_name: null, role: "analyst", status: "active", joined_at: "2026-02-01T00:00:00Z" },
];

const session = vi.hoisted(() => ({ role: "owner" as Role, permissions: [] as string[] }));

vi.mock("@/components/session/session-provider", () => ({
  useSession: () => ({
    me: { id: "u1", email: "owner@acme.in", full_name: "Owner", memberships: [] },
    org: { id: "org-1", name: "Acme", slug: "acme", role: session.role, permissions: session.permissions, created_at: "" } satisfies Organization,
    can: (p: string) => session.permissions.includes(p),
    refresh: vi.fn(),
  }),
}));

vi.mock("@/lib/api", () => ({
  api: vi.fn((path: string) => Promise.resolve(path === "/members" ? members : [])),
}));

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("TeamPage", () => {
  it("shows invite and member controls to roles that can manage members", async () => {
    session.role = "owner";
    session.permissions = ["members.manage"];
    wrap(<TeamPage />);
    expect(await screen.findByText("analyst@acme.in")).toBeInTheDocument();
    expect(screen.getByLabelText("Invite by email")).toBeInTheDocument();
    expect(screen.getByLabelText("Role for analyst@acme.in")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Make owner" })).toBeInTheDocument();
    // The owner row is never editable.
    expect(screen.queryByLabelText("Role for owner@acme.in")).not.toBeInTheDocument();
  });

  it("is read-only for viewers", async () => {
    session.role = "viewer";
    session.permissions = [];
    wrap(<TeamPage />);
    expect(await screen.findByText("analyst@acme.in")).toBeInTheDocument();
    expect(screen.queryByLabelText("Invite by email")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });
});
