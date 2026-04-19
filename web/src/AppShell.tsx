import { Outlet } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";

export default function AppShell() {
  return (
    <div className="min-h-screen grid grid-cols-[180px_1fr] bg-bg text-text font-sans">
      <Sidebar />
      <main className="flex flex-col min-w-0">
        <Outlet />
      </main>
    </div>
  );
}
