import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CC | AI Trading Dashboard",
  description: "Multi-agent algo trading dashboard — Multi-Pair Futures",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-TW">
      <body className="min-h-screen bg-[#0a0e17] antialiased">
        {children}
      </body>
    </html>
  );
}
