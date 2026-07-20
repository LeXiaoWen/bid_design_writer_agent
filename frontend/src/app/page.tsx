"use client";

import { X } from "lucide-react";
import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { zodResolver } from "@hookform/resolvers/zod";
import { Panel, PanelGroup, PanelResizeHandle, type ImperativePanelHandle } from "react-resizable-panels";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import {
  changePassword,
  cancelChat,
  cancelBidWorkflow,
  confirmBidWorkflow,
  createConversation,
  createBidWorkflow,
  downloadBidArtifact,
  downloadBidZip,
  extractBidWorkflow,
  generateBidWorkflow,
  getBidWorkflow,
  listBidWorkflows,
  restoreCredentials,
  searchWorkbench,
  streamBidWorkflow,
} from "@/lib/api";
import { ChatWorkspace } from "@/components/ChatWorkspace";
import { ConfigDialog, type ProviderProfileDraft, type ProviderProfileValues, type WebSearchValues } from "@/components/ConfigDialog";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { AuthPanel, type AuthMode as AuthPanelMode } from "@/components/AuthPanel";
import { BidWorkflowPanel } from "@/components/BidWorkflowPanel";
import { WorkbenchSidebar } from "@/components/WorkbenchSidebar";
import { ThemePanel } from "@/components/ThemePanel";
import { useAuth } from "@/hooks/useAuth";
import { useBidWorkflow, useBidWorkflows } from "@/hooks/useBidWorkflow";
import { useChatStream } from "@/hooks/useChatStream";
import { useConfiguration } from "@/hooks/useConfiguration";
import { useProviderModels } from "@/hooks/useProviderModels";
import { useWorkbenchData } from "@/hooks/useWorkbenchData";
import { useTheme } from "@/hooks/useTheme";
import type {
  BidWorkflow,
  BidWorkflowStreamEvent,
  ChatStreamEvent,
  SearchResult,
  SearchResultKind,
  WebSearchConfig,
  WorkbenchConversation,
  WorkbenchMessage,
  WorkbenchProject,
} from "@/lib/types";
import { applyBidWorkflowStreamEvent, applyChatStreamEvent } from "@/lib/chatReducer";

const providerPresets: ProviderProfileDraft[] = [
  { provider: "OpenAI", display_name: "OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-4o" },
  { provider: "DeepSeek", display_name: "DeepSeek", base_url: "https://api.deepseek.com", model: "deepseek-v4-flash" },
  { provider: "通义千问 DashScope", display_name: "通义千问", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus" },
  { provider: "SiliconFlow", display_name: "SiliconFlow", base_url: "https://api.siliconflow.cn/v1", model: "deepseek-ai/DeepSeek-V3" },
  { provider: "OpenRouter", display_name: "OpenRouter", base_url: "https://openrouter.ai/api/v1", model: "openai/gpt-4o-mini" },
  { provider: "自定义", display_name: "自定义", base_url: "", model: "" },
];

const PROJECT_PREVIEW_CONVERSATION_LIMIT = 6;

const passwordChangeSchema = z
  .object({
    currentPassword: z.string().min(1, "请输入当前密码。"),
    newPassword: z.string().min(12, "新密码至少 12 位。"),
    confirmPassword: z.string(),
  })
  .refine((values) => values.newPassword === values.confirmPassword, {
    path: ["confirmPassword"],
    message: "两次输入的新密码不一致。",
  });

type PasswordChangeValues = z.infer<typeof passwordChangeSchema>;

function localMessage(role: "user" | "assistant", content: string, status: string): WorkbenchMessage {
  const now = new Date().toISOString();
  return {
    id: `local-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    conversation_id: "local",
    role,
    content,
    status,
    created_at: now,
    updated_at: now,
  };
}

function sanitizeFilename(value: string): string {
  return (value || "项目").replace(/[\\/:*?"<>|]/g, "_").trim() || "项目";
}

function stripExtension(value: string): string {
  return value.replace(/\.[^.]+$/, "");
}

export default function Home() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null);
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [currentProfileId, setCurrentProfileId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchKind, setSearchKind] = useState<SearchResultKind | "all">("all");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const { isStreaming, send: sendChatStream, abort: abortChatStream } = useChatStream();
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [configOpen, setConfigOpen] = useState(false);
  const [userPanelOpen, setUserPanelOpen] = useState(false);
  const {
    mode: authMode,
    backendReady: authBackendReady,
    user: authUser,
    initialize: initializeAuth,
    switchMode: switchAuthMode,
    submit: submitAuthRequest,
    logout: logoutAuthSession,
  } = useAuth(setError);
  const theme = useTheme(authMode === "ready");
  const {
    projects,
    projectConversations,
    recentConversations,
    messages,
    refreshProjects,
    refreshConversations,
    refreshMessages,
    updateMessages,
    clear: clearWorkbenchData,
    createProject: createProjectMutation,
    deleteProject: deleteProjectMutation,
    createConversation: createConversationMutation,
    deleteConversation: deleteConversationMutation,
  } = useWorkbenchData({ enabled: authMode === "ready", projectId: currentProjectId, conversationId: currentConversationId });
  const {
    profiles,
    webSearchConfig,
    error: configurationError,
    createProfile,
    updateProfile,
    updateWebSearch,
    refresh: refreshConfiguration,
    clear: clearConfiguration,
  } = useConfiguration(authMode === "ready");
  const passwordChangeForm = useForm<PasswordChangeValues>({
    resolver: zodResolver(passwordChangeSchema),
    defaultValues: { currentPassword: "", newPassword: "", confirmPassword: "" },
  });
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [projectsOpen, setProjectsOpen] = useState(true);
  const [projectConversationsOpen, setProjectConversationsOpen] = useState(true);
  const [conversationsOpen, setConversationsOpen] = useState(true);
  const {
    workflow: activeBidWorkflow,
    setWorkflow: setActiveBidWorkflow,
    isBusy: isBidBusy,
    setIsBusy: setIsBidBusy,
    error: workflowError,
  } = useBidWorkflow();
  const [bidWorkflows, setBidWorkflows] = useState<BidWorkflow[]>([]);
  const { workflows: polledBidWorkflows, error: bidWorkflowsError } = useBidWorkflows(currentConversationId, bidWorkflows);
  const [bidConfirmation, setBidConfirmation] = useState("确认");
  const [bidExtraContext, setBidExtraContext] = useState("");
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [uploadFileName, setUploadFileName] = useState("");
  const [userChatAvatar, setUserChatAvatar] = useState("我");
  const [assistantChatAvatar, setAssistantChatAvatar] = useState("AI");
  const [webSearchEnabled, setWebSearchEnabled] = useState(false);
  const [attachmentMenuOpen, setAttachmentMenuOpen] = useState(false);
  const sidebarPanelRef = useRef<ImperativePanelHandle>(null);
  const initialConversationSelectedRef = useRef(false);

  const currentProject = useMemo(() => projects.find((project) => project.id === currentProjectId) ?? null, [projects, currentProjectId]);
  const currentConversation = useMemo(
    () => [...projectConversations, ...recentConversations].find((conversation) => conversation.id === currentConversationId) ?? null,
    [projectConversations, recentConversations, currentConversationId],
  );
  const defaultProject = useMemo(
    () => projects.find((project) => !project.workspace_path && project.title === "默认项目") ?? projects.find((project) => !project.workspace_path) ?? null,
    [projects],
  );
  const projectPreviewConversations = useMemo(
    () => (currentProject?.workspace_path ? projectConversations.slice(0, PROJECT_PREVIEW_CONVERSATION_LIMIT) : []),
    [currentProject?.workspace_path, projectConversations],
  );
  const sidebarHistoryConversations = useMemo(() => {
    return recentConversations.filter((conversation) => conversation.project_id === defaultProject?.id);
  }, [defaultProject?.id, recentConversations]);
  const currentProfile = useMemo(() => profiles.find((profile) => profile.id === currentProfileId) ?? null, [profiles, currentProfileId]);
  const workflowPanel = (
    <BidWorkflowPanel
      workflow={activeBidWorkflow}
      workflows={bidWorkflows}
      currentConversationId={currentConversationId}
      confirmation={bidConfirmation}
      extraContext={bidExtraContext}
      isBusy={isBidBusy}
      onConfirmationChange={setBidConfirmation}
      onExtraContextChange={setBidExtraContext}
      onCancel={cancelWorkflow}
      onConfirm={confirmWorkflow}
      onGenerate={generateWorkflow}
      onRetry={retryWorkflow}
      onRefresh={refreshActiveWorkflow}
      onSelectWorkflow={setActiveBidWorkflow}
      onDownloadArtifact={downloadArtifact}
      onDownloadZip={downloadArtifactsZip}
    />
  );

  if (authMode !== "ready") {
    return <AuthPanel mode={authMode} backendReady={authBackendReady} error={error} onModeChange={switchAuthMode} onSubmit={submitAuth} />;
  }

  return (
    <ErrorBoundary>
    <PanelGroup className="workbench-shell" data-sidebar={sidebarCollapsed ? "collapsed" : "expanded"} data-theme={theme.activeTheme?.source ?? "system"} data-theme-mode={workspaceMode} {...themeShellAttrs} style={themeStyle} direction="horizontal" autoSaveId="bid-writer-workbench-layout">
      <Panel ref={sidebarPanelRef} id="workbench-sidebar" order={1} defaultSize={22} minSize={18} maxSize={36} collapsible collapsedSize={6} onCollapse={() => setSidebarCollapsed(true)} onExpand={() => setSidebarCollapsed(false)}>
        <WorkbenchSidebar
          collapsed={sidebarCollapsed}
          projects={projects}
          currentProjectId={currentProjectId}
          currentConversationId={currentConversationId}
          projectPreviewConversations={projectPreviewConversations}
          historyConversations={sidebarHistoryConversations}
          searchQuery={searchQuery}
          searchKind={searchKind}
          searchResults={searchResults}
          projectsOpen={projectsOpen}
          projectConversationsOpen={projectConversationsOpen}
          conversationsOpen={conversationsOpen}
          authUser={authUser}
          userPanelOpen={userPanelOpen}
          onToggleSidebar={toggleSidebar}
          onStartNewChat={startNewChat}
          onFocusSearch={() => setSearchQuery((current) => current || " ")}
          onOpenConfig={openConfigPanel}
          onSearchQueryChange={setSearchQuery}
          onSearchKindChange={setSearchKind}
          onToggleProjects={() => setProjectsOpen((current) => !current)}
          onChooseWorkspace={chooseWorkspaceDirectory}
          onSwitchProject={switchProject}
          onToggleProjectConversations={() => setProjectConversationsOpen((current) => !current)}
          onRemoveProject={removeProject}
          onOpenConversation={openConversation}
          onRemoveConversation={removeConversation}
          onToggleConversations={() => setConversationsOpen((current) => !current)}
          onToggleUserPanel={toggleUserPanel}
        />
      </Panel>
      <PanelResizeHandle className="sidebar-resize-handle" hitAreaMargins={{ coarse: 16, fine: 8 }} />
      <Panel id="workbench-chat" order={2} minSize={40}>
        <ChatWorkspace
          messages={messages}
          currentProjectTitle={currentProject?.title ?? null}
          currentConversationTitle={currentConversation?.title ?? null}
          input={input}
          onInputChange={setInput}
          onSend={() => sendMessage()}
          isStreaming={isStreaming}
          onStopStreaming={stopStreaming}
          isUploadingTender={uploadProgress !== null}
          onUploadTenderFile={uploadTenderFile}
          uploadProgress={uploadProgress}
          uploadFileName={uploadFileName}
          isConfigured={Boolean(currentProfile?.model)}
          currentProfileModel={currentProfile?.model ?? null}
          onOpenConfig={openConfigPanel}
          webSearchConfig={webSearchConfig}
          webSearchEnabled={webSearchEnabled}
          onToggleWebSearch={() => {
            if (webSearchConfig?.has_key === false) {
              setError("请先在模型配置中填写 Tavily API key。");
              return;
            }
            setWebSearchEnabled((current) => !current);
          }}
          modelMenuOpen={modelMenuOpen}
          onModelMenuOpenChange={(open) => {
            if (open) void openModelMenu();
            else setModelMenuOpen(false);
          }}
          providerModels={providerModels}
          isLoadingModels={isLoadingModels}
          onChooseModel={chooseModel}
          attachmentMenuOpen={attachmentMenuOpen}
          onAttachmentMenuOpenChange={setAttachmentMenuOpen}
          onChooseWorkspace={chooseWorkspaceDirectory}
          userAvatar={userChatAvatar}
          assistantAvatar={assistantChatAvatar}
          workflowPanel={workflowPanel}
        />

      <ConfigDialog
        open={configOpen}
        onOpenChange={setConfigOpen}
        presets={providerPresets}
        profile={configProfile}
        onSaveProfile={saveProfile}
        webSearchConfig={webSearchConfig}
        onSaveWebSearch={saveWebSearchConfig}
      />

      <Dialog.Root open={userPanelOpen} onOpenChange={setUserPanelOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="user-modal-backdrop" />
          <Dialog.Content className="user-modal" aria-describedby={undefined}>
            <div className="user-panel-header">
              <Dialog.Title asChild><strong>账号</strong></Dialog.Title>
              <Dialog.Close asChild><button type="button" aria-label="关闭账号面板">
                <X size={17} />
              </button></Dialog.Close>
            </div>
            <div className="user-panel-scroll">
              <ThemePanel
                themes={theme.themes}
                activeThemeId={theme.activeTheme?.id ?? "system"}
                busy={theme.isBusy}
                onActivate={activateAppTheme}
                onUpload={uploadAppTheme}
                onDelete={removeAppTheme}
              />
              <div className="user-detail">
                <span>当前账号</span>
                <strong>{authUser?.username ?? "未登录"}</strong>
              </div>
              <div className="user-detail">
                <span>数据范围</span>
                <strong>当前账号独立数据</strong>
              </div>
              <div className="avatar-settings">
                <label>
                  用户头像
                  <input value={userChatAvatar} onChange={(event) => updateChatAvatar("user", event.target.value)} placeholder="文字、emoji 或图片 URL" />
                </label>
                <label>
                  LLM 头像
                  <input value={assistantChatAvatar} onChange={(event) => updateChatAvatar("assistant", event.target.value)} placeholder="文字、emoji 或图片 URL" />
                </label>
              </div>
              <form className="user-login-form" onSubmit={passwordChangeForm.handleSubmit(changeCurrentPassword)}>
                <label>
                  当前密码
                  <input
                    {...passwordChangeForm.register("currentPassword")}
                    type="password"
                    autoComplete="current-password"
                  />
                  {passwordChangeForm.formState.errors.currentPassword && <small className="auth-field-error">{passwordChangeForm.formState.errors.currentPassword.message}</small>}
                </label>
                <label>
                  新密码
                  <input
                    {...passwordChangeForm.register("newPassword")}
                    type="password"
                    autoComplete="new-password"
                  />
                  {passwordChangeForm.formState.errors.newPassword && <small className="auth-field-error">{passwordChangeForm.formState.errors.newPassword.message}</small>}
                </label>
                <label>
                  确认新密码
                  <input
                    {...passwordChangeForm.register("confirmPassword")}
                    type="password"
                    autoComplete="new-password"
                  />
                  {passwordChangeForm.formState.errors.confirmPassword && <small className="auth-field-error">{passwordChangeForm.formState.errors.confirmPassword.message}</small>}
                </label>
                {passwordChangeForm.formState.errors.root && <div className="auth-field-error">{passwordChangeForm.formState.errors.root.message}</div>}
                <button type="submit" disabled={passwordChangeForm.formState.isSubmitting}>{passwordChangeForm.formState.isSubmitting ? "修改中" : "修改密码"}</button>
                <button type="button" className="user-secondary-action" onClick={restoreLegacyCredentials} disabled={passwordChangeForm.formState.isSubmitting}>恢复旧密钥备份</button>
              </form>
            </div>
            <div className="user-panel-actions">
              <button type="button" className="user-secondary-action" onClick={logoutUser}>
                退出登录
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
      </Panel>
    </PanelGroup>
    </ErrorBoundary>
  );
}
