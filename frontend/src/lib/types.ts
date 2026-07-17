export type WorkbenchProject = {
  id: string;
  title: string;
  workspace_path?: string | null;
  created_at: string;
  updated_at: string;
};

export type WorkbenchConversation = {
  id: string;
  project_id: string;
  title: string;
  provider_profile_id?: string | null;
  model?: string | null;
  created_at: string;
  updated_at: string;
};

export type WorkbenchMessage = {
  id: string;
  conversation_id: string;
  role: "system" | "user" | "assistant" | string;
  content: string;
  status: "streaming" | "completed" | "interrupted" | "error" | string;
  model?: string | null;
  finish_reason?: string | null;
  usage?: Record<string, unknown> | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
};

export type ProviderProfile = {
  id: string;
  provider: string;
  display_name: string;
  base_url: string;
  model: string;
  has_key: boolean;
  created_at: string;
  updated_at: string;
};

export type ProviderModel = {
  id: string;
  name: string;
};

export type WebSearchConfig = {
  provider: "tavily" | string;
  has_key: boolean;
  source: "db" | "env" | "none" | string;
  max_results: number;
  search_depth: "basic" | "advanced" | string;
};

export type ProviderModelsResponse = {
  models: ProviderModel[];
};

export type BidWorkflowStatus = "uploaded" | "extracting" | "extraction_ready" | "generating" | "completed" | "failed" | "cancelled";

export type BidArtifact = {
  name: string;
  size: number;
  kind: "extraction" | "proposal" | "drawing" | "spec" | "file" | string;
};

export type ArtifactVersion = {
  name: string;
  version: number;
  size: number;
  created_at: string;
};

export type ArtifactVersionContent = ArtifactVersion & {
  content: string;
};

export type BidWorkflowExecution = {
  state: "queued" | "running" | "failed" | "cancelled" | "completed" | string;
  phase: "extraction" | "generation" | string;
  progress: number;
  message: string;
};

export type BidWorkflow = {
  id: string;
  project_id: string;
  conversation_id: string;
  provider_profile_id?: string | null;
  file_name: string;
  extracted_markdown: string;
  confirmation_text: string;
  template_choice?: string | null;
  status: BidWorkflowStatus;
  error?: string | null;
  execution?: BidWorkflowExecution | null;
  artifacts: BidArtifact[];
  created_at: string;
  updated_at: string;
};

export type BidWorkflowCreateResponse = BidWorkflow & {
  char_count: number;
  message: string;
};

export type BidWorkflowActionResponse = {
  workflow: BidWorkflow;
  message: string;
};

export type SearchResult = {
  kind: string;
  id: string;
  title: string;
  excerpt: string;
  conversation_id?: string | null;
  project_id?: string | null;
};

export type HealthResponse = {
  ok: boolean;
  app: string;
  version: string;
  database: string;
  presets: Record<string, { provider: string; base_url: string; model: string }>;
};

export type AuthStatus = {
  authenticated: boolean;
  username?: string | null;
  registration_allowed: boolean;
};

export type AuthLoginResponse = {
  token: string;
  expires_at: string;
  username: string;
};

export type AuthUser = {
  id: string;
  username: string;
  created_at: string;
  updated_at: string;
  last_login_at?: string | null;
};

export type ChatStreamEvent =
  | {
      event: "message_start";
      data: {
        conversation_id: string;
        message_id: string;
        user_message_id: string;
        run_id: string;
        model: string;
        usage?: Record<string, unknown> | null;
      };
    }
  | {
      event: "delta";
      data: {
        conversation_id: string;
        message_id: string;
        delta: string;
      };
    }
  | {
      event: "message_done";
      data: {
        conversation_id: string;
        message_id: string;
        status: "completed" | "interrupted" | "error";
        finish_reason?: string | null;
        usage?: Record<string, unknown> | null;
        content: string;
      };
    }
  | {
      event: "conversation_updated";
      data: {
        conversation_id: string;
        project_id: string;
        title: string;
      };
    }
  | {
      event: "error";
      data: {
        conversation_id?: string;
        message_id?: string;
        type: string;
        message: string;
        content?: string;
      };
    }
  | {
      event: "warning";
      data: {
        conversation_id?: string;
        message_id?: string;
        type: string;
        message: string;
      };
    };
