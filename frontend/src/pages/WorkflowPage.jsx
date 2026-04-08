import { useEffect, useMemo, useState } from "react";
import { client } from "../api/client";
import JobRunner from "../components/JobRunner";

export default function WorkflowPage() {
  const [routeOptions, setRouteOptions] = useState({});
  const [umlaufOptions, setUmlaufOptions] = useState({});
  const [simOptions, setSimOptions] = useState({});
  const [jobId, setJobId] = useState("");

  const [routeForm, setRouteForm] = useState({ mode: "new", selection: "a", visualize: true });
  const [umlaufForm, setUmlaufForm] = useState({
    mode: "1",
    city: "",
    bus: "",
    accel_idx: "0",
    scenario_idx: "2",
    file_idx: "a",
    umlauf: "",
    excel_idx: "0",
  });
  const [simForm, setSimForm] = useState({
    provider: "",
    city: "",
    bus: "",
    file_idx: "0",
    date: "08.04.2026 06:00",
    accel_idx: "0",
    scenario_idx: "2",
    variant: "G4",
    cleanup: false,
  });

  useEffect(() => {
    client.routeOptions().then((data) => {
      setRouteOptions(data);
      const city = Object.keys(data)[0] || "";
      const bus = data[city]?.[0] || "";
      setUmlaufForm((prev) => ({ ...prev, city, bus }));
    });
    client.umlaufOptions().then(setUmlaufOptions);
    client.simulationOptions().then((data) => {
      setSimOptions(data);
      const provider = Object.keys(data)[0] || "";
      const city = Object.keys(data[provider] || {})[0] || "";
      const bus = Object.keys(data[provider]?.[city] || {})[0] || "";
      setSimForm((prev) => ({ ...prev, provider, city, bus, file_idx: "0" }));
    });
  }, []);

  const umlaufBuses = routeOptions[umlaufForm.city] || [];
  const simCities = useMemo(() => Object.keys(simOptions[simForm.provider] || {}), [simOptions, simForm.provider]);
  const simBuses = useMemo(
    () => Object.keys(simOptions[simForm.provider]?.[simForm.city] || {}),
    [simOptions, simForm.provider, simForm.city]
  );
  const simFiles = simOptions[simForm.provider]?.[simForm.city]?.[simForm.bus] || [];

  const runRouteGeneration = async () => {
    const res = await client.runRouting(routeForm);
    setJobId(res.job_id);
  };

  const runUmlauf = async (e) => {
    e.preventDefault();
    const res = await client.runUmlauf(umlaufForm);
    setJobId(res.job_id);
  };

  const runSimulation = async (e) => {
    e.preventDefault();
    const res = await client.runSimulation(simForm);
    setJobId(res.job_id);
  };

  return (
    <section>
      <h1>Frontend Workflow (Lokal)</h1>
      <p>Schritt 1: Neue Route erzeugen und Map bauen.</p>
      <div className="card">
        <button onClick={runRouteGeneration}>Neue Route generieren</button>
        <label>
          Auswahl
          <input
            value={routeForm.selection}
            onChange={(e) => setRouteForm((prev) => ({ ...prev, selection: e.target.value }))}
          />
        </label>
      </div>

      <p>Schritt 2: Route wählen und Umlauf erzeugen.</p>
      <form className="card" onSubmit={runUmlauf}>
        <label>
          Stadt
          <select
            value={umlaufForm.city}
            onChange={(e) => setUmlaufForm((prev) => ({ ...prev, city: e.target.value, bus: routeOptions[e.target.value]?.[0] || "" }))}
          >
            {Object.keys(routeOptions).map((city) => (
              <option key={city}>{city}</option>
            ))}
          </select>
        </label>
        <label>
          Route / Linie
          <select value={umlaufForm.bus} onChange={(e) => setUmlaufForm((prev) => ({ ...prev, bus: e.target.value }))}>
            {umlaufBuses.map((bus) => (
              <option key={bus}>{bus}</option>
            ))}
          </select>
        </label>
        <label>
          Modus
          <select value={umlaufForm.mode} onChange={(e) => setUmlaufForm((prev) => ({ ...prev, mode: e.target.value }))}>
            <option value="1">Kurse vorhanden (HEAG)</option>
            <option value="0">Umlauf manuell</option>
          </select>
        </label>
        {umlaufForm.mode === "0" && (
          <label>
            Umlauf-Muster
            <input value={umlaufForm.umlauf} onChange={(e) => setUmlaufForm((prev) => ({ ...prev, umlauf: e.target.value }))} />
          </label>
        )}
        <button type="submit">Umlauf erzeugen</button>
      </form>

      <p>Schritt 3: Vorhandenen Kurs/Profil wählen und letztes Main-Skript starten.</p>
      <form className="card" onSubmit={runSimulation}>
        <label>
          Provider
          <select
            value={simForm.provider}
            onChange={(e) => {
              const provider = e.target.value;
              const city = Object.keys(simOptions[provider] || {})[0] || "";
              const bus = Object.keys(simOptions[provider]?.[city] || {})[0] || "";
              setSimForm((prev) => ({ ...prev, provider, city, bus, file_idx: "0" }));
            }}
          >
            {Object.keys(simOptions).map((provider) => (
              <option key={provider}>{provider}</option>
            ))}
          </select>
        </label>
        <label>
          Stadt
          <select
            value={simForm.city}
            onChange={(e) => {
              const city = e.target.value;
              const bus = Object.keys(simOptions[simForm.provider]?.[city] || {})[0] || "";
              setSimForm((prev) => ({ ...prev, city, bus, file_idx: "0" }));
            }}
          >
            {simCities.map((city) => (
              <option key={city}>{city}</option>
            ))}
          </select>
        </label>
        <label>
          Linie
          <select value={simForm.bus} onChange={(e) => setSimForm((prev) => ({ ...prev, bus: e.target.value, file_idx: "0" }))}>
            {simBuses.map((bus) => (
              <option key={bus}>{bus}</option>
            ))}
          </select>
        </label>
        <label>
          Kurs / Profil
          <select value={simForm.file_idx} onChange={(e) => setSimForm((prev) => ({ ...prev, file_idx: e.target.value }))}>
            {simFiles.map((file, idx) => (
              <option value={String(idx)} key={file}>
                {file}
              </option>
            ))}
          </select>
        </label>
        <label>
          Startdatum
          <input value={simForm.date} onChange={(e) => setSimForm((prev) => ({ ...prev, date: e.target.value }))} />
        </label>
        <button type="submit">Letztes Main-Skript starten (Simulation)</button>
      </form>

      <JobRunner jobId={jobId} />
      <p>
        Hinweis: Dieses Frontend ist auf lokalen Betrieb ausgelegt (localhost/127.0.0.1).
        Gefundene Kursordner: {Object.keys(umlaufOptions).join(", ") || "-"}
      </p>
    </section>
  );
}
