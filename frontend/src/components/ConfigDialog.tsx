"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import type { WebSearchConfig } from "@/lib/types";
import styles from "./ConfigDialog.module.css";

export type ProviderProfileDraft = {
  provider: string;
  display_name: string;
  base_url: string;
  model: string;
};

export type ProviderProfileValues = ProviderProfileDraft & { api_key: string };

export type WebSearchValues = {
  api_key: string;
  max_results: string;
  search_depth: "basic" | "advanced";
};

const profileSchema = z.object({
  provider: z.string().trim().min(1, "请选择 Provider。"),
  display_name: z.string().trim().min(1, "请输入显示名称。"),
  base_url: z.string().trim().min(1, "请输入 Base URL。"),
  model: z.string().trim().min(1, "请输入模型名称。"),
  api_key: z.string(),
});

const webSearchSchema = z.object({
  api_key: z.string(),
  max_results: z.string().regex(/^\d+$/, "请输入 1 到 10 的整数。").refine((value) => Number(value) >= 1 && Number(value) <= 10, "结果数量应为 1 到 10。"),
  search_depth: z.enum(["basic", "advanced"]),
});

type ConfigDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  presets: readonly ProviderProfileDraft[];
  profile: ProviderProfileDraft;
  onSaveProfile: (values: ProviderProfileValues) => Promise<void>;
  webSearchConfig: WebSearchConfig | null;
  onSaveWebSearch: (values: WebSearchValues) => Promise<WebSearchConfig>;
};

function profileValues(profile: ProviderProfileDraft): ProviderProfileValues {
  return { ...profile, api_key: "" };
}

function webSearchValues(config: WebSearchConfig | null): WebSearchValues {
  return { api_key: "", max_results: String(config?.max_results ?? 5), search_depth: config?.search_depth === "advanced" ? "advanced" : "basic" };
}

export function ConfigDialog({ open, onOpenChange, presets, profile, onSaveProfile, webSearchConfig, onSaveWebSearch }: ConfigDialogProps) {
  const profileForm = useForm<ProviderProfileValues>({ resolver: zodResolver(profileSchema), defaultValues: profileValues(profile) });
  const webSearchForm = useForm<WebSearchValues>({ resolver: zodResolver(webSearchSchema), defaultValues: webSearchValues(webSearchConfig) });
  const [webSearchMessage, setWebSearchMessage] = useState("");

  useEffect(() => {
    if (!open) return;
    profileForm.reset(profileValues(profile));
    webSearchForm.reset(webSearchValues(webSearchConfig));
    setWebSearchMessage("");
  }, [open, profile, profileForm, webSearchConfig, webSearchForm]);

  const selectPreset = (provider: string) => {
    const preset = presets.find((item) => item.provider === provider) ?? presets[0];
    if (!preset) return;
    profileForm.reset({ ...preset, api_key: profileForm.getValues("api_key") });
  };

  const saveProfile = profileForm.handleSubmit(async (values) => {
    profileForm.clearErrors("root");
    try {
      await onSaveProfile(values);
    } catch (caught) {
      profileForm.setError("root", { message: caught instanceof Error ? caught.message : String(caught) });
    }
  });

  const saveWebSearch = webSearchForm.handleSubmit(async (values) => {
    webSearchForm.clearErrors("root");
    setWebSearchMessage("");
    try {
      const updated = await onSaveWebSearch(values);
      webSearchForm.reset(webSearchValues(updated));
      setWebSearchMessage("搜索配置已保存。");
    } catch (caught) {
      webSearchForm.setError("root", { message: caught instanceof Error ? caught.message : String(caught) });
    }
  });

  const isSavingSearch = webSearchForm.formState.isSubmitting;
  const webSearchSource = webSearchConfig?.source;
  const webSearchStatus = webSearchSource === "system" ? "已配置（系统凭据库）" : webSearchSource === "env" ? "已配置（环境变量）" : "未配置";
  const webSearchPlaceholder = webSearchSource === "system" ? "留空则保留系统凭据库中的 key" : webSearchSource === "env" ? "填写后保存到本地（替代环境变量）" : "填写 Tavily API key";

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.backdrop} />
        <Dialog.Content className={styles.modal} aria-describedby="config-modal-description">
          <div className={styles.header}>
            <div>
              <Dialog.Title asChild><strong>模型与工具配置</strong></Dialog.Title>
              <Dialog.Description asChild><span id="config-modal-description">模型 API 和联网搜索仅保存在本机</span></Dialog.Description>
            </div>
            <Dialog.Close asChild><button type="button" aria-label="关闭模型配置"><X size={17} /></button></Dialog.Close>
          </div>
          <div className={styles.scrollArea}>
            <form className={styles.section} onSubmit={saveProfile}>
              <div className={styles.sectionTitle}>模型配置</div>
              <div className={styles.grid}>
                <label>
                  Provider
                  <select {...profileForm.register("provider")} onChange={(event) => selectPreset(event.target.value)}>
                    {presets.map((preset) => <option key={preset.provider}>{preset.provider}</option>)}
                  </select>
                  {profileForm.formState.errors.provider && <small className={styles.fieldError}>{profileForm.formState.errors.provider.message}</small>}
                </label>
                <label>
                  显示名称
                  <input {...profileForm.register("display_name")} />
                  {profileForm.formState.errors.display_name && <small className={styles.fieldError}>{profileForm.formState.errors.display_name.message}</small>}
                </label>
                <label>
                  Base URL
                  <input {...profileForm.register("base_url")} />
                  {profileForm.formState.errors.base_url && <small className={styles.fieldError}>{profileForm.formState.errors.base_url.message}</small>}
                </label>
                <label>
                  Model
                  <input {...profileForm.register("model")} />
                  {profileForm.formState.errors.model && <small className={styles.fieldError}>{profileForm.formState.errors.model.message}</small>}
                </label>
                <label className={styles.apiKeyField}>
                  API key
                  <input {...profileForm.register("api_key")} type="password" placeholder="保存到当前账号本地数据库" />
                </label>
              </div>
              {profileForm.formState.errors.root && <div className={`${styles.message} ${styles.error}`}>{profileForm.formState.errors.root.message}</div>}
              <div className={styles.actions}><button type="submit" disabled={profileForm.formState.isSubmitting}>{profileForm.formState.isSubmitting ? "保存中" : "保存模型"}</button></div>
            </form>

            <form className={styles.section} onSubmit={saveWebSearch}>
              <div className={styles.sectionTitle}><span>联网搜索</span><em>{webSearchStatus}</em></div>
              {webSearchSource === "env" && <div className={styles.message}>当前 key 来自环境变量（.env 文件），优先级低于本地保存的 key。在下方填写新 key 保存后将覆盖。</div>}
              <div className={styles.grid}>
                <label className={styles.apiKeyField}>
                  Tavily API key
                  <input {...webSearchForm.register("api_key")} type="password" placeholder={webSearchPlaceholder} disabled={isSavingSearch} />
                </label>
                <label>
                  结果数量
                  <input {...webSearchForm.register("max_results")} type="number" min={1} max={10} disabled={isSavingSearch} />
                  {webSearchForm.formState.errors.max_results && <small className={styles.fieldError}>{webSearchForm.formState.errors.max_results.message}</small>}
                </label>
                <label>
                  搜索深度
                  <select {...webSearchForm.register("search_depth")} disabled={isSavingSearch}><option value="basic">basic</option><option value="advanced">advanced</option></select>
                </label>
              </div>
              {webSearchMessage && <div className={styles.message}>{webSearchMessage}</div>}
              {webSearchForm.formState.errors.root && <div className={`${styles.message} ${styles.error}`}>{webSearchForm.formState.errors.root.message}</div>}
              <div className={styles.actions}><button type="submit" disabled={isSavingSearch}>{isSavingSearch ? "保存中" : "保存搜索"}</button></div>
            </form>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
