"use client";

import { useCallback, useState } from "react";

import { getAuthStatus, getMe, loginAuth, logoutAuth, registerAuth, setApiBaseUrl, setAuthContext } from "@/lib/api";
import type { AuthUser } from "@/lib/types";

export type AuthMode = "login" | "register";
type AuthStateMode = AuthMode | "ready";

const AUTH_TOKEN_KEY = "ai-workbench-auth-token";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function getAuthStatusWithRetry() {
  let lastError: unknown = null;
  for (let attempt = 0; attempt < 180; attempt += 1) {
    try {
      return await getAuthStatus();
    } catch (caught) {
      lastError = caught;
      const message = caught instanceof Error ? caught.message : String(caught);
      if (!message.includes("无法连接本地后端")) throw caught;
      await sleep(attempt === 0 ? 100 : 500);
    }
  }
  throw lastError instanceof Error ? lastError : new Error("本地后端启动超时，请重新打开应用。");
}

export function useAuth(onError: (message: string | null) => void) {
  const [mode, setMode] = useState<AuthStateMode>("login");
  const [backendReady, setBackendReady] = useState(false);
  const [user, setUser] = useState<AuthUser | null>(null);

  const initialize = useCallback(async (): Promise<AuthUser | null> => {
    try {
      const [appSecret, savedToken] = await Promise.all([
        window.bidDesignWriterDesktop?.getAppAuthSecret?.() ?? Promise.resolve(null),
        Promise.resolve(window.sessionStorage.getItem(AUTH_TOKEN_KEY)),
      ]);
      setApiBaseUrl(await (window.bidDesignWriterDesktop?.getBackendUrl?.() ?? Promise.resolve(null)));
      setAuthContext({ appSecret, token: savedToken });
      const status = await getAuthStatusWithRetry();
      setBackendReady(true);
      onError(null);
      if (!status.authenticated || !savedToken) return null;
      const nextUser = await getMe();
      setUser(nextUser);
      setMode("ready");
      return nextUser;
    } catch (caught) {
      setBackendReady(false);
      setMode("login");
      onError(caught instanceof Error ? caught.message : String(caught));
      return null;
    }
  }, [onError]);

  const switchMode = useCallback((nextMode: AuthMode) => {
    setMode(nextMode);
    onError(null);
  }, [onError]);

  const submit = useCallback(async (nextMode: AuthMode, values: { username: string; password: string }): Promise<AuthUser | null> => {
    if (!backendReady) {
      onError("正在连接本地后端，请稍候。");
      return null;
    }
    try {
      const response = nextMode === "register"
        ? await registerAuth({ username: values.username.trim(), password: values.password })
        : await loginAuth({ username: values.username.trim(), password: values.password });
      window.sessionStorage.setItem(AUTH_TOKEN_KEY, response.token);
      setAuthContext({ token: response.token });
      const nextUser = await getMe();
      setUser(nextUser);
      setMode("ready");
      onError(null);
      return nextUser;
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : String(caught));
      return null;
    }
  }, [backendReady, onError]);

  const logout = useCallback(async () => {
    try {
      await logoutAuth();
    } catch {
      // Clear the local session even when the backend is already unavailable.
    }
    window.sessionStorage.removeItem(AUTH_TOKEN_KEY);
    setAuthContext({ token: null });
    setUser(null);
    setMode("login");
  }, []);

  return { mode, backendReady, user, initialize, switchMode, submit, logout };
}
