import { useEffect, useState } from "react";

interface HealthResponse {
  status: string;
  service: string;
  version: string;
}

async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch("/api/health");
  if (!response.ok) {
    throw new Error(`Health check failed (HTTP ${response.status})`);
  }
  return (await response.json()) as HealthResponse;
}

type LoadState = "loading" | "ok" | "error";

function App() {
  const [state, setState] = useState<LoadState>("loading");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchHealth()
      .then((data) => {
        setHealth(data);
        setState("ok");
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Unknown error");
        setState("error");
      });
  }, []);

  return (
    <main>
      <h1>WindIQ</h1>

      {state === "loading" && <p>Checking backend…</p>}

      {state === "ok" && health && (
        <div>
          <h2>API status</h2>
          <dl>
            <dt>status</dt>
            <dd>
              <code>{health.status}</code>
            </dd>
            <dt>service</dt>
            <dd>
              <code>{health.service}</code>
            </dd>
            <dt>version</dt>
            <dd>
              <code>{health.version}</code>
            </dd>
          </dl>
        </div>
      )}

      {state === "error" && <p>Backend unreachable — {error}</p>}

      <footer>
        UI served by nginx · API at <code>/api</code> · docs at{" "}
        <a href="/api/docs" target="_blank" rel="noreferrer">
          /api/docs
        </a>
      </footer>
    </main>
  );
}

export default App;
