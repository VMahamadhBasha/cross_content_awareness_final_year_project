import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Creator Dashboard",
  description: "Track creator posts, engagement, and recommendations in one place.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <div className="brand"><span className="logo">◆</span> Creator Dashboard</div>
          <nav>
            <Link href="/">Overview</Link>
            <Link href="/whatif">Plan a post</Link>
          </nav>
        </header>
        <main className="container">{children}</main>
      </body>
    </html>
  );
}
