/** API response types (mirrors apps/api/src/sellerscope/schemas/accounts.py). */
export type Role = "owner" | "admin" | "analyst" | "viewer";
export type AssignableRole = Exclude<Role, "owner">;

export interface Membership {
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  role: Role;
}

export interface Me {
  id: string;
  email: string;
  full_name: string | null;
  memberships: Membership[];
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  role: Role;
  permissions: string[];
  created_at: string;
}

export interface Member {
  user_id: string;
  email: string;
  full_name: string | null;
  role: Role;
  status: "active" | "suspended";
  joined_at: string;
}

export interface Invitation {
  id: string;
  email: string;
  role: AssignableRole;
  expires_at: string;
  created_at: string;
  invited_by: string | null;
}

export interface InvitationSent extends Invitation {
  email_sent: boolean;
}

export interface InvitationPreview {
  organization_name: string;
  email: string;
  role: AssignableRole;
  status: "pending" | "accepted" | "revoked" | "expired";
  email_matches: boolean;
}

export const ROLE_LABELS: Record<Role, string> = {
  owner: "Owner",
  admin: "Admin",
  analyst: "Analyst",
  viewer: "Viewer",
};
