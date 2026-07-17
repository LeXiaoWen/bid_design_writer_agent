"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import * as Tabs from "@radix-ui/react-tabs";
import { Loader2 } from "lucide-react";
import { useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

export type AuthMode = "login" | "register";

type AuthValues = {
  username: string;
  password: string;
  confirmPassword: string;
};

type AuthPanelProps = {
  mode: AuthMode;
  backendReady: boolean;
  error: string | null;
  onModeChange: (mode: AuthMode) => void;
  onSubmit: (mode: AuthMode, values: AuthValues) => Promise<void>;
};

export function AuthPanel({ mode, backendReady, error, onModeChange, onSubmit }: AuthPanelProps) {
  const schema = useMemo(
    () =>
      z
        .object({
          username: z.string().trim().min(1, "请输入用户名。"),
          password: z.string().min(1, "请输入密码。"),
          confirmPassword: z.string(),
        })
        .superRefine((values, context) => {
          if (mode === "register" && values.password.length < 12) {
            context.addIssue({ code: z.ZodIssueCode.too_small, minimum: 12, type: "string", inclusive: true, path: ["password"], message: "密码至少 12 位。" });
          }
          if (mode === "register" && values.password !== values.confirmPassword) {
            context.addIssue({ code: z.ZodIssueCode.custom, path: ["confirmPassword"], message: "两次输入的密码不一致。" });
          }
        }),
    [mode],
  );
  const form = useForm<AuthValues>({ resolver: zodResolver(schema), defaultValues: { username: "", password: "", confirmPassword: "" } });

  useEffect(() => form.reset(), [form, mode]);

  return (
    <main className="auth-screen">
      <section className="auth-panel">
        <div className="auth-heading">
          <span>建筑设计标书方案助手</span>
          <h1>{mode === "register" ? "注册" : "登录"}</h1>
        </div>
        <Tabs.Root value={mode} onValueChange={(value) => onModeChange(value as AuthMode)}>
          <Tabs.List className="auth-tabs" aria-label="账号入口">
            <Tabs.Trigger value="login">登录</Tabs.Trigger>
            <Tabs.Trigger value="register">注册</Tabs.Trigger>
          </Tabs.List>
        </Tabs.Root>
        <form className="auth-form" onSubmit={form.handleSubmit((values) => onSubmit(mode, values))}>
          <label>
            用户名
            <input {...form.register("username")} autoComplete="username" />
            {form.formState.errors.username && <small className="auth-field-error">{form.formState.errors.username.message}</small>}
          </label>
          <label>
            密码
            <input {...form.register("password")} type="password" autoComplete={mode === "register" ? "new-password" : "current-password"} />
            {form.formState.errors.password && <small className="auth-field-error">{form.formState.errors.password.message}</small>}
          </label>
          {mode === "register" && (
            <label>
              确认密码
              <input {...form.register("confirmPassword")} type="password" autoComplete="new-password" />
              {form.formState.errors.confirmPassword && <small className="auth-field-error">{form.formState.errors.confirmPassword.message}</small>}
            </label>
          )}
          <button type="submit" disabled={form.formState.isSubmitting}>{mode === "register" ? "注册并进入" : "登录"}</button>
        </form>
        {!backendReady && (
          <div className="auth-status">
            <Loader2 size={16} className="spin-icon" />
            <span>正在连接本地后端，可先输入账号密码</span>
          </div>
        )}
        {error && <div className="auth-error">{error}</div>}
      </section>
    </main>
  );
}
