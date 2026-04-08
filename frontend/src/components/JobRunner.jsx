import { useEffect, useState } from "react";
import { client } from "../api/client";

export default function JobRunner({ jobId }) {
  const [state, setState] = useState({ status: "idle", logs: [] });

  useEffect(() => {
    if (!jobId) return;
    let timer = null;
    const tick = async () => {
      const data = await client.jobLogs(jobId);
      setState(data);
      if (data.status === "running" || data.status === "queued") {
        timer = setTimeout(tick, 1000);
      }
    };
    tick();
    return () => timer && clearTimeout(timer);
  }, [jobId]);

  if (!jobId) return null;
  return (
    <section className="card">
      <h3>Job Status: {state.status}</h3>
      <pre className="logs">{state.logs?.join("\n")}</pre>
    </section>
  );
}
