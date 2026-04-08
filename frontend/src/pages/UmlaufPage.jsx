import { useEffect, useState } from "react";
import { client } from "../api/client";
import JobRunner from "../components/JobRunner";

export default function UmlaufPage() {
  const [routes, setRoutes] = useState({});
  const [form, setForm] = useState({
    mode: "1",
    city: "",
    bus: "",
    accel_idx: "0",
    scenario_idx: "2",
    file_idx: "a",
    umlauf: "",
    excel_idx: "0",
  });
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
    const res = await client.runUmlauf(form);
    setJobId(res.job_id);
  };

  return (
    <section>
      <h1>Umlauf + Basis-Speedprofil</h1>
      <form className="card" onSubmit={submit}>
        <label>Mode
          <select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>
            <option value="1">HEAG</option>
            <option value="0">Manuell</option>
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
        <label>Umlauf-Muster <input value={form.umlauf} onChange={(e) => setForm({ ...form, umlauf: e.target.value })} /></label>
        <button type="submit">Pipeline starten</button>
      </form>
      <JobRunner jobId={jobId} />
    </section>
  );
}
