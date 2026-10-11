import React, { useContext } from "react";
import { Routes, Route, Navigate } from "react-router-dom";

import { AuthContext } from "../app/App";
import AppLayout from "../layouts/appLayout";
import LoginPage from "./LoginPage";
import NotFoundPage from "./NotFoundPage";
import { PAGE_REGISTRY } from "./registry";

const ProtectedLayout = () => {
  const { mode, identity, authReady } = useContext(AuthContext);
  if (!authReady) {
    return (
      <main className="app-bg grid min-h-screen place-items-center text-sm text-themeTextGray">
        正在检查登录状态…
      </main>
    );
  }
  if (mode !== "open" && mode !== "local") {
    return (
      <main className="app-bg grid min-h-screen place-items-center px-4 text-center text-sm text-statusRed">
        登录服务暂不可用，请检查后端连接后重试。
      </main>
    );
  }
  return mode === "local" && !identity ? <LoginPage /> : <AppLayout />;
};

const LoginRoute = () => {
  const { mode, identity, authReady } = useContext(AuthContext);
  if (!authReady) return null;
  return mode !== "local" || identity ? <Navigate to="/" replace /> : <LoginPage />;
};

const Routing = () => (
  <Routes>
    <Route path="/login" element={<LoginRoute />} />
    <Route path="/" element={<ProtectedLayout />}>
      {PAGE_REGISTRY.map(({ path, component: Component }) =>
        path === "/" ? (
          <Route key={path} index element={<Component />} />
        ) : (
          <Route key={path} path={path.slice(1)} element={<Component />} />
        ),
      )}
      <Route path="dashboard" element={<Navigate to="/" replace />} />
      <Route path="missions" element={<Navigate to="/route" replace />} />
      <Route path="inspection" element={<Navigate to="/route#inspection-records" replace />} />
      <Route path="waypoint-actions" element={<Navigate to="/route#inspection-setup" replace />} />
      <Route path="*" element={<NotFoundPage />} />
    </Route>
  </Routes>
);
export default Routing;
