import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "AegisOps — Coordinate incident response",
    template: "%s · AegisOps",
  },
  description:
    "AegisOps helps SaaS engineering and security leaders coordinate incident response with clear workflows, control, and integrations.",
  metadataBase: new URL("http://127.0.0.1:3000"),
  openGraph: {
    title: "AegisOps — Coordinate incident response",
    description:
      "Book a technical demo of incident response orchestration for SaaS teams.",
    type: "website",
    locale: "en_US",
  },
  robots: { index: true, follow: true },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <a className="skip-link btn btn-secondary" href="#main">
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
