import type { Metadata } from "next";
import { connection } from "next/server";
import type { ReactNode } from "react";

import { Providers } from "@/components/providers";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "SellerScope", template: "%s · SellerScope" },
  description: "Marketplace seller mapping and intelligence for brands on Amazon India.",
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  // Render per request so Next can attach the CSP nonce (set in proxy.ts) to its scripts.
  await connection();
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
