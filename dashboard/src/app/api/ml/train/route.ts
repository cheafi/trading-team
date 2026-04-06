/**
 * Server-side API route to proxy ML training requests.
 * Injects the API key server-side so it's never exposed to the browser.
 * If ML_TRAIN_API_KEY is set on the agent-runner but missing here,
 * the agent-runner will reject the request (fail closed).
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
    if (res.status === 403) {
      return Response.json(
        { error: "Training auth failed — ML_TRAIN_API_KEY mismatch" },
        { status: 403 },
      );
    }
    return Response.json(data, { status: res.status });
  } catch (err) {
    return Response.json(
      { error: "Agent runner unavailable" },
      { status: 502 },
    );
  }
}
