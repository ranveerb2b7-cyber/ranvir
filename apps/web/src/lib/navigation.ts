import type { LucideIcon } from "lucide-react";
import {
  Bell,
  FileBarChart,
  History,
  LayoutDashboard,
  PackageSearch,
  Settings,
  Store,
  Upload,
  Users,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Milestone that delivers this screen (see docs/plan/08-milestones.md). */
  milestone: string;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, milestone: "M4" },
  { href: "/upload", label: "Upload Products", icon: Upload, milestone: "M5" },
  { href: "/products", label: "Product Mapping", icon: PackageSearch, milestone: "M4" },
  { href: "/sellers", label: "Seller Intelligence", icon: Store, milestone: "M8" },
  { href: "/history", label: "Scan History", icon: History, milestone: "M8" },
  { href: "/alerts", label: "Alerts", icon: Bell, milestone: "M10" },
  { href: "/reports", label: "Reports", icon: FileBarChart, milestone: "M11" },
  { href: "/team", label: "Team Management", icon: Users, milestone: "M3" },
  { href: "/settings", label: "Settings", icon: Settings, milestone: "M3" },
];

export function navItem(href: string): NavItem {
  const item = NAV_ITEMS.find((n) => n.href === href);
  if (!item) throw new Error(`Unknown nav item: ${href}`);
  return item;
}
