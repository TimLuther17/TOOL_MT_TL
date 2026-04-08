const API_BASE = "http://localhost:8000";

async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status}`);
  }
  return res.json();
}

export const client = {
  options: () => api("/api/options"),
  routeOptions: () => api("/api/options/routes"),
  umlaufOptions: () => api("/api/options/umlauf"),
  simulationOptions: () => api("/api/options/simulation"),
  runRouting: (payload) => api("/api/run/routing", { method: "POST", body: JSON.stringify(payload) }),
  runUmlauf: (payload) => api("/api/run/umlauf", { method: "POST", body: JSON.stringify(payload) }),
  runSimulation: (payload) => api("/api/run/simulation", { method: "POST", body: JSON.stringify(payload) }),
  jobLogs: (jobId) => api(`/api/jobs/${jobId}/logs`),
  results: () => api("/api/results"),
};
