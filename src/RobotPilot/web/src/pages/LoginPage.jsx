import React, { useContext, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { AuthContext } from "../app/App";

const API_BASE = "";

const LoginPage = () => {
  const { mode, identity, setIdentity } = useContext(AuthContext);
  const location = useLocation();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (mode !== "local") return <Navigate to="/" replace />;
  if (identity) return <Navigate to="/" replace />;

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const response = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      if (!response.ok) {
        setError(
          response.status === 429
            ? "尝试次数过多，请稍后再试。"
            : "用户名或密码不正确。",
        );
        return;
      }
      const meResponse = await fetch(`${API_BASE}/api/v1/auth/me`, {
        credentials: "include",
        cache: "no-store",
      });
      if (!meResponse.ok) throw new Error("登录状态无法确认，请重试。");
      setIdentity(await meResponse.json());
      navigate(location.state?.from || "/", { replace: true });
    } catch (requestError) {
      setError(requestError.message || "无法连接到登录服务。");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-shell app-bg flex min-h-screen items-center justify-center px-4 py-10">
      <div className="login-card w-full max-w-[440px] rounded-[28px] border border-borderSubtle bg-bgCard/90 p-6 shadow-2xl backdrop-blur-xl sm:p-9">
        <div className="mb-8 flex items-center gap-3">
          <span className="relative flex h-12 w-12 items-center justify-center overflow-hidden rounded-2xl bg-themeBlue text-white shadow-lg shadow-themeBlue/25">
            <span className="absolute inset-0 bg-gradient-to-br from-violet-500 via-purple-500 to-pink-400" />
            <svg
              className="relative h-7 w-7"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.7"
              aria-hidden="true"
            >
              <rect x="4.5" y="7" width="15" height="11" rx="4" />
              <path
                d="M9 7V5m6 2V5M9 13h.01M15 13h.01M9 17h6"
                strokeLinecap="round"
              />
            </svg>
          </span>
          <div>
            <p className="font-[RobotoMono] text-[10px] font-semibold uppercase tracking-[0.2em] text-themeTextGray">
              RobotPilot
            </p>
            <p className="mt-1 text-sm text-textWhiteActive">机器人管理平台</p>
          </div>
        </div>

        <div className="mb-7">
          <p className="mb-2 font-[RobotoMono] text-[10px] font-semibold uppercase tracking-[0.18em] text-themeBlue">
            安全访问
          </p>
          <h1 className="text-3xl font-bold tracking-tight text-textWhiteHover">
            欢迎回来
          </h1>
          <p className="mt-2 text-sm leading-6 text-themeTextGray">
            登录以查看机器人状态并管理任务。
          </p>
        </div>

        <form onSubmit={submit} className="grid gap-5">
          <label className="grid gap-2 text-sm font-medium text-textWhiteActive">
            用户名
            <input
              autoFocus
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
              maxLength={80}
              className="login-input min-h-12 rounded-xl border border-borderSubtle bg-bgBase/70 px-4 text-base text-textWhiteHover outline-none transition focus:border-themeBlue focus:ring-4 focus:ring-themeBlue/15"
              placeholder="输入用户名"
            />
          </label>
          <label className="grid gap-2 text-sm font-medium text-textWhiteActive">
            密码
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              maxLength={1024}
              className="login-input min-h-12 rounded-xl border border-borderSubtle bg-bgBase/70 px-4 text-base text-textWhiteHover outline-none transition focus:border-themeBlue focus:ring-4 focus:ring-themeBlue/15"
              placeholder="输入密码"
            />
          </label>
          {error && (
            <p
              role="alert"
              className="rounded-xl border border-statusRed/25 bg-statusRed/10 px-3 py-2.5 text-sm text-statusRed"
            >
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={submitting || !username || !password}
            className="mt-1 flex min-h-12 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 via-purple-600 to-pink-500 px-4 font-semibold text-white shadow-lg shadow-themeBlue/20 transition hover:brightness-110 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-themeBlue/30 disabled:cursor-wait disabled:opacity-60"
          >
            {submitting ? "正在登录…" : "登录"}
            {!submitting && <span aria-hidden="true">→</span>}
          </button>
        </form>

        <div className="mt-7 flex items-center gap-2 border-t border-borderSubtle pt-5 font-[RobotoMono] text-[10px] text-themeTextGray/70">
          <span className="h-1.5 w-1.5 rounded-full bg-statusGreen" />
          单机器人安全会话
        </div>
      </div>
    </main>
  );
};

export default LoginPage;
