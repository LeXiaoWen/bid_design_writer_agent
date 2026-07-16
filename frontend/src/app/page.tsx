"use client";

import { X } from "lucide-react";
import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Panel, PanelGroup, PanelResizeHandle, type ImperativePanelHandle } from "react-resizable-panels";
import { toast } from "sonner";

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
  getBidWorkflow,
  getWebSearchConfig,
  listConversations,
  listBidWorkflows,
  listMessages,
  listProjects,
  listProviderProfiles,
  searchWorkbench,
  updateProviderProfile,
  updateWebSearchConfig,
} from "@/lib/api";
import { ChatWorkspace } from "@/components/ChatWorkspace";
import { ConfigDialog, type ProviderProfileDraft, type ProviderProfileValues, type WebSearchValues } from "@/components/ConfigDialog";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { AuthPanel, type AuthMode as AuthPanelMode } from "@/components/AuthPanel";
import { BidWorkflowPanel } from "@/components/BidWorkflowPanel";
import { WorkbenchSidebar } from "@/components/WorkbenchSidebar";
import { useAuth } from "@/hooks/useAuth";
import { useBidWorkflow } from "@/hooks/useBidWorkflow";
import { useChatStream } from "@/hooks/useChatStream";
import { useProviderModels } from "@/hooks/useProviderModels";
import type {
  BidWorkflow,
  ChatStreamEvent,
  ProviderProfile,
  SearchResult,
  WebSearchConfig,
  WorkbenchConversation,
  WorkbenchMessage,
  WorkbenchProject,
} from "@/lib/types";
import { applyChatStreamEvent } from "@/lib/chatReducer";

const providerPresets: ProviderProfileDraft[] = [
  { provider: "OpenAI", display_name: "OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-4o" },
  { provider: "DeepSeek", display_name: "DeepSeek", base_url: "https://api.deepseek.com", model: "deepseek-v4-flash" },
  { provider: "通义千问 DashScope", display_name: "通义千问", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus" },
  { provider: "SiliconFlow", display_name: "SiliconFlow", base_url: "https://api.siliconflow.cn/v1", model: "deepseek-ai/DeepSeek-V3" },
  { provider: "OpenRouter", display_name: "OpenRouter", base_url: "https://openrouter.ai/api/v1", model: "openai/gpt-4o-mini" },
  { provider: "自定义", display_name: "自定义", base_url: "", model: "" },
];

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

function sanitizeFilename(value: string): string {
  return (value || "项目").replace(/[\\/:*?"<>|]/g, "_").trim() || "项目";
}

function stripExtension(value: string): string {
  return value.replace(/\.[^.]+$/, "");
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
  const [passwordForm, setPasswordForm] = useState({ currentPassword: "", newPassword: "", confirmPassword: "" });
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [projectsOpen, setProjectsOpen] = useState(true);
  const [projectConversationsOpen, setProjectConversationsOpen] = useState(true);
  const [conversationsOpen, setConversationsOpen] = useState(true);
  const [webSearchConfig, setWebSearchConfig] = useState<WebSearchConfig | null>(null);
  const {
    workflow: activeBidWorkflow,
    setWorkflow: setActiveBidWorkflow,
    isBusy: isBidBusy,
    setIsBusy: setIsBidBusy,
    polledWorkflow,
    error: workflowError,
  } = useBidWorkflow();
  const [bidConfirmation, setBidConfirmation] = useState("确认");
  const [bidExtraContext, setBidExtraContext] = useState("");
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [uploadFileName, setUploadFileName] = useState("");
  const [userChatAvatar, setUserChatAvatar] = useState("我");
  const [assistantChatAvatar, setAssistantChatAvatar] = useState("AI");
  const [webSearchEnabled, setWebSearchEnabled] = useState(false);
  const [attachmentMenuOpen, setAttachmentMenuOpen] = useState(false);
  const sidebarPanelRef = useRef<ImperativePanelHandle>(null);

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
  const configProfile = useMemo<ProviderProfileDraft>(
    () => currentProfile ? { provider: currentProfile.provider, display_name: currentProfile.display_name, base_url: currentProfile.base_url, model: currentProfile.model } : providerPresets[0],
    [currentProfile],
  );
  const { models: providerModels, isLoading: isLoadingModels, error: providerModelsError } = useProviderModels(currentProfileId, modelMenuOpen);

  useEffect(() => {
    void initializeAuth().then((user) => user && bootstrap());
  }, [initializeAuth]);

  useEffect(() => {
    const handleAuthExpired = () => {
      void logoutUser();
      setError("登录会话已失效，请重新登录。");
    };
    window.addEventListener("ai-workbench-auth-expired", handleAuthExpired);
    return () => window.removeEventListener("ai-workbench-auth-expired", handleAuthExpired);
  }, []);

  useEffect(() => {
    if (authMode !== "ready" || !error) return;
    toast.error(error);
    setError(null);
  }, [authMode, error]);

  useEffect(() => {
    setUserChatAvatar(window.localStorage.getItem("bid-writer-user-avatar") || "我");
    setAssistantChatAvatar(window.localStorage.getItem("bid-writer-assistant-avatar") || "AI");
  }, []);

  useEffect(() => {
    setModelMenuOpen(false);
  }, [currentProfileId]);

  useEffect(() => {
    if (!modelMenuOpen || !providerModelsError) return;
    setModelMenuOpen(false);
    setConfigOpen(true);
    setUserPanelOpen(false);
    setAttachmentMenuOpen(false);
    setError(providerModelsError instanceof Error ? providerModelsError.message : String(providerModelsError));
  }, [modelMenuOpen, providerModelsError]);

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
    const workflow = polledWorkflow;
    if (!workflow) return;
    if (workflow.conversation_id === currentConversationId) {
      void listMessages(workflow.conversation_id).then(setMessages).catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
    }
    if (!["extracting", "generating"].includes(workflow.status)) {
      void refreshConversations(currentProjectId).catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
    }
  }, [polledWorkflow, currentConversationId, currentProjectId]);

  useEffect(() => {
    if (!workflowError) return;
    setError(workflowError instanceof Error ? workflowError.message : String(workflowError));
    setIsBidBusy(false);
  }, [workflowError, setIsBidBusy]);

  async function bootstrap() {
    try {
      const [nextProjects, nextProfiles, nextWebSearchConfig] = await Promise.all([listProjects(), listProviderProfiles(), getWebSearchConfig()]);
      setProjects(nextProjects);
      setProfiles(nextProfiles);
      setWebSearchConfig(nextWebSearchConfig);
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

  function toggleSidebar() {
    if (sidebarCollapsed) {
      sidebarPanelRef.current?.expand(22);
    } else {
      sidebarPanelRef.current?.collapse();
    }
  }

  async function chooseWorkspaceDirectory() {
    sidebarPanelRef.current?.expand(22);
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
    try {
      await sendChatStream(
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
    abortChatStream();
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

  async function saveProfile(values: ProviderProfileValues) {
    try {
      const existing = currentProfileId ? profiles.find((profile) => profile.id === currentProfileId) : null;
      const payload = { ...values, api_key: values.api_key || undefined };
      const profile = existing ? await updateProviderProfile(existing.id, payload) : await createProviderProfile(payload);
      const nextProfiles = await listProviderProfiles();
      setProfiles(nextProfiles);
      setCurrentProfileId(profile.id);
      setConfigOpen(false);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      throw caught;
    }
  }

  async function saveWebSearchConfig(values: WebSearchValues): Promise<WebSearchConfig> {
    try {
      const apiKeyValue = values.api_key.trim();
      const updated = await updateWebSearchConfig({
        api_key: apiKeyValue || undefined,
        max_results: Number(values.max_results),
        search_depth: values.search_depth,
      });
      setWebSearchConfig(updated);
      setError(null);
      return updated;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      throw caught;
    }
  }

  function openConfigPanel() {
    setConfigOpen(true);
    setUserPanelOpen(false);
    setModelMenuOpen(false);
    setAttachmentMenuOpen(false);
  }

  function toggleUserPanel() {
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

  async function submitAuth(mode: AuthPanelMode, values: { username: string; password: string; confirmPassword: string }) {
    const user = await submitAuthRequest(mode, { username: values.username, password: values.password });
    if (user) await bootstrap();
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
    await logoutAuthSession();
    setUserPanelOpen(false);
    setProjects([]);
    setProjectConversations([]);
    setRecentConversations([]);
    setMessages([]);
    setProfiles([]);
    setWebSearchConfig(null);
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
    setError(null);
  }

  async function chooseModel(modelId: string) {
    if (!currentProfileId || !currentProfile) return;
    try {
      const updated = await updateProviderProfile(currentProfileId, { model: modelId });
      const nextProfiles = await listProviderProfiles();
      setProfiles(nextProfiles);
      setCurrentProfileId(updated.id);
      setModelMenuOpen(false);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  const workflowPanel = (
    <BidWorkflowPanel
      workflow={activeBidWorkflow}
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
      onDownloadArtifact={downloadArtifact}
      onDownloadZip={downloadArtifactsZip}
    />
  );

  if (authMode !== "ready") {
    return <AuthPanel mode={authMode} backendReady={authBackendReady} error={error} onModeChange={switchAuthMode} onSubmit={submitAuth} />;
  }

  return (
    <ErrorBoundary>
    <PanelGroup className="workbench-shell" data-sidebar={sidebarCollapsed ? "collapsed" : "expanded"} direction="horizontal" autoSaveId="bid-writer-workbench-layout">
      <Panel ref={sidebarPanelRef} id="workbench-sidebar" order={1} defaultSize={22} minSize={18} maxSize={36} collapsible collapsedSize={6} onCollapse={() => setSidebarCollapsed(true)} onExpand={() => setSidebarCollapsed(false)}>
        <WorkbenchSidebar
          collapsed={sidebarCollapsed}
          projects={projects}
          currentProjectId={currentProjectId}
          currentConversationId={currentConversationId}
          projectPreviewConversations={projectPreviewConversations}
          historyConversations={sidebarHistoryConversations}
          searchQuery={searchQuery}
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
          isBidBusy={isBidBusy}
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
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
      </Panel>
    </PanelGroup>
    </ErrorBoundary>
  );
}
