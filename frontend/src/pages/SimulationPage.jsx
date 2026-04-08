import { useEffect, useMemo, useState } from "react";
import { client } from "../api/client";
import JobRunner from "../components/JobRunner";

export default function SimulationPage() {
  const [options, setOptions] = useState({});
  const [form, setForm] = useState({
    provider: "",
    city: "",
    bus: "",
    file_idx: "a",
    date: "08.04.2026 06:00",
    accel_idx: "0",
    scenario_idx: "2",
    variant: "G4",
    cleanup: false,
  });
  const [jobId, setJobId] = useState("");

  useEffect(() => {
    client.simulationOptions().then((data) => {
      setOptions(data);
      const provider = Object.keys(data)[0] || "";
      const city = Object.keys(data[provider] || {})[0] || "";
      const bus = Object.keys(data[provider]?.[city] || {})[0] || "";
      setForm((prev) => ({ ...prev, provider, city, bus }));
    });
  }, []);

  const cities = useMemo(() => Object.keys(options[form.provider] || {}), [options, form.provider]);
  const buses = useMemo(() => Object.keys(options[form.provider]?.[form.city] || {}), [options, form.provider, form.city]);

  const submit = async (e) => {
    e.preventDefault();
    const res = await client.runSimulation(form);
    setJobId(res.job_id);
  };

  return (
    <section>
      <h1>Simulation</h1>
      <form className="card" onSubmit={submit}>
        <label>Provider
          <select value={form.provider} onChange={(e) => {
            const provider = e.target.value;
            const city = Object.keys(options[provider] || {})[0] || "";
            const bus = Object.keys(options[provider]?.[city] || {})[0] || "";
            setForm({ ...form, provider, city, bus });
          }}>
            {Object.keys(options).map((p) => <option key={p}>{p}</option>)}
          </select>
        </label>
        <label>Stadt
          <select value={form.city} onChange={(e) => {
            const city = e.target.value;
            const bus = Object.keys(options[form.provider]?.[city] || {})[0] || "";
            setForm({ ...form, city, bus });
          }}>
            {cities.map((city) => <option key={city}>{city}</option>)}
          </select>
        </label>
        <label>Bus
          <select value={form.bus} onChange={(e) => setForm({ ...form, bus: e.target.value })}>
            {buses.map((bus) => <option key={bus}>{bus}</option>)}
          </select>
        </label>
        <label>Startdatum <input value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} /></label>
        <label>Variante <input value={form.variant} onChange={(e) => setForm({ ...form, variant: e.target.value })} /></label>
        <label><input type="checkbox" checked={form.cleanup} onChange={(e) => setForm({ ...form, cleanup: e.target.checked })} /> Cleanup</label>
        <button type="submit">Simulation starten</button>
      </form>
      <JobRunner jobId={jobId} />
    </section>
  );
}
