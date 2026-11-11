import type { Metadata } from "next";

import { NotBuilt } from "@/components/ui/not-built";
import { navItem } from "@/lib/navigation";

const item = navItem("/team");

export const metadata: Metadata = { title: item.label };

export default function Page() {
  return <NotBuilt title={item.label} milestone={item.milestone} />;
}
