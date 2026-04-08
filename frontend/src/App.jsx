import { NavLink, Route, Routes } from "react-router-dom";
import DashboardPage from "./pages/DashboardPage";
import RoutingPage from "./pages/RoutingPage";
import UmlaufPage from "./pages/UmlaufPage";
import SimulationPage from "./pages/SimulationPage";
import ResultsPage from "./pages/ResultsPage";
import WorkflowPage from "./pages/WorkflowPage";

export default function App() {
  return (
    <div className="layout">
      <aside className="sidebar">
        <h2>Pipeline UI</h2>
        <nav>
          <NavLink to="/">Dashboard</NavLink>
          <NavLink to="/workflow">Workflow</NavLink>
          <NavLink to="/routing">Routing</NavLink>
          <NavLink to="/umlauf">Umlauf</NavLink>
          <NavLink to="/simulation">Simulation</NavLink>
          <NavLink to="/results">Results</NavLink>
        </nav>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/workflow" element={<WorkflowPage />} />
          <Route path="/routing" element={<RoutingPage />} />
          <Route path="/umlauf" element={<UmlaufPage />} />
          <Route path="/simulation" element={<SimulationPage />} />
          <Route path="/results" element={<ResultsPage />} />
        </Routes>
      </main>
    </div>
  );
}
