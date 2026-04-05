/**
 * Server-side API route to proxy ML training requests.
 * Injects the API key server-side so it's never exposed to the browser.
 */
const AGENT_HOST = process.env.AGENT_API_HOST || "agent-runner";
const AGENT_PORT = process.env.AGENT_API_PORT || "3001";
const API_KEY = process.env.ML_TRAIN_API_KEY || "";

export async function POST() {
  const url = `http://${AGENT_HOST}:${AGENT_PORT}/api/ml/train`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (API_KEY) {
    headers["X-API-Key"] = API_KEY;
  }

  try {
    const res = await fetch(url, { method: "POST", headers });
    const data = await res.json();
    return Response.json(data, { status: res.status });
  } catch (err) {
    return Response.json(
      { error: "Agent runner unavailable" },
      { status: 502 }
    );
  }
}
