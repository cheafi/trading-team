/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/agents/:path*",
        destination: `http://${process.env.AGENT_API_HOST || "agent-runner"}:${process.env.AGENT_API_PORT || "3001"}/api/agents/:path*`,
      },
      {
        source: "/api/findings/:path*",
        destination: `http://${process.env.AGENT_API_HOST || "agent-runner"}:${process.env.AGENT_API_PORT || "3001"}/api/findings/:path*`,
      },
      {
        source: "/api/strategies/:path*",
        destination: `http://${process.env.AGENT_API_HOST || "agent-runner"}:${process.env.AGENT_API_PORT || "3001"}/api/strategies/:path*`,
      },
      {
        source: "/api/ft/:path*",
        destination: `http://${process.env.AGENT_API_HOST || "agent-runner"}:${process.env.AGENT_API_PORT || "3001"}/api/ft/:path*`,
      },
      {
        source: "/api/ml/:path*",
        destination: `http://${process.env.AGENT_API_HOST || "agent-runner"}:${process.env.AGENT_API_PORT || "3001"}/api/ml/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
