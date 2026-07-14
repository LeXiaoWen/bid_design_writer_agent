"use client";

import {
  CheckCircle2,
  ChevronRight,
  Download,
  FileText,
  FolderOpen,
  Globe2,
  History,
  Loader2,
  MessageSquarePlus,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Search,
  Send,
  Settings2,
  ShieldCheck,
  Square,
  Trash2,
  X,
} from "lucide-react";
import { ChangeEvent, CSSProperties, FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  changePassword,
  cancelChat,
  cancelBidWorkflow,
  confirmBidWorkflow,
  createConversation,
  createBidWorkflow,
  createProject,
  createProviderProfile,
  deleteConversation,
  deleteProject,
  downloadBidArtifact,
  downloadBidZip,
  extractBidWorkflow,
  generateBidWorkflow,
  getAuthStatus,
  getBidWorkflow,
  getMe,
  getWebSearchConfig,
  listConversations,
  listBidWorkflows,
  listMessages,
  listProviderModels,
  listProjects,
  listProviderProfiles,
  loginAuth,
  logoutAuth,
  searchWorkbench,
  setApiBaseUrl,
  setAuthContext,
  registerAuth,
  streamChat,
  updateProviderProfile,
  updateWebSearchConfig,
} from "@/lib/api";
import { MarkdownPane } from "@/components/MarkdownPane";
import type {
  AuthUser,
  BidWorkflow,
  ChatStreamEvent,
  ProviderModel,
  ProviderProfile,
  SearchResult,
  WebSearchConfig,
  WorkbenchConversation,
  WorkbenchMessage,
  WorkbenchProject,
} from "@/lib/types";
import { applyChatStreamEvent } from "@/lib/chatReducer";

const providerPresets = [
  { provider: "OpenAI", display_name: "OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-4o" },
  { provider: "DeepSeek", display_name: "DeepSeek", base_url: "https://api.deepseek.com", model: "deepseek-v4-flash" },
  { provider: "通义千问 DashScope", display_name: "通义千问", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus" },
  { provider: "SiliconFlow", display_name: "SiliconFlow", base_url: "https://api.siliconflow.cn/v1", model: "deepseek-ai/DeepSeek-V3" },
  { provider: "OpenRouter", display_name: "OpenRouter", base_url: "https://openrouter.ai/api/v1", model: "openai/gpt-4o-mini" },
  { provider: "自定义", display_name: "自定义", base_url: "", model: "" },
];

type AuthMode = "register" | "login" | "ready";

const emptyAuthForm = {
  username: "",
  password: "",
  confirmPassword: "",
};
const PROJECT_PREVIEW_CONVERSATION_LIMIT = 6;

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

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function getAuthStatusWithRetry() {
  let lastError: unknown = null;
  const maxAttempts = 180;
  const delayMs = 500;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    try {
      return await getAuthStatus();
    } catch (caught) {
      lastError = caught;
      const message = caught instanceof Error ? caught.message : String(caught);
      if (!message.includes("无法连接本地后端")) throw caught;
      await sleep(attempt === 0 ? 100 : delayMs);
    }
  }
  throw lastError instanceof Error ? lastError : new Error("本地后端启动超时，请重新打开应用。");
}

function relativeTime(value: string): string {
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return "";
  const diffMs = Date.now() - timestamp;
  const minutes = Math.max(0, Math.round(diffMs / 60_000));
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} 小时`;
  const days = Math.round(hours / 24);
  return `${days} 天`;
}

function formatMessageTime(value: string): string {
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(timestamp);
}

function sanitizeFilename(value: string): string {
  return (value || "项目").replace(/[\\/:*?"<>|]/g, "_").trim() || "项目";
}

function stripExtension(value: string): string {
  return value.replace(/\.[^.]+$/, "");
}

function userInitials(user: AuthUser | null): string {
  const name = user?.username.trim();
  if (!name) return "未";
  return name.slice(0, 2).toUpperCase();
}

function workflowStatusText(status: BidWorkflow["status"]): string {
  const labels: Record<BidWorkflow["status"], string> = {
    uploaded: "已上传",
    extracting: "阶段一提取中",
    extraction_ready: "待确认",
    generating: "阶段二生成中",
    completed: "已完成",
    failed: "执行失败",
    cancelled: "已取消",
  };
  return labels[status];
}

function avatarContent(value: string) {
  const trimmed = value.trim();
  if (/^(https?:|data:image\/|blob:)/i.test(trimmed)) {
    return <img src={trimmed} alt="" />;
  }
  return trimmed.slice(0, 4) || "AI";
}

export default function Home() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(300);
  const [isResizingSidebar, setIsResizingSidebar] = useState(false);
  const [projects, setProjects] = useState<WorkbenchProject[]>([]);
  const [projectConversations, setProjectConversations] = useState<WorkbenchConversation[]>([]);
  const [recentConversations, setRecentConversations] = useState<WorkbenchConversation[]>([]);
  const [messages, setMessages] = useState<WorkbenchMessage[]>([]);
  const [profiles, setProfiles] = useState<ProviderProfile[]>([]);
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null);
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [currentProfileId, setCurrentProfileId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [configOpen, setConfigOpen] = useState(false);
  const [userPanelOpen, setUserPanelOpen] = useState(false);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [authBackendReady, setAuthBackendReady] = useState(false);
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [authForm, setAuthForm] = useState(emptyAuthForm);
  const [passwordForm, setPasswordForm] = useState({ currentPassword: "", newPassword: "", confirmPassword: "" });
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [providerModels, setProviderModels] = useState<ProviderModel[]>([]);
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [projectsOpen, setProjectsOpen] = useState(true);
  const [projectConversationsOpen, setProjectConversationsOpen] = useState(true);
  const [conversationsOpen, setConversationsOpen] = useState(true);
  const [profileForm, setProfileForm] = useState(providerPresets[0]);
  const [apiKey, setApiKey] = useState("");
  const [webSearchConfig, setWebSearchConfig] = useState<WebSearchConfig | null>(null);
  const [webSearchForm, setWebSearchForm] = useState({ api_key: "", max_results: "5", search_depth: "basic" });
  const [webSearchSaveState, setWebSearchSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [webSearchSaveMessage, setWebSearchSaveMessage] = useState("");
  const [activeBidWorkflow, setActiveBidWorkflow] = useState<BidWorkflow | null>(null);
  const [bidConfirmation, setBidConfirmation] = useState("确认");
  const [bidExtraContext, setBidExtraContext] = useState("");
  const [isBidBusy, setIsBidBusy] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [uploadFileName, setUploadFileName] = useState("");
  const [userChatAvatar, setUserChatAvatar] = useState("我");
  const [assistantChatAvatar, setAssistantChatAvatar] = useState("AI");
  const [webSearchEnabled, setWebSearchEnabled] = useState(false);
  const [attachmentMenuOpen, setAttachmentMenuOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

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

  useEffect(() => {
    void initializeAuth();
  }, []);

  useEffect(() => {
    const handleAuthExpired = () => {
      void logoutUser();
      setError("登录会话已失效，请重新登录。");
    };
    window.addEventListener("ai-workbench-auth-expired", handleAuthExpired);
    return () => window.removeEventListener("ai-workbench-auth-expired", handleAuthExpired);
  }, []);

  useEffect(() => {
    const savedWidth = Number(window.localStorage.getItem("bid-writer-sidebar-width"));
    if (Number.isFinite(savedWidth) && savedWidth >= 250 && savedWidth <= 440) {
      setSidebarWidth(savedWidth);
    }
  }, []);

  useEffect(() => {
    window.localStorage.setItem("bid-writer-sidebar-width", String(sidebarWidth));
  }, [sidebarWidth]);

  useEffect(() => {
    if (!isResizingSidebar) return;

    const resizeSidebar = (event: PointerEvent) => {
      setSidebarWidth(Math.min(440, Math.max(250, event.clientX)));
    };
    const stopResizing = () => setIsResizingSidebar(false);

    document.addEventListener("pointermove", resizeSidebar);
    document.addEventListener("pointerup", stopResizing);
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    return () => {
      document.removeEventListener("pointermove", resizeSidebar);
      document.removeEventListener("pointerup", stopResizing);
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
    };
  }, [isResizingSidebar]);

  useEffect(() => {
    setUserChatAvatar(window.localStorage.getItem("bid-writer-user-avatar") || "我");
    setAssistantChatAvatar(window.localStorage.getItem("bid-writer-assistant-avatar") || "AI");
  }, []);

  async function initializeAuth() {
    try {
      const [appSecret, savedToken] = await Promise.all([
        window.bidDesignWriterDesktop?.getAppAuthSecret?.() ?? Promise.resolve(null),
        Promise.resolve(window.sessionStorage.getItem("ai-workbench-auth-token")),
      ]);
      const backendUrl = await (window.bidDesignWriterDesktop?.getBackendUrl?.() ?? Promise.resolve(null));
      setApiBaseUrl(backendUrl);
      setAuthContext({ appSecret, token: savedToken });
      const status = await getAuthStatusWithRetry();
      setAuthBackendReady(true);
      setError(null);
      if (status.authenticated && savedToken) {
        const user = await getMe();
        setAuthUser(user);
        setAuthMode("ready");
        await bootstrap();
        return;
      }
    } catch (caught) {
      setAuthBackendReady(false);
      setAuthMode("login");
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  function switchAuthMode(nextMode: "login" | "register") {
    setAuthMode(nextMode);
    setAuthForm(emptyAuthForm);
    setError(null);
  }

  useEffect(() => {
    if (!configOpen || !currentProfile) return;
    setProfileForm({
      provider: currentProfile.provider,
      display_name: currentProfile.display_name,
      base_url: currentProfile.base_url,
      model: currentProfile.model,
    });
  }, [configOpen, currentProfile]);

  useEffect(() => {
    setModelMenuOpen(false);
    setProviderModels([]);
  }, [currentProfileId]);

  useEffect(() => {
    if (webSearchConfig?.has_key === false && webSearchEnabled) {
      setWebSearchEnabled(false);
    }
  }, [webSearchConfig?.has_key, webSearchEnabled]);

  useEffect(() => {
    const trimmed = searchQuery.trim();
    if (!trimmed) {
      setSearchResults([]);
      return;
    }
    const timer = window.setTimeout(async () => {
      try {
        setSearchResults(await searchWorkbench(trimmed));
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    }, 240);
    return () => window.clearTimeout(timer);
  }, [searchQuery]);

  useEffect(() => {
    if (!activeBidWorkflow || !["extracting", "generating"].includes(activeBidWorkflow.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const workflow = await getBidWorkflow(activeBidWorkflow.id);
        setActiveBidWorkflow(workflow);
        setIsBidBusy(["extracting", "generating"].includes(workflow.status));
        if (workflow.conversation_id === currentConversationId) {
          setMessages(await listMessages(workflow.conversation_id));
        }
        if (!["extracting", "generating"].includes(workflow.status)) {
          await refreshConversations(currentProjectId);
        }
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
        setIsBidBusy(false);
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [activeBidWorkflow, currentConversationId, currentProjectId]);

  async function bootstrap() {
    try {
      const [nextProjects, nextProfiles, nextWebSearchConfig] = await Promise.all([listProjects(), listProviderProfiles(), getWebSearchConfig()]);
      setProjects(nextProjects);
      setProfiles(nextProfiles);
      setWebSearchConfig(nextWebSearchConfig);
      setWebSearchForm({
        api_key: "",
        max_results: String(nextWebSearchConfig.max_results),
        search_depth: nextWebSearchConfig.search_depth,
      });
      const initialProject = nextProjects.find((project) => !project.workspace_path && project.title === "默认项目") ?? nextProjects.find((project) => !project.workspace_path) ?? nextProjects[0];
      setCurrentProjectId(initialProject?.id ?? null);
      setCurrentProfileId(nextProfiles[0]?.id ?? null);
      const [nextProjectConversations, nextRecentConversations] = await Promise.all([
        initialProject?.id ? listConversations(initialProject.id) : Promise.resolve([]),
        listConversations(),
      ]);
      setProjectConversations(nextProjectConversations);
      setRecentConversations(nextRecentConversations);
      const firstConversation = nextRecentConversations.find((conversation) => conversation.project_id === initialProject?.id) ?? nextProjectConversations[0];
      if (firstConversation) {
        await openConversation(firstConversation.id);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function refreshConversations(projectId = currentProjectId) {
    const [nextProjectConversations, nextRecentConversations] = await Promise.all([
      projectId ? listConversations(projectId) : Promise.resolve([]),
      listConversations(),
    ]);
    setProjectConversations(nextProjectConversations);
    setRecentConversations(nextRecentConversations);
    return nextProjectConversations;
  }

  async function switchProject(project: WorkbenchProject) {
    setCurrentProjectId(project.id);
    setProjectConversationsOpen(true);
    setMessages([]);
    setCurrentConversationId(null);
    setActiveBidWorkflow(null);
    await refreshConversations(project.id);
  }

  async function chooseWorkspaceDirectory() {
    setSidebarCollapsed(false);
    setError(null);
    const selected = await window.bidDesignWriterDesktop?.selectDirectory();
    if (!selected) {
      if (!window.bidDesignWriterDesktop) {
        setError("当前运行环境不支持选择本地工作目录，请在桌面端使用。");
      }
      return;
    }

    try {
      const latestProjects = await listProjects();
      const existingProject = latestProjects.find((project) => project.workspace_path === selected.path);
      if (existingProject) {
        setProjects(latestProjects);
        await switchProject(existingProject);
        return;
      }

      const project = await createProject({ title: selected.name || "未命名项目", workspace_path: selected.path });
      const nextProjects = await listProjects();
      setProjects(nextProjects);
      await switchProject(project);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function openConversation(conversationId: string) {
    const targetConversation = [...projectConversations, ...recentConversations].find((conversation) => conversation.id === conversationId);
    if (targetConversation?.project_id && targetConversation.project_id !== currentProjectId) {
      setCurrentProjectId(targetConversation.project_id);
      void refreshConversations(targetConversation.project_id);
    }
    setCurrentConversationId(conversationId);
    const [nextMessages, workflows] = await Promise.all([listMessages(conversationId), listBidWorkflows(conversationId)]);
    const workflow = workflows[0] ?? null;
    setMessages(nextMessages);
    setActiveBidWorkflow(workflow);
    setError(null);
  }

  async function removeProject(project: WorkbenchProject) {
    if (!window.confirm(`删除项目“${project.title}”？项目下的对话也会被删除。`)) return;
    try {
      await deleteProject(project.id);
      const nextProjects = await listProjects();
      const nextDefaultProject = nextProjects.find((item) => !item.workspace_path && item.title === "默认项目") ?? nextProjects.find((item) => !item.workspace_path);
      const nextProjectId = project.id === currentProjectId ? nextDefaultProject?.id ?? nextProjects[0]?.id ?? null : currentProjectId;
      setProjects(nextProjects);
      setCurrentProjectId(nextProjectId);
      await refreshConversations(nextProjectId);
      if (project.id === currentProjectId) {
        setCurrentConversationId(null);
        setMessages([]);
        setActiveBidWorkflow(null);
      }
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function removeConversation(conversation: WorkbenchConversation) {
    if (!window.confirm(`删除对话“${conversation.title}”？`)) return;
    try {
      await deleteConversation(conversation.id);
      await refreshConversations(currentProjectId);
      if (conversation.id === currentConversationId) {
        setCurrentConversationId(null);
        setMessages([]);
        setActiveBidWorkflow(null);
      }
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function startNewChat() {
    setError(null);
    try {
      const latestProjects = projects.length > 0 ? projects : await listProjects();
      const targetProject = latestProjects.find((project) => !project.workspace_path && project.title === "默认项目") ?? latestProjects.find((project) => !project.workspace_path);
      const conversation = await createConversation({
        project_id: targetProject?.id,
        title: "新对话",
        provider_profile_id: currentProfileId ?? undefined,
        model: currentProfile?.model,
      });
      setProjects(await listProjects());
      setCurrentProjectId(conversation.project_id);
      setCurrentConversationId(conversation.id);
      setMessages([]);
      setActiveBidWorkflow(null);
      setInput("");
      await refreshConversations(conversation.project_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function ensureConversation(text: string) {
    if (currentConversationId) return currentConversationId;
    const conversation = await createConversation({
      project_id: currentProjectId ?? undefined,
      title: text.slice(0, 32) || "新对话",
      provider_profile_id: currentProfileId ?? undefined,
      model: currentProfile?.model,
    });
    setCurrentConversationId(conversation.id);
    await refreshConversations(conversation.project_id);
    return conversation.id;
  }

  async function sendMessage(event?: FormEvent) {
    event?.preventDefault();
    const text = input.trim();
    if (!text || isStreaming) return;
    setError(null);

    if (!currentProfileId) {
      setConfigOpen(true);
      setError("请先配置模型 API。");
      return;
    }
    if (webSearchEnabled && !webSearchConfig?.has_key) {
      setConfigOpen(true);
      setError("请先在模型配置中填写 Tavily API key。");
      return;
    }

    const conversationId = await ensureConversation(text);
    setInput("");
    setMessages((current) => [...current, localMessage("user", text, "completed")]);
    setIsStreaming(true);

    try {
      await streamChat(
        {
          conversation_id: conversationId,
          project_id: currentProjectId ?? undefined,
          provider_profile_id: currentProfileId,
          message: text,
          web_search_enabled: webSearchEnabled,
        },
        handleStreamEvent,
      );
      await refreshConversations(currentProjectId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setIsStreaming(false);
      setActiveRunId(null);
    }
  }

  function handleStreamEvent(event: ChatStreamEvent) {
    if (event.event === "message_start") {
      setActiveRunId(event.data.run_id);
      setCurrentConversationId(event.data.conversation_id);
      setMessages((current) => applyChatStreamEvent(current, event));
      return;
    }

    if (event.event === "delta" || event.event === "message_done") {
      setMessages((current) => applyChatStreamEvent(current, event));
      return;
    }

    if (event.event === "conversation_updated") {
      void refreshConversations(event.data.project_id);
      return;
    }

    if (event.event === "error") {
      setError(event.data.message);
      if (event.data.message_id) {
        setMessages((current) => applyChatStreamEvent(current, event));
      }
    }

    if (event.event === "warning") {
      setError(event.data.message);
    }
  }

  async function stopStreaming() {
    if (!activeRunId) return;
    await cancelChat(activeRunId);
  }

  async function refreshWorkflowMessages(workflow: BidWorkflow) {
    const refreshedWorkflow = await getBidWorkflow(workflow.id);
    setActiveBidWorkflow(refreshedWorkflow);
    setCurrentConversationId(refreshedWorkflow.conversation_id);
    setMessages(await listMessages(refreshedWorkflow.conversation_id));
    await refreshConversations(currentProjectId);
  }

  async function uploadTenderFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || isBidBusy) return;
    setError(null);

    if (!currentProfileId) {
      openConfigPanel();
      setError("请先配置模型 API。");
      return;
    }
    if (activeBidWorkflow && !["completed", "cancelled"].includes(activeBidWorkflow.status)) {
      setError("当前对话已有标书工作流，请新建对话后再上传新的招标文件。");
      return;
    }

    setIsBidBusy(true);
    setUploadFileName(file.name);
    setUploadProgress(0);
    try {
      const conversationId = await ensureConversation(file.name.replace(/\.[^.]+$/, "") || file.name);
      const workflow = await createBidWorkflow({
        conversation_id: conversationId,
        provider_profile_id: currentProfileId,
        file,
        onProgress: setUploadProgress,
      });
      setActiveBidWorkflow(workflow);
      setBidConfirmation("确认");
      setBidExtraContext("");
      await refreshWorkflowMessages(workflow);
      setUploadProgress(null);
      setUploadFileName("");
      const extraction = await extractBidWorkflow(workflow.id);
      setActiveBidWorkflow(extraction.workflow);
      await refreshWorkflowMessages(extraction.workflow);
    } catch (caught) {
      setIsBidBusy(false);
      setUploadProgress(null);
      setUploadFileName("");
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function confirmWorkflow() {
    if (!activeBidWorkflow || isBidBusy) return;
    setIsBidBusy(true);
    setError(null);
    try {
      const response = await confirmBidWorkflow(activeBidWorkflow.id, bidConfirmation.trim() || "确认");
      setActiveBidWorkflow(response.workflow);
      await refreshWorkflowMessages(response.workflow);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setIsBidBusy(false);
    }
  }

  async function generateWorkflow() {
    if (!activeBidWorkflow || isBidBusy) return;
    setIsBidBusy(true);
    setError(null);
    try {
      const response = await generateBidWorkflow(activeBidWorkflow.id, {
        extra_context: bidExtraContext.trim() || undefined,
      });
      setActiveBidWorkflow(response.workflow);
      await refreshWorkflowMessages(response.workflow);
    } catch (caught) {
      setIsBidBusy(false);
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function retryWorkflow() {
    if (!activeBidWorkflow || isBidBusy) return;
    setIsBidBusy(true);
    setError(null);
    try {
      const response = activeBidWorkflow.extracted_markdown
        ? await generateBidWorkflow(activeBidWorkflow.id, {
            extra_context: bidExtraContext.trim() || undefined,
          })
        : await extractBidWorkflow(activeBidWorkflow.id);
      setActiveBidWorkflow(response.workflow);
      await refreshWorkflowMessages(response.workflow);
    } catch (caught) {
      setIsBidBusy(false);
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function cancelWorkflow() {
    if (!activeBidWorkflow) return;
    setError(null);
    try {
      const response = await cancelBidWorkflow(activeBidWorkflow.id);
      setActiveBidWorkflow(response.workflow);
      setIsBidBusy(false);
      await refreshWorkflowMessages(response.workflow);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function refreshActiveWorkflow() {
    if (!activeBidWorkflow) return;
    try {
      const workflow = await getBidWorkflow(activeBidWorkflow.id);
      setActiveBidWorkflow(workflow);
      await refreshWorkflowMessages(workflow);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  function saveBlob(blob: Blob, filename: string) {
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.URL.revokeObjectURL(url);
  }

  function downloadBaseName() {
    return sanitizeFilename(currentProject?.title || stripExtension(activeBidWorkflow?.file_name ?? "") || currentConversation?.title || "标书项目");
  }

  function artifactDownloadName(artifactName: string) {
    const ext = artifactName.includes(".") ? artifactName.slice(artifactName.lastIndexOf(".")) : ".md";
    const suffix = artifactName.includes("信息提取")
      ? "招标文件信息提取"
      : artifactName.includes("绘图") || artifactName.includes("图纸") || artifactName.includes("图文证据")
        ? "图文证据与图纸需求"
        : artifactName.includes("规范")
          ? "标书制作规范"
          : "设计方案";
    return `${downloadBaseName()}_${suffix}${ext}`;
  }

  async function downloadArtifact(artifactName: string) {
    if (!activeBidWorkflow) return;
    try {
      const blob = await downloadBidArtifact(activeBidWorkflow.id, artifactName);
      saveBlob(blob, artifactDownloadName(artifactName));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function downloadArtifactsZip() {
    if (!activeBidWorkflow) return;
    try {
      const blob = await downloadBidZip(activeBidWorkflow.id);
      saveBlob(blob, `${downloadBaseName()}_标书成果.zip`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    try {
      const existing = currentProfileId ? profiles.find((profile) => profile.id === currentProfileId) : null;
      const payload = { ...profileForm, api_key: apiKey || undefined };
      const profile = existing ? await updateProviderProfile(existing.id, payload) : await createProviderProfile(payload);
      const nextProfiles = await listProviderProfiles();
      setProfiles(nextProfiles);
      setCurrentProfileId(profile.id);
      setApiKey("");
      setConfigOpen(false);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function saveWebSearchConfig(event: FormEvent) {
    event.preventDefault();
    setWebSearchSaveState("saving");
    setWebSearchSaveMessage("");
    try {
      const apiKeyValue = webSearchForm.api_key.trim();
      const updated = await updateWebSearchConfig({
        api_key: apiKeyValue || undefined,
        max_results: Number(webSearchForm.max_results) || undefined,
        search_depth: webSearchForm.search_depth,
      });
      setWebSearchConfig(updated);
      setWebSearchForm({ api_key: "", max_results: String(updated.max_results), search_depth: updated.search_depth });
      setWebSearchSaveState("saved");
      setWebSearchSaveMessage(apiKeyValue ? "搜索配置已保存。" : "搜索配置已保存。");
      setError(null);
      window.setTimeout(() => {
        setWebSearchSaveState((current) => (current === "saved" ? "idle" : current));
        setWebSearchSaveMessage((current) => (current === "搜索配置已保存。" || current === "搜索配置已保存。" ? "" : current));
      }, 3000);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : String(caught);
      setWebSearchSaveState("error");
      setWebSearchSaveMessage(message);
      setError(message);
    }
  }

  function choosePreset(provider: string) {
    const preset = providerPresets.find((item) => item.provider === provider) ?? providerPresets[0];
    setProfileForm(preset);
  }

  function openConfigPanel() {
    setSidebarCollapsed(false);
    setSidebarWidth((current) => Math.max(current, 320));
    setConfigOpen(true);
    setUserPanelOpen(false);
    setModelMenuOpen(false);
    setAttachmentMenuOpen(false);
    setWebSearchSaveState("idle");
    setWebSearchSaveMessage("");
  }

  function toggleUserPanel() {
    setSidebarCollapsed(false);
    setConfigOpen(false);
    setModelMenuOpen(false);
    setAttachmentMenuOpen(false);
    setUserPanelOpen((current) => !current);
  }

  function updateChatAvatar(kind: "user" | "assistant", value: string) {
    if (kind === "user") {
      setUserChatAvatar(value);
      window.localStorage.setItem("bid-writer-user-avatar", value);
      return;
    }
    setAssistantChatAvatar(value);
    window.localStorage.setItem("bid-writer-assistant-avatar", value);
  }

  async function completeAuthSession(token: string) {
    window.sessionStorage.setItem("ai-workbench-auth-token", token);
    setAuthContext({ token });
    const user = await getMe();
    setAuthUser(user);
    setAuthMode("ready");
    setAuthForm(emptyAuthForm);
    setError(null);
    await bootstrap();
  }

  async function submitAuth(event: FormEvent) {
    event.preventDefault();
    if (!authBackendReady) {
      setError("正在连接本地后端，请稍候。");
      return;
    }
    const username = authForm.username.trim();
    if (!username || !authForm.password) {
      setError("请输入用户名和密码。");
      return;
    }
    if (authMode === "register" && authForm.password !== authForm.confirmPassword) {
      setError("两次输入的密码不一致。");
      return;
    }
    try {
      const response =
        authMode === "register"
          ? await registerAuth({ username, password: authForm.password })
          : await loginAuth({ username, password: authForm.password });
      await completeAuthSession(response.token);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function changeCurrentPassword(event: FormEvent) {
    event.preventDefault();
    if (!passwordForm.currentPassword || !passwordForm.newPassword) {
      setError("请输入当前密码和新密码。");
      return;
    }
    if (passwordForm.newPassword !== passwordForm.confirmPassword) {
      setError("两次输入的新密码不一致。");
      return;
    }
    try {
      await changePassword({
        current_password: passwordForm.currentPassword,
        new_password: passwordForm.newPassword,
      });
      await logoutUser();
      setError("密码已修改，请重新登录。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function logoutUser() {
    try {
      await logoutAuth();
    } catch {
      // Local logout should still clear the session if the token is already invalid.
    }
    window.sessionStorage.removeItem("ai-workbench-auth-token");
    setAuthContext({ token: null });
    setAuthUser(null);
    setAuthMode("login");
    setUserPanelOpen(false);
    setProjects([]);
    setProjectConversations([]);
    setRecentConversations([]);
    setMessages([]);
    setProfiles([]);
    setWebSearchConfig(null);
    setWebSearchForm({ api_key: "", max_results: "5", search_depth: "basic" });
    setWebSearchEnabled(false);
    setCurrentProjectId(null);
    setCurrentConversationId(null);
    setCurrentProfileId(null);
    setActiveBidWorkflow(null);
    setPasswordForm({ currentPassword: "", newPassword: "", confirmPassword: "" });
  }

  async function openModelMenu() {
    setAttachmentMenuOpen(false);
    if (!currentProfileId) {
      openConfigPanel();
      setError("请先配置模型 API。");
      return;
    }
    if (modelMenuOpen) {
      setModelMenuOpen(false);
      return;
    }
    setModelMenuOpen(true);
    if (providerModels.length > 0) return;

    setIsLoadingModels(true);
    setError(null);
    try {
      setProviderModels(await listProviderModels(currentProfileId));
    } catch (caught) {
      setModelMenuOpen(false);
      setError(caught instanceof Error ? caught.message : String(caught));
      openConfigPanel();
    } finally {
      setIsLoadingModels(false);
    }
  }

  async function chooseModel(modelId: string) {
    if (!currentProfileId || !currentProfile) return;
    try {
      const updated = await updateProviderProfile(currentProfileId, { model: modelId });
      const nextProfiles = await listProviderProfiles();
      setProfiles(nextProfiles);
      setCurrentProfileId(updated.id);
      setProfileForm({
        provider: updated.provider,
        display_name: updated.display_name,
        base_url: updated.base_url,
        model: updated.model,
      });
      setModelMenuOpen(false);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  const composerControls = (
    <div className="composer-toolbar">
      <div className="toolbar-left">
        <input ref={fileInputRef} type="file" accept=".pdf,.docx,.txt,.md" className="hidden-file-input" onChange={uploadTenderFile} />
        <div className="attachment-menu-wrap">
          <button
            type="button"
            className="attachment-add-button"
            onClick={() => setAttachmentMenuOpen((current) => !current)}
            disabled={isBidBusy}
            aria-label="添加"
            aria-expanded={attachmentMenuOpen}
          >
            <Plus size={18} />
          </button>
          {attachmentMenuOpen && (
            <div className="attachment-menu">
              <button
                type="button"
                onClick={() => {
                  setAttachmentMenuOpen(false);
                  fileInputRef.current?.click();
                }}
                disabled={isBidBusy}
              >
                <FileText size={16} />
                <span>上传招标文件</span>
              </button>
            </div>
          )}
        </div>
        {uploadProgress !== null && (
          <div className="upload-progress" title={uploadFileName}>
            <span>{uploadProgress}%</span>
            <div>
              <i style={{ width: `${uploadProgress}%` }} />
            </div>
          </div>
        )}
        <button
          type="button"
          className={currentProfile?.model ? "access-button configured" : "access-button"}
          onClick={openConfigPanel}
        >
          <ShieldCheck size={18} />
          <span>{currentProfile?.model ? "模型已配置" : "配置模型"}</span>
          <ChevronRight size={16} />
        </button>
        <button
          type="button"
          className={
            webSearchConfig?.has_key === false
              ? "web-search-toggle disabled"
              : webSearchEnabled
                ? "web-search-toggle active"
                : "web-search-toggle"
          }
          onClick={() => {
            if (webSearchConfig?.has_key === false) {
              setError("请先在模型配置中填写 Tavily API key。");
              return;
            }
            setWebSearchEnabled((current) => !current);
          }}
          aria-pressed={webSearchEnabled}
          title={webSearchConfig?.has_key === false ? "请先配置 Tavily API key" : "使用 Tavily 联网搜索"}
        >
          <Globe2 size={17} />
          <span>联网搜索</span>
        </button>
      </div>
      <div className="toolbar-right">
        <div className="model-picker">
          <button type="button" className="model-select" onClick={openModelMenu} aria-expanded={modelMenuOpen}>
            {currentProfile?.model ?? "选择模型"}
            <ChevronRight className={modelMenuOpen ? "chevron open" : "chevron"} size={15} />
          </button>
          {modelMenuOpen && (
            <div className="model-menu">
              {isLoadingModels ? (
                <div className="model-menu-status">
                  <Loader2 size={14} />
                  拉取模型中
                </div>
              ) : providerModels.length === 0 ? (
                <div className="model-menu-status">未返回模型列表</div>
              ) : (
                providerModels.map((model) => (
                  <button
                    type="button"
                    className={model.id === currentProfile?.model ? "model-option active" : "model-option"}
                    key={model.id}
                    onClick={() => chooseModel(model.id)}
                  >
                    {model.name || model.id}
                  </button>
                ))
              )}
            </div>
          )}
        </div>
        {isStreaming ? (
          <button type="button" className="send-round" onClick={stopStreaming} aria-label="停止生成">
            <Square size={17} />
          </button>
        ) : (
          <button className="send-round" disabled={!input.trim()} aria-label="发送">
            <Send size={18} />
          </button>
        )}
      </div>
    </div>
  );

  const workflowPanel =
    activeBidWorkflow && activeBidWorkflow.conversation_id === currentConversationId ? (
      <section className="workflow-panel">
        <div className="workflow-header">
          <div>
            <span>{workflowStatusText(activeBidWorkflow.status)}</span>
            <strong>{activeBidWorkflow.file_name}</strong>
          </div>
          <div className="workflow-header-tools">
            {["uploaded", "extracting", "extraction_ready", "generating", "failed"].includes(activeBidWorkflow.status) && (
              <>
                {["extracting", "generating"].includes(activeBidWorkflow.status) && <Loader2 size={18} className="spin-icon" />}
                <button type="button" onClick={cancelWorkflow}>
                  取消
                </button>
              </>
            )}
            {activeBidWorkflow.status === "completed" && <CheckCircle2 size={18} />}
          </div>
        </div>

        {activeBidWorkflow.status === "extraction_ready" && !activeBidWorkflow.confirmation_text && (
          <div className="workflow-actions">
            <label>
              确认信息
              <textarea value={bidConfirmation} onChange={(event) => setBidConfirmation(event.target.value)} rows={3} />
            </label>
            <button type="button" onClick={confirmWorkflow} disabled={isBidBusy}>
              确认阶段一
            </button>
          </div>
        )}

        {activeBidWorkflow.confirmation_text && !["completed", "cancelled"].includes(activeBidWorkflow.status) && (
          <div className="workflow-actions">
            <div className="workflow-note">目录结构将按当前招标范围、评分、成果和格式要求动态编排，不套用固定模板。</div>
            <label>
              补充信息
              <textarea
                value={bidExtraContext}
                onChange={(event) => setBidExtraContext(event.target.value)}
                rows={3}
                placeholder="企业优势、类似业绩、设计团队或章节偏好"
              />
            </label>
            <button type="button" onClick={generateWorkflow} disabled={isBidBusy || activeBidWorkflow.status === "generating"}>
              生成设计方案
            </button>
          </div>
        )}

        {activeBidWorkflow.status === "failed" && (
          <div className="workflow-error">
            <span>{activeBidWorkflow.error ?? "执行失败"}</span>
            <button type="button" onClick={retryWorkflow} disabled={isBidBusy}>
              重试当前阶段
            </button>
          </div>
        )}

        {activeBidWorkflow.status === "completed" && (
          <div className="artifact-list">
            <div className="artifact-primary-actions">
              {activeBidWorkflow.artifacts.find((artifact) => artifact.kind === "proposal") ? (
                <button
                  type="button"
                  className="artifact-primary-button"
                  onClick={() => downloadArtifact(activeBidWorkflow.artifacts.find((artifact) => artifact.kind === "proposal")!.name)}
                >
                  <Download size={15} />
                  <span>下载 Markdown 文件</span>
                </button>
              ) : (
                <button type="button" className="artifact-primary-button" onClick={refreshActiveWorkflow}>
                  <Download size={15} />
                  <span>刷新成果文件</span>
                </button>
              )}
              {activeBidWorkflow.artifacts.length > 0 && (
                <button type="button" className="artifact-primary-button" onClick={downloadArtifactsZip}>
                  <Download size={15} />
                  <span>下载 ZIP 包</span>
                </button>
              )}
            </div>
            {activeBidWorkflow.artifacts.length > 0 ? (
              activeBidWorkflow.artifacts.map((artifact) => (
                <button type="button" key={artifact.name} onClick={() => downloadArtifact(artifact.name)}>
                  <Download size={15} />
                  <span>{artifact.name}</span>
                </button>
              ))
            ) : (
              <div className="workflow-note">阶段二已完成，正在等待成果文件同步。</div>
            )}
          </div>
        )}
      </section>
    ) : null;

  if (authMode !== "ready") {
    return (
      <main className="auth-screen">
        <section className="auth-panel">
          <div className="auth-heading">
            <span>建筑设计标书方案助手</span>
            <h1>{authMode === "register" ? "注册" : "登录"}</h1>
          </div>
          <div className="auth-tabs" role="tablist" aria-label="账号入口">
            <button type="button" className={authMode === "login" ? "active" : ""} onClick={() => switchAuthMode("login")}>
              登录
            </button>
            <button type="button" className={authMode === "register" ? "active" : ""} onClick={() => switchAuthMode("register")}>
              注册
            </button>
          </div>
          <form className="auth-form" onSubmit={submitAuth}>
            <label>
              用户名
              <input value={authForm.username} onChange={(event) => setAuthForm({ ...authForm, username: event.target.value })} autoComplete="username" />
            </label>
            <label>
              密码
              <input
                value={authForm.password}
                type="password"
                onChange={(event) => setAuthForm({ ...authForm, password: event.target.value })}
                autoComplete={authMode === "register" ? "new-password" : "current-password"}
              />
            </label>
            {authMode === "register" && (
              <label>
                确认密码
                <input
                  value={authForm.confirmPassword}
                  type="password"
                  onChange={(event) => setAuthForm({ ...authForm, confirmPassword: event.target.value })}
                  autoComplete="new-password"
                />
              </label>
            )}
            <button type="submit">{authMode === "register" ? "注册并进入" : "登录"}</button>
          </form>
          {!authBackendReady && (
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

  return (
    <main
      className="workbench-shell"
      data-sidebar={sidebarCollapsed ? "collapsed" : "expanded"}
      style={{ "--sidebar-width": `${sidebarWidth}px` } as CSSProperties}
    >
      <aside className="sidebar">
        <div className="sidebar-top">
          {!sidebarCollapsed && <div className="app-mark">建筑设计标书方案助手</div>}
          <button className="ghost-icon" onClick={() => setSidebarCollapsed((current) => !current)} aria-label="折叠菜单">
            {sidebarCollapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
          </button>
        </div>

        <div className="menu-block">
          <button className="menu-command" onClick={startNewChat} title="新对话">
            <MessageSquarePlus size={19} />
            {!sidebarCollapsed && <span>新对话</span>}
          </button>
          <button className="menu-command" onClick={() => setSearchQuery((current) => current || " ")} title="搜索">
            <Search size={19} />
            {!sidebarCollapsed && <span>搜索</span>}
          </button>
          <button className="menu-command" onClick={openConfigPanel} title="模型配置">
            <Settings2 size={19} />
            {!sidebarCollapsed && <span>模型配置</span>}
          </button>
        </div>

        {configOpen && !sidebarCollapsed && (
          <section className="config-panel" aria-label="模型与工具配置">
            <div className="config-panel-header">
              <div>
                <strong>模型与工具配置</strong>
                <span>模型 API 和联网搜索仅保存在本机</span>
              </div>
              <button type="button" onClick={() => setConfigOpen(false)} aria-label="关闭模型配置">
                <X size={17} />
              </button>
            </div>
            <div className="config-panel-scroll">
              <form className="config-section" onSubmit={saveProfile}>
                <div className="config-section-title">模型配置</div>
                <div className="config-grid">
                  <label>
                    Provider
                    <select value={profileForm.provider} onChange={(event) => choosePreset(event.target.value)}>
                      {providerPresets.map((preset) => (
                        <option key={preset.provider}>{preset.provider}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    显示名称
                    <input value={profileForm.display_name} onChange={(event) => setProfileForm({ ...profileForm, display_name: event.target.value })} />
                  </label>
                  <label>
                    Base URL
                    <input value={profileForm.base_url} onChange={(event) => setProfileForm({ ...profileForm, base_url: event.target.value })} />
                  </label>
                  <label>
                    Model
                    <input value={profileForm.model} onChange={(event) => setProfileForm({ ...profileForm, model: event.target.value })} />
                  </label>
                  <label className="api-key-field">
                    API key
                    <input value={apiKey} type="password" onChange={(event) => setApiKey(event.target.value)} placeholder="保存到当前账号本地数据库" />
                  </label>
                </div>
                <div className="config-actions">
                  <button type="submit">保存模型</button>
                </div>
              </form>

              <form className="config-section" onSubmit={saveWebSearchConfig}>
                <div className="config-section-title">
                  <span>联网搜索</span>
                  <em>
                    {webSearchConfig?.source === "db"
                      ? "已配置（本地）"
                      : webSearchConfig?.source === "env"
                        ? "已配置（环境变量）"
                        : "未配置"}
                  </em>
                </div>
                {webSearchConfig?.source === "env" && (
                  <div className="config-message">
                    当前 key 来自环境变量（.env 文件），优先级低于本地保存的 key。在下方填写新 key 保存后将覆盖。
                  </div>
                )}
                <div className="config-grid">
                  <label className="api-key-field">
                    Tavily API key
                    <input
                      value={webSearchForm.api_key}
                      type="password"
                      onChange={(event) => setWebSearchForm({ ...webSearchForm, api_key: event.target.value })}
                      placeholder={
                        webSearchConfig?.source === "db"
                          ? "留空则保留现有 key"
                          : webSearchConfig?.source === "env"
                            ? "填写后保存到本地（替代环境变量）"
                            : "填写 Tavily API key"
                      }
                      disabled={webSearchSaveState === "saving"}
                    />
                  </label>
                  <label>
                    结果数量
                    <input
                      value={webSearchForm.max_results}
                      type="number"
                      min={1}
                      max={10}
                      onChange={(event) => setWebSearchForm({ ...webSearchForm, max_results: event.target.value })}
                      disabled={webSearchSaveState === "saving"}
                    />
                  </label>
                  <label>
                    搜索深度
                    <select value={webSearchForm.search_depth} onChange={(event) => setWebSearchForm({ ...webSearchForm, search_depth: event.target.value })} disabled={webSearchSaveState === "saving"}>
                      <option value="basic">basic</option>
                      <option value="advanced">advanced</option>
                    </select>
                  </label>
                </div>
                {webSearchSaveMessage && <div className={webSearchSaveState === "error" ? "config-message error" : "config-message"}>{webSearchSaveMessage}</div>}
                <div className="config-actions">
                  <button type="submit" disabled={webSearchSaveState === "saving"}>
                    {webSearchSaveState === "saving" ? "保存中" : "保存搜索"}
                  </button>
                </div>
              </form>
            </div>
          </section>
        )}

        <div className="sidebar-section">
          {!sidebarCollapsed && (
            <button className="section-label section-toggle" onClick={() => setProjectsOpen((current) => !current)}>
              项目
              <ChevronRight className={projectsOpen ? "chevron open" : "chevron"} size={15} />
            </button>
          )}
          {!sidebarCollapsed && (
            <div className="search-box">
              <Search size={16} />
              <input value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="搜索项目、历史对话" />
            </div>
          )}
          {!sidebarCollapsed && searchResults.length > 0 && (
            <div className="search-results">
              {searchResults.map((result) => (
                <button key={`${result.kind}-${result.id}`} onClick={() => result.conversation_id && openConversation(result.conversation_id)}>
                  <strong>{result.title}</strong>
                  <span>{result.excerpt}</span>
                </button>
              ))}
            </div>
          )}
          {projectsOpen && (
            <div className="nav-list">
              {!sidebarCollapsed && (
                <button type="button" className="workspace-picker-row" onClick={chooseWorkspaceDirectory}>
                  <FolderOpen size={17} />
                  <span>选择本地文件夹</span>
                </button>
              )}
              {projects.map((project) => (
                <div className="project-group" key={project.id}>
                  <div className={project.id === currentProjectId ? "sidebar-item-shell project-shell active" : "sidebar-item-shell"}>
                    <button
                      className="project-row"
                      onClick={() => switchProject(project)}
                      title={project.workspace_path ? `${project.title}\n${project.workspace_path}` : project.title}
                    >
                      <FileText size={18} />
                      {!sidebarCollapsed && <span>{project.title}</span>}
                    </button>
                    {!sidebarCollapsed && project.workspace_path && project.id === currentProjectId && (
                      <button
                        type="button"
                        className="project-expand-toggle"
                        onClick={() => setProjectConversationsOpen((current) => !current)}
                        aria-label={projectConversationsOpen ? `收起 ${project.title} 的对话` : `展开 ${project.title} 的对话`}
                      >
                        <ChevronRight className={projectConversationsOpen ? "chevron open" : "chevron"} size={15} />
                      </button>
                    )}
                    {!sidebarCollapsed && (
                      <button type="button" className="row-delete" onClick={() => removeProject(project)} aria-label={`删除项目 ${project.title}`}>
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                    {!sidebarCollapsed &&
                    project.workspace_path &&
                    project.id === currentProjectId &&
                    projectConversationsOpen &&
                    projectPreviewConversations.map((conversation) => (
                      <div className={conversation.id === currentConversationId ? "sidebar-item-shell project-chat-shell active" : "sidebar-item-shell project-chat-shell"} key={conversation.id}>
                        <button className="project-chat-row" onClick={() => openConversation(conversation.id)} title={conversation.title}>
                          <span>{conversation.title}</span>
                          <time>{relativeTime(conversation.updated_at)}</time>
                        </button>
                        <button type="button" className="row-delete" onClick={() => removeConversation(conversation)} aria-label={`删除对话 ${conversation.title}`}>
                          <Trash2 size={14} />
                        </button>
                      </div>
                    ))}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="sidebar-section grow">
          {!sidebarCollapsed && (
            <button className="section-label section-toggle" onClick={() => setConversationsOpen((current) => !current)}>
              对话
              <ChevronRight className={conversationsOpen ? "chevron open" : "chevron"} size={15} />
            </button>
          )}
          {conversationsOpen && (
            <div className="nav-list history-list">
              {sidebarHistoryConversations.length === 0 && !sidebarCollapsed ? (
                <div className="empty-sidebar">暂无其他对话</div>
              ) : (
                sidebarHistoryConversations.map((conversation) => (
                  <div className={conversation.id === currentConversationId ? "sidebar-item-shell conversation-shell active" : "sidebar-item-shell conversation-shell"} key={conversation.id}>
                    <button className="conversation-row" onClick={() => openConversation(conversation.id)} title={conversation.title}>
                      <History size={16} />
                      {!sidebarCollapsed && <span>{conversation.title}</span>}
                      {!sidebarCollapsed && <time>{relativeTime(conversation.updated_at)}</time>}
                    </button>
                    {!sidebarCollapsed && (
                      <button type="button" className="row-delete" onClick={() => removeConversation(conversation)} aria-label={`删除对话 ${conversation.title}`}>
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        {userPanelOpen && !sidebarCollapsed && (
          <section className="user-panel">
            <div className="user-panel-header">
              <strong>账号</strong>
              <button type="button" onClick={() => setUserPanelOpen(false)} aria-label="关闭账号面板">
                ×
              </button>
            </div>
            <div className="user-panel-scroll">
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
              <form className="user-login-form" onSubmit={changeCurrentPassword}>
                <label>
                  当前密码
                  <input
                    value={passwordForm.currentPassword}
                    type="password"
                    onChange={(event) => setPasswordForm({ ...passwordForm, currentPassword: event.target.value })}
                    autoComplete="current-password"
                  />
                </label>
                <label>
                  新密码
                  <input
                    value={passwordForm.newPassword}
                    type="password"
                    onChange={(event) => setPasswordForm({ ...passwordForm, newPassword: event.target.value })}
                    autoComplete="new-password"
                  />
                </label>
                <label>
                  确认新密码
                  <input
                    value={passwordForm.confirmPassword}
                    type="password"
                    onChange={(event) => setPasswordForm({ ...passwordForm, confirmPassword: event.target.value })}
                    autoComplete="new-password"
                  />
                </label>
                <button type="submit">修改密码</button>
              </form>
            </div>
            <div className="user-panel-actions">
              <button type="button" className="user-secondary-action" onClick={logoutUser}>
                退出登录
              </button>
            </div>
          </section>
        )}

        <button type="button" className="account-card" onClick={toggleUserPanel} title="用户信息">
          <div className="account-avatar">{userInitials(authUser)}</div>
          {!sidebarCollapsed && (
            <div className="account-copy">
              <strong>{authUser?.username ?? "未登录"}</strong>
              <span>本机账号</span>
            </div>
          )}
          {!sidebarCollapsed && <ChevronRight className={userPanelOpen ? "chevron open" : "chevron"} size={16} />}
        </button>
        {!sidebarCollapsed && (
          <div
            className="sidebar-resize-handle"
            role="separator"
            aria-label="调整侧边栏宽度"
            aria-orientation="vertical"
            tabIndex={0}
            onPointerDown={(event) => {
              event.preventDefault();
              setIsResizingSidebar(true);
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowLeft") {
                event.preventDefault();
                setSidebarWidth((current) => Math.max(250, current - 16));
              }
              if (event.key === "ArrowRight") {
                event.preventDefault();
                setSidebarWidth((current) => Math.min(440, current + 16));
              }
            }}
          />
        )}
      </aside>

      <section className="chat-workspace">
        {error && <div className="error-banner">{error}</div>}

        {messages.length === 0 ? (
          <div className="landing-stage">
            <h1>今天想聊什么？</h1>
            <form className="composer hero-composer" onSubmit={sendMessage}>
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder={currentProfileId ? "随心输入或者上传招标文件" : "先配置模型 API"}
                rows={2}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void sendMessage();
                  }
                }}
              />
              {composerControls}
              <button type="button" className="choose-project" onClick={chooseWorkspaceDirectory}>
                <FolderOpen size={16} />
                <span>{currentProject?.title ? `当前工作目录 · ${currentProject.title}` : "选择项目工作目录"}</span>
              </button>
            </form>
          </div>
        ) : (
          <>
            <div className="messages">
              <div className="conversation-title">
                <span>{currentProject?.title ?? "默认项目"}</span>
                <h1>{currentConversation?.title ?? "新对话"}</h1>
              </div>
              {messages.map((message) => (
                <article className={`message-row ${message.role}`} key={message.id}>
                  <div className="avatar chat-avatar">{avatarContent(message.role === "user" ? userChatAvatar : assistantChatAvatar)}</div>
                  <div className="message-bubble">
                    <div className="message-meta">
                      <span>{message.role === "user" ? "用户" : "LLM"}</span>
                      <time>{formatMessageTime(message.created_at)}</time>
                    </div>
                    {message.role === "assistant" ? (
                      <MarkdownPane content={message.content} empty={message.status === "streaming" ? "正在生成..." : "暂无内容"} />
                    ) : (
                      <p>{message.content}</p>
                    )}
                    {message.status === "streaming" && (
                      <span className="message-status">
                        <Loader2 size={14} />
                        streaming
                      </span>
                    )}
                    {message.status === "interrupted" && <span className="message-status">interrupted</span>}
                    {message.status === "error" && <span className="message-status error">error</span>}
                  </div>
                </article>
              ))}
              {workflowPanel}
            </div>
            <form className="composer docked-composer" onSubmit={sendMessage}>
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder={currentProfileId ? "随心输入或者上传招标文件" : "先配置模型 API"}
                rows={1}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void sendMessage();
                  }
                }}
              />
              {composerControls}
            </form>
          </>
        )}
      </section>
    </main>
  );
}
