import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import AppShell from "./AppShell";
import Scan from "./pages/Scan";
import Snapshots from "./pages/Snapshots";
import Providers from "./pages/Providers";
import History from "./pages/History";
import Settings from "./pages/Settings";
import Memory from "./pages/Memory";
import { useSettings } from "./hooks/useSettings";

const Dashboard = lazy(() => import("./pages/Dashboard"));

export function LandingRedirect() {
  const { settings } = useSettings();
  return <Navigate to={`/${settings.landingPage}`} replace />;
}

function DashboardRoute() {
  return (
    <Suspense
      fallback={
        <div className="p-8 text-text-muted font-mono text-sm animate-pulse">
          loading dashboard…
        </div>
      }
    >
      <Dashboard />
    </Suspense>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route index element={<LandingRedirect />} />
          <Route path="dashboard" element={<DashboardRoute />} />
          <Route path="disk" element={<Scan />} />
          <Route path="disk/providers" element={<Providers />} />
          <Route path="disk/snapshots" element={<Snapshots />} />
          <Route path="disk/history" element={<History />} />
          <Route path="memory" element={<Memory />} />
          <Route path="memory/:tab" element={<Memory />} />
          <Route path="snapshots" element={<Navigate to="/disk/snapshots" replace />} />
          <Route path="providers" element={<Navigate to="/disk/providers" replace />} />
          <Route path="history" element={<Navigate to="/disk/history" replace />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
