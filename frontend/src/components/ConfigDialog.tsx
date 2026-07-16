"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { FormEvent } from "react";

import type { WebSearchConfig } from "@/lib/types";
import styles from "./ConfigDialog.module.css";

export type ProviderProfileDraft = {
  provider: string;
  display_name: string;
  base_url: string;
  model: string;
};

export type WebSearchDraft = {
  api_key: string;
  max_results: string;
  search_depth: string;
};

type ConfigDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  presets: readonly ProviderProfileDraft[];
  profile: ProviderProfileDraft;
  apiKey: string;
  onProfileChange: (profile: ProviderProfileDraft) => void;
  onApiKeyChange: (value: string) => void;
  onPresetChange: (provider: string) => void;
  onSaveProfile: (event: FormEvent) => void;
  webSearchConfig: WebSearchConfig | null;
  webSearchForm: WebSearchDraft;
  webSearchSaveState: "idle" | "saving" | "saved" | "error";
  webSearchSaveMessage: string;
  onWebSearchFormChange: (form: WebSearchDraft) => void;
  onSaveWebSearch: (event: FormEvent) => void;
};

export function ConfigDialog({
  open,
  onOpenChange,
  presets,
  profile,
  apiKey,
  onProfileChange,
  onApiKeyChange,
  onPresetChange,
  onSaveProfile,
  webSearchConfig,
  webSearchForm,
  webSearchSaveState,
  webSearchSaveMessage,
  onWebSearchFormChange,
  onSaveWebSearch,
}: ConfigDialogProps) {
  const isSavingSearch = webSearchSaveState === "saving";
  const webSearchSource = webSearchConfig?.source;
  const webSearchStatus = webSearchSource === "system"
    ? "已配置（系统凭据库）"
    : webSearchSource === "env"
      ? "已配置（环境变量）"
      : "未配置";
  const webSearchPlaceholder = webSearchSource === "system"
    ? "留空则保留系统凭据库中的 key"
    : webSearchSource === "env"
      ? "填写后保存到本地（替代环境变量）"
      : "填写 Tavily API key";

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
            <form className={styles.section} onSubmit={onSaveProfile}>
              <div className={styles.sectionTitle}>模型配置</div>
              <div className={styles.grid}>
                <label>
                  Provider
                  <select value={profile.provider} onChange={(event) => onPresetChange(event.target.value)}>
                    {presets.map((preset) => <option key={preset.provider}>{preset.provider}</option>)}
                  </select>
                </label>
                <label>
                  显示名称
                  <input value={profile.display_name} onChange={(event) => onProfileChange({ ...profile, display_name: event.target.value })} />
                </label>
                <label>
                  Base URL
                  <input value={profile.base_url} onChange={(event) => onProfileChange({ ...profile, base_url: event.target.value })} />
                </label>
                <label>
                  Model
                  <input value={profile.model} onChange={(event) => onProfileChange({ ...profile, model: event.target.value })} />
                </label>
                <label className={styles.apiKeyField}>
                  API key
                  <input value={apiKey} type="password" onChange={(event) => onApiKeyChange(event.target.value)} placeholder="保存到当前账号本地数据库" />
                </label>
              </div>
              <div className={styles.actions}><button type="submit">保存模型</button></div>
            </form>

            <form className={styles.section} onSubmit={onSaveWebSearch}>
              <div className={styles.sectionTitle}><span>联网搜索</span><em>{webSearchStatus}</em></div>
              {webSearchSource === "env" && (
                <div className={styles.message}>当前 key 来自环境变量（.env 文件），优先级低于本地保存的 key。在下方填写新 key 保存后将覆盖。</div>
              )}
              <div className={styles.grid}>
                <label className={styles.apiKeyField}>
                  Tavily API key
                  <input
                    value={webSearchForm.api_key}
                    type="password"
                    onChange={(event) => onWebSearchFormChange({ ...webSearchForm, api_key: event.target.value })}
                    placeholder={webSearchPlaceholder}
                    disabled={isSavingSearch}
                  />
                </label>
                <label>
                  结果数量
                  <input value={webSearchForm.max_results} type="number" min={1} max={10} onChange={(event) => onWebSearchFormChange({ ...webSearchForm, max_results: event.target.value })} disabled={isSavingSearch} />
                </label>
                <label>
                  搜索深度
                  <select value={webSearchForm.search_depth} onChange={(event) => onWebSearchFormChange({ ...webSearchForm, search_depth: event.target.value })} disabled={isSavingSearch}>
                    <option value="basic">basic</option>
                    <option value="advanced">advanced</option>
                  </select>
                </label>
              </div>
              {webSearchSaveMessage && <div className={`${styles.message} ${webSearchSaveState === "error" ? styles.error : ""}`}>{webSearchSaveMessage}</div>}
              <div className={styles.actions}>
                <button type="submit" disabled={isSavingSearch}>{isSavingSearch ? "保存中" : "保存搜索"}</button>
              </div>
            </form>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
