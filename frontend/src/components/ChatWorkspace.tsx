"use client";

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { ChevronRight, FileText, FolderOpen, Globe2, Loader2, Plus, Send, ShieldCheck, Square } from "lucide-react";
import { useRef, type ChangeEvent, type ReactNode } from "react";

import { MarkdownPane } from "@/components/MarkdownPane";
import { formatMessageUsage } from "@/lib/messageUsage";
import type { ProviderModel, WebSearchConfig, WorkbenchMessage } from "@/lib/types";
import styles from "./ChatWorkspace.module.css";

type ChatWorkspaceProps = {
  messages: WorkbenchMessage[];
  currentProjectTitle: string | null;
  currentConversationTitle: string | null;
  input: string;
  onInputChange: (value: string) => void;
  onSend: () => Promise<void>;
  isStreaming: boolean;
  onStopStreaming: () => void;
  isBidBusy: boolean;
  onUploadTenderFile: (event: ChangeEvent<HTMLInputElement>) => void;
  uploadProgress: number | null;
  uploadFileName: string;
  isConfigured: boolean;
  currentProfileModel: string | null;
  onOpenConfig: () => void;
  webSearchConfig: WebSearchConfig | null;
  webSearchEnabled: boolean;
  onToggleWebSearch: () => void;
  modelMenuOpen: boolean;
  onModelMenuOpenChange: (open: boolean) => void;
  providerModels: ProviderModel[];
  isLoadingModels: boolean;
  onChooseModel: (modelId: string) => void;
  attachmentMenuOpen: boolean;
  onAttachmentMenuOpenChange: (open: boolean) => void;
  onChooseWorkspace: () => void;
  userAvatar: string;
  assistantAvatar: string;
  workflowPanel: ReactNode;
};

function formatMessageTime(value: string): string {
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return "";
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(timestamp);
}

function avatarContent(value: string) {
  const trimmed = value.trim();
  if (/^(https?:|data:image\/|blob:)/i.test(trimmed)) return <img src={trimmed} alt="" />;
  return trimmed.slice(0, 4) || "AI";
}

function estimatedContextCharacters(messages: WorkbenchMessage[], assistantIndex: number): number {
  return messages.slice(0, assistantIndex).reduce((total, message) => total + message.content.length, 0);
}

export function ChatWorkspace({
  messages,
  currentProjectTitle,
  currentConversationTitle,
  input,
  onInputChange,
  onSend,
  isStreaming,
  onStopStreaming,
  isBidBusy,
  onUploadTenderFile,
  uploadProgress,
  uploadFileName,
  isConfigured,
  currentProfileModel,
  onOpenConfig,
  webSearchConfig,
  webSearchEnabled,
  onToggleWebSearch,
  modelMenuOpen,
  onModelMenuOpenChange,
  providerModels,
  isLoadingModels,
  onChooseModel,
  attachmentMenuOpen,
  onAttachmentMenuOpenChange,
  onChooseWorkspace,
  userAvatar,
  assistantAvatar,
  workflowPanel,
}: ChatWorkspaceProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const placeholder = isConfigured ? "随心输入或者上传招标文件" : "先配置模型 API";
  const submit = () => void onSend();
  const webSearchUnavailable = webSearchConfig?.has_key === false;

  const composerControls = (
    <div className="composer-toolbar">
      <div className="toolbar-left">
        <input ref={fileInputRef} type="file" accept=".pdf,.docx,.txt,.md" className="hidden-file-input" onChange={onUploadTenderFile} />
        <DropdownMenu.Root open={attachmentMenuOpen} onOpenChange={onAttachmentMenuOpenChange}>
          <DropdownMenu.Trigger asChild><button type="button" className="attachment-add-button" disabled={isBidBusy} aria-label="添加"><Plus size={18} /></button></DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content className="attachment-menu" side="top" align="start" sideOffset={8}>
              <DropdownMenu.Item className="attachment-menu-item" disabled={isBidBusy} onSelect={() => fileInputRef.current?.click()}>
                <FileText size={16} />
                <span>上传招标文件</span>
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
        {uploadProgress !== null && (
          <div className="upload-progress" title={uploadFileName}>
            <span>{uploadProgress}%</span>
            <div><i style={{ width: `${uploadProgress}%` }} /></div>
          </div>
        )}
        <button type="button" className={isConfigured ? "access-button configured" : "access-button"} onClick={onOpenConfig}>
          <ShieldCheck size={18} />
          <span>{isConfigured ? "模型已配置" : "配置模型"}</span>
          <ChevronRight size={16} />
        </button>
        <button
          type="button"
          className={webSearchUnavailable ? "web-search-toggle disabled" : webSearchEnabled ? "web-search-toggle active" : "web-search-toggle"}
          onClick={onToggleWebSearch}
          aria-pressed={webSearchEnabled}
          title={webSearchUnavailable ? "请先配置 Tavily API key" : "使用 Tavily 联网搜索"}
        >
          <Globe2 size={17} />
          <span>联网搜索</span>
        </button>
      </div>
      <div className="toolbar-right">
        <DropdownMenu.Root open={modelMenuOpen} onOpenChange={onModelMenuOpenChange}>
          <DropdownMenu.Trigger asChild>
            <button type="button" className="model-select">
              {currentProfileModel ?? "选择模型"}
              <ChevronRight className={modelMenuOpen ? "chevron open" : "chevron"} size={15} />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content className="model-menu" side="top" align="end" sideOffset={8}>
              {isLoadingModels ? (
                <div className="model-menu-status"><Loader2 size={14} />拉取模型中</div>
              ) : providerModels.length === 0 ? (
                <div className="model-menu-status">未返回模型列表</div>
              ) : providerModels.map((model) => (
                <DropdownMenu.Item className={model.id === currentProfileModel ? "model-option active" : "model-option"} key={model.id} onSelect={() => onChooseModel(model.id)}>
                  {model.name || model.id}
                </DropdownMenu.Item>
              ))}
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
        {isStreaming ? (
          <button type="button" className="send-round" onClick={onStopStreaming} aria-label="停止生成"><Square size={17} /></button>
        ) : (
          <button type="submit" className="send-round" disabled={!input.trim()} aria-label="发送"><Send size={18} /></button>
        )}
      </div>
    </div>
  );

  const composer = (className: string, rows: number, footer?: ReactNode) => (
    <form className={`composer ${className}`} onSubmit={(event) => { event.preventDefault(); submit(); }}>
      <textarea
        value={input}
        onChange={(event) => onInputChange(event.target.value)}
        placeholder={placeholder}
        rows={rows}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
      />
      {composerControls}
      {footer}
    </form>
  );

  return (
    <section className={`${styles.workspace} chat-workspace`}>
      {messages.length === 0 ? (
        <div className="landing-stage">
          <h1>今天想聊什么？</h1>
          {composer("hero-composer", 2, (
            <button type="button" className="choose-project" onClick={onChooseWorkspace}>
              <FolderOpen size={16} />
              <span>{currentProjectTitle ? `当前工作目录 · ${currentProjectTitle}` : "选择项目工作目录"}</span>
            </button>
          ))}
        </div>
      ) : (
        <>
          <div className="messages">
            <div className="conversation-title"><span>{currentProjectTitle ?? "默认项目"}</span><h1>{currentConversationTitle ?? "新对话"}</h1></div>
            {messages.map((message, index) => (
              <article className={`message-row ${message.role}`} key={message.id}>
                <div className="avatar chat-avatar">{avatarContent(message.role === "user" ? userAvatar : assistantAvatar)}</div>
                <div className="message-bubble">
                  <div className="message-meta"><span>{message.role === "user" ? "用户" : "LLM"}</span><time>{formatMessageTime(message.created_at)}</time></div>
                  {message.role === "assistant" ? <MarkdownPane content={message.content} empty={message.status === "streaming" ? "正在生成..." : "暂无内容"} /> : <p>{message.content}</p>}
                  {message.role === "assistant" && <div className={styles.usage}>{formatMessageUsage(message.usage, estimatedContextCharacters(messages, index))}</div>}
                  {message.status === "streaming" && <span className="message-status"><Loader2 size={14} />streaming</span>}
                  {message.status === "interrupted" && <span className="message-status">interrupted</span>}
                  {message.status === "error" && <span className="message-status error">error</span>}
                </div>
              </article>
            ))}
            {workflowPanel}
          </div>
          {composer("docked-composer", 1)}
        </>
      )}
    </section>
  );
}
