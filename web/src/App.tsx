import { BrowserRouter, Route, Routes } from "react-router-dom";
import AppShell from "./AppShell";
import Scan from "./pages/Scan";
import Snapshots from "./pages/Snapshots";
import Providers from "./pages/Providers";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route index element={<Scan />} />
          <Route path="snapshots" element={<Snapshots />} />
          <Route path="providers" element={<Providers />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
