"use client";

import { ImagePlus, Trash2 } from "lucide-react";
import { useRef, useState } from "react";

import type { ThemeAppearance, UserTheme } from "@/lib/types";
import styles from "./ThemePanel.module.css";

type ThemePanelProps = {
  themes: UserTheme[];
  activeThemeId: string;
  busy: boolean;
  onUpload: (file: File, appearance: ThemeAppearance) => Promise<unknown>;
  onActivate: (themeId: string) => Promise<unknown>;
  onDelete: (themeId: string) => Promise<unknown>;
};

export function ThemePanel({ themes, activeThemeId, busy, onUpload, onActivate, onDelete }: ThemePanelProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [appearance, setAppearance] = useState<ThemeAppearance>("auto");

  const chooseFile = async (file: File | undefined) => {
    if (!file) return;
    await onUpload(file, appearance);
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <section className={styles.section} aria-label="外观">
      <div className={styles.heading}><strong>外观</strong><span>背景仅保存在当前账号的本机数据目录</span></div>
      <div className={styles.themeList}>
        {themes.map((theme) => (
          <div className={`${styles.themeCard} ${theme.id === activeThemeId ? styles.active : ""}`} key={theme.id}>
            <button type="button" onClick={() => void onActivate(theme.id)} disabled={busy} aria-pressed={theme.id === activeThemeId}>
              <strong>{theme.name}</strong>
              <span>{theme.source === "system" ? "无背景图" : `${theme.width} × ${theme.height}`}</span>
            </button>
            {theme.source === "custom" && <button className={styles.delete} type="button" onClick={() => void onDelete(theme.id)} disabled={busy} aria-label={`删除主题 ${theme.name}`}><Trash2 size={14} /></button>}
          </div>
        ))}
      </div>
      <div className={styles.importRow}>
        <select value={appearance} onChange={(event) => setAppearance(event.target.value as ThemeAppearance)} aria-label="背景明暗模式" disabled={busy}>
          <option value="auto">自动明暗</option><option value="light">浅色界面</option><option value="dark">深色界面</option>
        </select>
        <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => void chooseFile(event.target.files?.[0])} />
        <button type="button" onClick={() => inputRef.current?.click()} disabled={busy}><ImagePlus size={15} />导入背景图</button>
      </div>
    </section>
  );
}
