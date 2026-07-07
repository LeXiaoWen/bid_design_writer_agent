"use client";

import { MessageSquareText, PanelRightOpen } from "lucide-react";
import type { ReactNode } from "react";

type WorkbenchLayoutProps = {
  mode: "chat" | "workbench";
  onModeChange: (mode: "chat" | "workbench") => void;
  chatContent: ReactNode;
  appContent: ReactNode;
};

export function WorkbenchLayout({ mode, onModeChange, chatContent, appContent }: WorkbenchLayoutProps) {
  return (
    <main className="app-shell" data-mode={mode}>
      <nav className="mode-rail" aria-label="工作区模式">
        <button
          className={mode === "chat" ? "active" : ""}
          onClick={() => onModeChange("chat")}
          title="Chat"
          aria-label="Chat"
        >
          <MessageSquareText size={18} />
        </button>
        <button
          className={mode === "workbench" ? "active" : ""}
          onClick={() => onModeChange("workbench")}
          title="工作台"
          aria-label="工作台"
        >
          <PanelRightOpen size={18} />
        </button>
      </nav>

      <section className="chat-surface">{chatContent}</section>
      <section className="workbench-surface">{appContent}</section>
    </main>
  );
}
