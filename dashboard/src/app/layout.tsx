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
        <footer className="max-w-[1600px] mx-auto px-4 pb-6 pt-2 border-t border-slate-800/50 mt-4">
          <p className="text-[10px] text-slate-600 text-center leading-relaxed">
            ⚠️ Not financial advice. For educational/research purposes only. Past performance does not guarantee future results.
            You may lose all capital. Provided AS-IS without warranty. Not a registered investment advisor.
            All figures shown are from paper trading or historical backtests.
          </p>
        </footer>
      </body>
    </html>
  );
}
