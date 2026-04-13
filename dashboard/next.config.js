/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  async rewrites() {
    const dest = `http://${process.env.AGENT_API_HOST || "agent-runner"}:${process.env.AGENT_API_PORT || "3001"}`;
    return [
      {
        source: "/api/agents/:path*",
        destination: `${dest}/api/agents/:path*`,
      },
      {
        source: "/api/findings/:path*",
        destination: `${dest}/api/findings/:path*`,
      },
      {
        source: "/api/strategies/:path*",
        destination: `${dest}/api/strategies/:path*`,
      },
      {
        source: "/api/ft/:path*",
        destination: `${dest}/api/ft/:path*`,
      },
      {
        source: "/api/ml/:path*",
        destination: `${dest}/api/ml/:path*`,
      },
      {
        source: "/api/diagnostics/:path*",
        destination: `${dest}/api/diagnostics/:path*`,
      },
      {
        source: "/api/benchmark",
        destination: `${dest}/api/benchmark`,
      },
      {
        source: "/api/kill-switch",
        destination: `${dest}/api/kill-switch`,
      },
      {
        source: "/api/backtest/:path*",
        destination: `${dest}/api/backtest/:path*`,
      },
      {
        source: "/api/risk/:path*",
        destination: `${dest}/api/risk/:path*`,
      },
      {
        source: "/api/data/:path*",
        destination: `${dest}/api/data/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
