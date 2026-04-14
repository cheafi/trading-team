import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CC | Algo Trading Dashboard",
  description: "6-pair USDT futures short specialist — R2 regime, 5m timeframe, paper trading",
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
