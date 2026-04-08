import { useEffect, useState } from "react";
import { client } from "../api/client";
import JobRunner from "../components/JobRunner";

export default function RoutingPage() {
  const [routes, setRoutes] = useState({});
  const [form, setForm] = useState({ mode: "raw", city: "", bus: "", selection: "a", visualize: false });
  const [jobId, setJobId] = useState("");

  useEffect(() => {
    client.routeOptions().then((data) => {
      setRoutes(data);
      const firstCity = Object.keys(data)[0] || "";
      const firstBus = data[firstCity]?.[0] || "";
      setForm((prev) => ({ ...prev, city: firstCity, bus: firstBus }));
    });
  }, []);

  const buses = routes[form.city] || [];

  const submit = async (e) => {
    e.preventDefault();
    const res = await client.runRouting(form);
    setJobId(res.job_id);
  };

  return (
    <section>
      <h1>Routing Pipeline</h1>
      <form className="card" onSubmit={submit}>
        <label>Mode
          <select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>
            <option value="new">new</option>
            <option value="raw">raw</option>
            <option value="list">list</option>
          </select>
        </label>
        <label>Stadt
          <select value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value, bus: routes[e.target.value]?.[0] || "" })}>
            {Object.keys(routes).map((city) => <option key={city}>{city}</option>)}
          </select>
        </label>
        <label>Bus
          <select value={form.bus} onChange={(e) => setForm({ ...form, bus: e.target.value })}>
            {buses.map((bus) => <option key={bus}>{bus}</option>)}
          </select>
        </label>
        <label>Selection
          <input value={form.selection} onChange={(e) => setForm({ ...form, selection: e.target.value })} />
        </label>
        <label>
          <input type="checkbox" checked={form.visualize} onChange={(e) => setForm({ ...form, visualize: e.target.checked })} />
          Visualize
        </label>
        <button type="submit">Pipeline starten</button>
      </form>
      <JobRunner jobId={jobId} />
    </section>
  );
}
