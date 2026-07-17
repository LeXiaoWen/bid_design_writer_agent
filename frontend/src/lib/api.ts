import type {
  AuthLoginResponse,
  AuthStatus,
  AuthUser,
  ArtifactVersion,
  ArtifactVersionContent,
  BidArtifact,
  BidWorkflowStreamEvent,
  BidWorkflow,
  BidWorkflowActionResponse,
  BidWorkflowCreateResponse,
  ChatStreamEvent,
  HealthResponse,
  ProviderModel,
  ProviderProfile,
  SearchResult,
  SearchResultKind,
  WebSearchConfig,
  WorkbenchConversation,
  WorkbenchMessage,
  WorkbenchProject,
} from "./types";

let apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8765";

let authToken: string | null = null;
let appAuthSecret: string | null = null;
const APP_AUTH_SECRET_STORAGE_KEY = "ai-workbench-app-auth-secret";
const LOCAL_BACKEND_RETRY_ATTEMPTS = 10;
const LOCAL_BACKEND_RETRY_DELAY_MS = 250;

export function setApiBaseUrl(url: string | null | undefined): void {
  if (url) apiBaseUrl = url.replace(/\/$/, "");
}

export function setAuthContext(next: { token?: string | null; appSecret?: string | null }): void {
  if ("token" in next) authToken = next.token ?? null;
  if ("appSecret" in next) {
    appAuthSecret = next.appSecret ?? null;
    if (typeof window !== "undefined") {
      if (appAuthSecret) {
        window.sessionStorage.setItem(APP_AUTH_SECRET_STORAGE_KEY, appAuthSecret);
      } else {
        window.sessionStorage.removeItem(APP_AUTH_SECRET_STORAGE_KEY);
      }
    }
  }
}

function currentAppAuthSecret(): string | null {
  if (appAuthSecret) return appAuthSecret;
  if (typeof window === "undefined") return null;
  appAuthSecret = window.sessionStorage.getItem(APP_AUTH_SECRET_STORAGE_KEY);
  return appAuthSecret;
}

function withAuthHeaders(options?: RequestInit): RequestInit {
  const headers = new Headers(options?.headers);
  if (authToken) headers.set("Authorization", `Bearer ${authToken}`);
  const secret = currentAppAuthSecret();
  if (secret) headers.set("X-App-Auth-Secret", secret);
  return { ...options, headers };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function localBackendConnectionError(): Error {
  return new Error(`无法连接本地后端：${apiBaseUrl}。请确认桌面应用后端已启动，或检查当前页面地址是否被 CORS 允许。`);
}

async function fetchWithLocalRetry(url: string, options?: RequestInit): Promise<Response> {
  let lastError: unknown = null;
  for (let attempt = 0; attempt < LOCAL_BACKEND_RETRY_ATTEMPTS; attempt += 1) {
    try {
      return await fetch(url, options);
    } catch (caught) {
      lastError = caught;
      await sleep(LOCAL_BACKEND_RETRY_DELAY_MS);
    }
  }
  throw lastError instanceof Error ? localBackendConnectionError() : localBackendConnectionError();
}

async function requestOnce(path: string, options?: RequestInit): Promise<Response> {
  try {
    return await fetch(`${apiBaseUrl}${path}`, withAuthHeaders(options));
  } catch {
    throw localBackendConnectionError();
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetchWithLocalRetry(`${apiBaseUrl}${path}`, withAuthHeaders(options));
  } catch (error) {
    throw localBackendConnectionError();
  }
  if (!response.ok) {
    if (response.status === 401 && authToken && !path.startsWith("/api/v1/auth/")) {
      window.dispatchEvent(new Event("ai-workbench-auth-expired"));
    }
    let detail = `请求失败：${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail ?? detail;
    } catch {
      // Keep the status fallback when the body is not JSON.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

/** 单次请求，不重试。用于状态轮询场景，由外层控制重试节奏。 */
async function quickRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await requestOnce(path, options);
  if (!response.ok) {
    let detail = `请求失败：${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail ?? detail;
    } catch {
      // Keep the status fallback.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

export function getAuthStatus(): Promise<AuthStatus> {
  return quickRequest<AuthStatus>("/api/v1/auth/status");
}

export function registerAuth(input: { username: string; password: string }): Promise<AuthLoginResponse> {
  return request<AuthLoginResponse>("/api/v1/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function loginAuth(input: { username: string; password: string }): Promise<AuthLoginResponse> {
  return request<AuthLoginResponse>("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function logoutAuth(): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("/api/v1/auth/logout", { method: "POST" });
}

export function getMe(): Promise<AuthUser> {
  return request<AuthUser>("/api/v1/me");
}

export function changePassword(input: { current_password: string; new_password: string }): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("/api/v1/auth/change-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function listProjects(): Promise<WorkbenchProject[]> {
  return request<WorkbenchProject[]>("/api/v1/projects");
}

export function createProject(input: { title?: string; workspace_path?: string } = {}): Promise<WorkbenchProject> {
  return request<WorkbenchProject>("/api/v1/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: input.title ?? "新项目", workspace_path: input.workspace_path }),
  });
}

export function deleteProject(projectId: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/v1/projects/${projectId}`, { method: "DELETE" });
}

export function listConversations(projectId?: string): Promise<WorkbenchConversation[]> {
  const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  return request<WorkbenchConversation[]>(`/api/v1/conversations${suffix}`);
}

export function createConversation(input: {
  project_id?: string;
  title?: string;
  provider_profile_id?: string;
  model?: string;
}): Promise<WorkbenchConversation> {
  return request<WorkbenchConversation>("/api/v1/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function listMessages(conversationId: string): Promise<WorkbenchMessage[]> {
  return request<WorkbenchMessage[]>(`/api/v1/conversations/${conversationId}/messages`);
}

export function deleteConversation(conversationId: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/v1/conversations/${conversationId}`, { method: "DELETE" });
}

export function listProviderProfiles(): Promise<ProviderProfile[]> {
  return request<ProviderProfile[]>("/api/v1/provider-profiles");
}

export function createProviderProfile(input: {
  provider: string;
  display_name: string;
  base_url: string;
  model: string;
  api_key?: string;
}): Promise<ProviderProfile> {
  return request<ProviderProfile>("/api/v1/provider-profiles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function updateProviderProfile(
  profileId: string,
  input: Partial<{
    provider: string;
    display_name: string;
    base_url: string;
    model: string;
    api_key: string;
  }>,
): Promise<ProviderProfile> {
  return request<ProviderProfile>(`/api/v1/provider-profiles/${profileId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function listProviderModels(profileId: string): Promise<ProviderModel[]> {
  const payload = await request<{ models: ProviderModel[] }>(`/api/v1/provider-profiles/${profileId}/models`);
  return payload.models;
}

export function searchWorkbench(query: string, kind?: SearchResultKind): Promise<SearchResult[]> {
  const filter = kind ? `&kind=${encodeURIComponent(kind)}` : "";
  return request<SearchResult[]>(`/api/v1/search?q=${encodeURIComponent(query)}${filter}`);
}

export function getWebSearchConfig(): Promise<WebSearchConfig> {
  return request<WebSearchConfig>("/api/v1/web-search-config");
}

export function updateWebSearchConfig(input: {
  api_key?: string;
  max_results?: number;
  search_depth?: string;
}): Promise<WebSearchConfig> {
  return request<WebSearchConfig>("/api/v1/web-search-config", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function cancelChat(runId: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/v1/chat/${runId}/cancel`, { method: "POST" });
}

export function createBidWorkflow(input: {
  conversation_id: string;
  provider_profile_id: string;
  file: File;
  onProgress?: (progress: number) => void;
}): Promise<BidWorkflowCreateResponse> {
  const formData = new FormData();
  formData.append("conversation_id", input.conversation_id);
  formData.append("provider_profile_id", input.provider_profile_id);
  formData.append("file", input.file);

  if (!input.onProgress) {
    return request<BidWorkflowCreateResponse>("/api/v1/bid-workflows", {
      method: "POST",
      body: formData,
    });
  }

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${apiBaseUrl}/api/v1/bid-workflows`);
    if (authToken) xhr.setRequestHeader("Authorization", `Bearer ${authToken}`);
    if (appAuthSecret) xhr.setRequestHeader("X-App-Auth-Secret", appAuthSecret);
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) return;
      input.onProgress?.(Math.min(95, Math.round((event.loaded / event.total) * 100)));
    };
    xhr.upload.onload = () => input.onProgress?.(100);
    xhr.onerror = () => reject(new Error(`无法连接本地后端：${apiBaseUrl}。请确认桌面应用后端已启动，或检查当前页面地址是否被 CORS 允许。`));
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        input.onProgress?.(100);
        resolve(JSON.parse(xhr.responseText) as BidWorkflowCreateResponse);
        return;
      }
      let detail = `请求失败：${xhr.status}`;
      try {
        const payload = JSON.parse(xhr.responseText);
        detail = payload.detail ?? detail;
      } catch {
        // Keep the status fallback when the body is not JSON.
      }
      reject(new Error(detail));
    };
    xhr.send(formData);
  });
}

export function getBidWorkflow(workflowId: string): Promise<BidWorkflow> {
  return request<BidWorkflow>(`/api/v1/bid-workflows/${workflowId}`);
}

export function listBidWorkflows(conversationId?: string): Promise<BidWorkflow[]> {
  const suffix = conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : "";
  return request<BidWorkflow[]>(`/api/v1/bid-workflows${suffix}`);
}

export function extractBidWorkflow(workflowId: string): Promise<BidWorkflowActionResponse> {
  return request<BidWorkflowActionResponse>(`/api/v1/bid-workflows/${workflowId}/extract`, { method: "POST" });
}

export function confirmBidWorkflow(workflowId: string, text: string): Promise<BidWorkflowActionResponse> {
  return request<BidWorkflowActionResponse>(`/api/v1/bid-workflows/${workflowId}/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}

export function generateBidWorkflow(
  workflowId: string,
  input: {
    extra_context?: string;
  },
): Promise<BidWorkflowActionResponse> {
  return request<BidWorkflowActionResponse>(`/api/v1/bid-workflows/${workflowId}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function cancelBidWorkflow(workflowId: string): Promise<BidWorkflowActionResponse> {
  return request<BidWorkflowActionResponse>(`/api/v1/bid-workflows/${workflowId}/cancel`, { method: "POST" });
}

export function listBidArtifacts(workflowId: string): Promise<BidArtifact[]> {
  return request<BidArtifact[]>(`/api/v1/bid-workflows/${workflowId}/artifacts`);
}

export function listBidArtifactVersions(workflowId: string, artifactName: string): Promise<ArtifactVersion[]> {
  return request<ArtifactVersion[]>(`/api/v1/bid-workflows/${workflowId}/artifacts/versions?name=${encodeURIComponent(artifactName)}`);
}

export function getBidArtifactVersion(workflowId: string, artifactName: string, version: number): Promise<ArtifactVersionContent> {
  return request<ArtifactVersionContent>(`/api/v1/bid-workflows/${workflowId}/artifacts/${encodeURIComponent(artifactName)}/versions/${version}`);
}

export function restoreBidArtifactVersion(workflowId: string, artifactName: string, version: number): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/v1/bid-workflows/${workflowId}/artifacts/${encodeURIComponent(artifactName)}/versions/${version}/restore`, { method: "POST" });
}

export function updateBidArtifactContent(workflowId: string, artifactName: string, content: string): Promise<BidArtifact> {
  return request<BidArtifact>(`/api/v1/bid-workflows/${workflowId}/artifacts/${encodeURIComponent(artifactName)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

export function downloadBidArtifactUrl(workflowId: string, artifactName: string): string {
  return `${apiBaseUrl}/api/v1/bid-workflows/${workflowId}/artifacts/${encodeURIComponent(artifactName)}`;
}

export function downloadBidZipUrl(workflowId: string): string {
  return `${apiBaseUrl}/api/v1/bid-workflows/${workflowId}/export.zip`;
}

export async function downloadBidArtifact(workflowId: string, artifactName: string): Promise<Blob> {
  const response = await fetch(downloadBidArtifactUrl(workflowId, artifactName), withAuthHeaders());
  if (!response.ok) throw new Error(`下载失败：${response.status}`);
  return response.blob();
}

export async function downloadBidZip(workflowId: string): Promise<Blob> {
  const response = await fetch(downloadBidZipUrl(workflowId), withAuthHeaders());
  if (!response.ok) throw new Error(`下载失败：${response.status}`);
  return response.blob();
}

export async function streamChat(
  input: {
    conversation_id?: string;
    project_id?: string;
    provider_profile_id?: string;
    model?: string;
    api_key?: string;
    message: string;
    system_prompt?: string;
    web_search_enabled?: boolean;
  },
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  try {
    const requestOptions = withAuthHeaders({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    await fetchEventSource(`${apiBaseUrl}/api/v1/chat/stream`, {
      method: "POST",
      headers: Object.fromEntries(new Headers(requestOptions.headers).entries()),
      body: requestOptions.body as string,
      signal,
      openWhenHidden: true,
      async onopen(response) {
        if (response.ok && response.headers.get("content-type")?.includes("text/event-stream")) return;
        if (response.status === 401 && authToken) {
          window.dispatchEvent(new Event("ai-workbench-auth-expired"));
        }
        let detail = `请求失败：${response.status}`;
        try {
          const payload = await response.json();
          detail = payload.detail ?? detail;
        } catch {
          // Keep the HTTP fallback if an upstream response has no JSON body.
        }
        throw new Error(detail);
      },
      onmessage(message) {
        if (!message.event || !message.data) return;
        try {
          onEvent({ event: message.event as ChatStreamEvent["event"], data: JSON.parse(message.data) } as ChatStreamEvent);
        } catch {
          throw new Error("本地后端返回了无法识别的流式消息。" );
        }
      },
      onerror(error) {
        // Re-throwing disables the library's automatic reconnect: replaying a POST could bill the LLM twice.
        throw error;
      },
    });
  } catch (error) {
    if (signal?.aborted) return;
    if (error instanceof Error) throw error;
    throw localBackendConnectionError();
  }
}

export async function streamBidWorkflow(
  workflowId: string,
  onEvent: (event: BidWorkflowStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  try {
    const requestOptions = withAuthHeaders();
    await fetchEventSource(`${apiBaseUrl}/api/v1/bid-workflows/${encodeURIComponent(workflowId)}/stream`, {
      headers: Object.fromEntries(new Headers(requestOptions.headers).entries()),
      signal,
      openWhenHidden: true,
      async onopen(response) {
        if (response.ok && response.headers.get("content-type")?.includes("text/event-stream")) return;
        let detail = `请求失败：${response.status}`;
        try {
          const payload = await response.json();
          detail = payload.detail ?? detail;
        } catch {
          // Keep the HTTP fallback if an upstream response has no JSON body.
        }
        throw new Error(detail);
      },
      onmessage(message) {
        if (!message.event || !message.data) return;
        onEvent({ event: message.event, data: JSON.parse(message.data) } as BidWorkflowStreamEvent);
      },
      onerror(error) {
        throw error;
      },
    });
  } catch (error) {
    if (signal?.aborted) return;
    if (error instanceof Error) throw error;
    throw localBackendConnectionError();
  }
}
import { fetchEventSource } from "@microsoft/fetch-event-source";
