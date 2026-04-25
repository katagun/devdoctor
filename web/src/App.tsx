import { BrowserRouter, Route, Routes } from "react-router-dom";
import AppShell from "./AppShell";
import Scan from "./pages/Scan";
import Snapshots from "./pages/Snapshots";
import Providers from "./pages/Providers";
import History from "./pages/History";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <BrowserRouter
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route index element={<Scan />} />
          <Route path="snapshots" element={<Snapshots />} />
          <Route path="providers" element={<Providers />} />
          <Route path="history" element={<History />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
