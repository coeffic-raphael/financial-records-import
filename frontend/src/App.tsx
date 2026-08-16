import { QueryClientProvider } from "@tanstack/react-query";
import { Navigate, Route, BrowserRouter as Router, Routes } from "react-router-dom";

import { AppLayout } from "./components/AppLayout";
import { queryClient } from "./lib/queryClient";
import { useSessionRestore } from "./hooks/useSessionRestore";
import { installSessionBridge } from "./lib/session";
import { BatchDetailPage } from "./pages/BatchDetailPage";
import { BatchListPage } from "./pages/BatchListPage";
import { LoginPage } from "./pages/LoginPage";
import { RecordEditorPage } from "./pages/RecordEditorPage";
import { useAuthStore } from "./stores/authStore";

installSessionBridge();

function RequireAuth({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((state) => state.user);
  const { restoring, unreachable } = useSessionRestore();

  // Deciding before the restore attempt finishes would bounce every reload to
  // the login screen, which is what makes an in-memory token feel broken.
  if (restoring) return <p className="p-8 text-sm text-slate-500">Restoring session…</p>;

  if (unreachable && !user) {
    // Not "signed out" -- we simply could not ask. Saying so beats a login
    // screen that suggests the session ended when it may not have.
    return (
      <div className="p-8">
        <p className="text-sm font-medium text-slate-800">The server is unreachable.</p>
        <p className="mt-1 text-sm text-slate-500">
          It may be restarting. Reload the page once it is back.
        </p>
      </div>
    );
  }

  return user ? <>{children}</> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Router>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/*"
            element={
              <RequireAuth>
                <AppLayout>
                  <Routes>
                    <Route path="batches" element={<BatchListPage />} />
                    <Route path="batches/:batchId" element={<BatchDetailPage />} />
                    <Route path="records/:recordId" element={<RecordEditorPage />} />
                    <Route path="*" element={<Navigate to="/batches" replace />} />
                  </Routes>
                </AppLayout>
              </RequireAuth>
            }
          />
        </Routes>
      </Router>
    </QueryClientProvider>
  );
}
