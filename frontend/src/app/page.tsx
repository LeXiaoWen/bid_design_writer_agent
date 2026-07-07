"use client";

import {
  CheckCircle2,
  ChevronRight,
  Download,
  FileText,
  FolderOpen,
  History,
  Loader2,
  MessageSquarePlus,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Send,
  Settings2,
  ShieldCheck,
  Square,
  Trash2,
} from "lucide-react";
import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";

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
  setupAuth,
  streamChat,
  updateProviderProfile,
} from "@/lib/api";
import { MarkdownPane } from "@/components/MarkdownPane";
import type {
  AuthUser,
  BidWorkflow,
  ChatStreamEvent,
  ProviderModel,
  ProviderProfile,
  SearchResult,
  WorkbenchConversation,
  WorkbenchMessage,
  WorkbenchProject,
} from "@/lib/types";
import { applyChatStreamEvent } from "@/lib/chatReducer";

const providerPresets = [
  { provider: "OpenAI", display_name: "OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-4o" },
  { provider: "DeepSeek", display_name: "DeepSeek", base_url: "https://api.deepseek.com", model: "deepseek-chat" },
  { provider: "通义千问 DashScope", display_name: "通义千问", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus" },
  { provider: "SiliconFlow", display_name: "SiliconFlow", base_url: "https://api.siliconflow.cn/v1", model: "deepseek-ai/DeepSeek-V3" },
  { provider: "OpenRouter", display_name: "OpenRouter", base_url: "https://openrouter.ai/api/v1", model: "openai/gpt-4o-mini" },
  { provider: "自定义", display_name: "自定义", base_url: "", model: "" },
];

type AuthMode = "loading" | "setup" | "login" | "ready";

const emptyAuthForm = {
  username: "",
  password: "",
  confirmPassword: "",
};

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
  for (let attempt = 0; attempt < 30; attempt += 1) {
    try {
      return await getAuthStatus();
    } catch (caught) {
      lastError = caught;
      const message = caught instanceof Error ? caught.message : String(caught);
      if (!message.includes("无法连接本地后端")) throw caught;
      await sleep(500);
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError));
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
  const [authMode, setAuthMode] = useState<AuthMode>("loading");
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [authForm, setAuthForm] = useState(emptyAuthForm);
  const [passwordForm, setPasswordForm] = useState({ currentPassword: "", newPassword: "", confirmPassword: "" });
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [providerModels, setProviderModels] = useState<ProviderModel[]>([]);
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [projectsOpen, setProjectsOpen] = useState(true);
  const [conversationsOpen, setConversationsOpen] = useState(true);
  const [profileForm, setProfileForm] = useState(providerPresets[0]);
  const [apiKey, setApiKey] = useState("");
  const [activeBidWorkflow, setActiveBidWorkflow] = useState<BidWorkflow | null>(null);
  const [bidConfirmation, setBidConfirmation] = useState("确认");
  const [bidExtraContext, setBidExtraContext] = useState("");
  const [isBidBusy, setIsBidBusy] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [uploadFileName, setUploadFileName] = useState("");
  const [userChatAvatar, setUserChatAvatar] = useState("我");
  const [assistantChatAvatar, setAssistantChatAvatar] = useState("AI");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const currentProject = useMemo(() => projects.find((project) => project.id === currentProjectId) ?? null, [projects, currentProjectId]);
  const currentConversation = useMemo(
    () => [...projectConversations, ...recentConversations].find((conversation) => conversation.id === currentConversationId) ?? null,
    [projectConversations, recentConversations, currentConversationId],
  );
  const projectPreviewConversations = useMemo(() => projectConversations.slice(0, 2), [projectConversations]);
  const sidebarHistoryConversations = useMemo(() => {
    const previewIds = new Set(projectPreviewConversations.map((conversation) => conversation.id));
    return recentConversations.filter((conversation) => !previewIds.has(conversation.id));
  }, [projectPreviewConversations, recentConversations]);
  const currentProfile = useMemo(() => profiles.find((profile) => profile.id === currentProfileId) ?? null, [profiles, currentProfileId]);

  useEffect(() => {
    void initializeAuth();
  }, []);

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
      if (status.setup_required) {
        setAuthMode("setup");
        return;
      }
      if (status.authenticated && savedToken) {
        const user = await getMe();
        setAuthUser(user);
        setAuthMode("ready");
        await bootstrap();
        return;
      }
      setAuthMode("login");
    } catch (caught) {
      setAuthMode("login");
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  function switchAuthMode(nextMode: "login" | "setup") {
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
      const [nextProjects, nextProfiles] = await Promise.all([listProjects(), listProviderProfiles()]);
      setProjects(nextProjects);
      setProfiles(nextProfiles);
      setCurrentProjectId(nextProjects[0]?.id ?? null);
      setCurrentProfileId(nextProfiles[0]?.id ?? null);
      const [nextProjectConversations, nextRecentConversations] = await Promise.all([
        nextProjects[0]?.id ? listConversations(nextProjects[0].id) : Promise.resolve([]),
        listConversations(),
      ]);
      setProjectConversations(nextProjectConversations);
      setRecentConversations(nextRecentConversations);
      const firstConversation = nextProjectConversations[0] ?? nextRecentConversations[0];
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
      const nextProjectId = project.id === currentProjectId ? nextProjects[0]?.id ?? null : currentProjectId;
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
    setCurrentConversationId(null);
    setMessages([]);
    setActiveBidWorkflow(null);
    setInput("");
    setError(null);
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
        template_choice: "auto",
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
            template_choice: "auto",
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
      : artifactName.includes("绘图") || artifactName.includes("图纸")
        ? "绘图提示词_图纸需求清单"
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

  function choosePreset(provider: string) {
    const preset = providerPresets.find((item) => item.provider === provider) ?? providerPresets[0];
    setProfileForm(preset);
  }

  function openConfigPanel() {
    setSidebarCollapsed(false);
    setConfigOpen(true);
    setUserPanelOpen(false);
    setModelMenuOpen(false);
  }

  function toggleUserPanel() {
    setSidebarCollapsed(false);
    setConfigOpen(false);
    setModelMenuOpen(false);
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
    const username = authForm.username.trim();
    if (!username || !authForm.password) {
      setError("请输入用户名和密码。");
      return;
    }
    if (authMode === "setup" && authForm.password !== authForm.confirmPassword) {
      setError("两次输入的密码不一致。");
      return;
    }
    try {
      const response =
        authMode === "setup"
          ? await setupAuth({ username, password: authForm.password })
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
    setCurrentProjectId(null);
    setCurrentConversationId(null);
    setCurrentProfileId(null);
    setActiveBidWorkflow(null);
    setPasswordForm({ currentPassword: "", newPassword: "", confirmPassword: "" });
  }

  async function openModelMenu() {
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
        <button type="button" className="tender-upload-button" onClick={() => fileInputRef.current?.click()} disabled={isBidBusy}>
          <FileText size={17} />
          <span>招标文件</span>
        </button>
        {uploadProgress !== null && (
          <div className="upload-progress" title={uploadFileName}>
            <span>{uploadProgress}%</span>
            <div>
              <i style={{ width: `${uploadProgress}%` }} />
            </div>
          </div>
        )}
        <button type="button" className="access-button" onClick={openConfigPanel}>
          <ShieldCheck size={18} />
          <span>{currentProfileId ? "模型已配置" : "配置模型"}</span>
          <ChevronRight size={16} />
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
            <div className="workflow-note">目录结构将根据招标文件实际要求自动判断；有明确目录时按招标文件，没有明确目录时再参考通用模板。</div>
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
            <h1>{authMode === "setup" ? "注册" : authMode === "login" ? "登录" : "正在检查登录状态"}</h1>
          </div>
          {authMode === "loading" ? (
            <div className="auth-loading">
              <Loader2 size={18} className="spin-icon" />
              <span>加载中</span>
            </div>
          ) : (
            <>
              <div className="auth-tabs" role="tablist" aria-label="账号入口">
                <button type="button" className={authMode === "login" ? "active" : ""} onClick={() => switchAuthMode("login")}>
                  登录
                </button>
                <button type="button" className={authMode === "setup" ? "active" : ""} onClick={() => switchAuthMode("setup")}>
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
                    autoComplete={authMode === "setup" ? "new-password" : "current-password"}
                  />
                </label>
                {authMode === "setup" && (
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
                <button type="submit">{authMode === "setup" ? "注册并进入" : "登录"}</button>
              </form>
            </>
          )}
          {error && <div className="auth-error">{error}</div>}
        </section>
      </main>
    );
  }

  return (
    <main className="workbench-shell" data-sidebar={sidebarCollapsed ? "collapsed" : "expanded"}>
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
          <form className="config-panel" onSubmit={saveProfile}>
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
                <input value={apiKey} type="password" onChange={(event) => setApiKey(event.target.value)} placeholder="保存到系统钥匙串" />
              </label>
            </div>
            <div className="config-actions">
              <button type="button" onClick={() => setConfigOpen(false)}>
                取消
              </button>
              <button type="submit">保存配置</button>
            </div>
          </form>
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
                  <div className={project.id === currentProjectId ? "sidebar-item-shell active" : "sidebar-item-shell"}>
                    <button
                      className="project-row"
                      onClick={() => switchProject(project)}
                      title={project.workspace_path ? `${project.title}\n${project.workspace_path}` : project.title}
                    >
                      <FileText size={18} />
                      {!sidebarCollapsed && <span>{project.title}</span>}
                    </button>
                    {!sidebarCollapsed && (
                      <button type="button" className="row-delete" onClick={() => removeProject(project)} aria-label={`删除项目 ${project.title}`}>
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                  {!sidebarCollapsed &&
                    project.id === currentProjectId &&
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
            <div className="user-detail">
              <span>当前账号</span>
              <strong>{authUser?.username ?? "未登录"}</strong>
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
            <button type="button" className="user-secondary-action" onClick={logoutUser}>
              退出登录
            </button>
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
                placeholder={currentProfileId ? "随心输入" : "先配置模型 API"}
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
                placeholder={currentProfileId ? "继续输入..." : "先配置模型 API"}
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
