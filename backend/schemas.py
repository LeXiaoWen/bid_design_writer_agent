from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ProjectStage(str, Enum):
    INIT = "init"
    UPLOADED = "uploaded"
    CONFIRMING = "confirming"
    TEMPLATE_SELECT = "template_select"
    GENERATING = "generating"
    DONE = "done"


class BidWorkflowStatus(str, Enum):
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    EXTRACTION_READY = "extraction_ready"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApiConfig(BaseModel):
    provider: str = "OpenAI"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = Field(min_length=1)
    model: str = "gpt-4o"


class Message(BaseModel):
    role: str
    content: str


class ArtifactInfo(BaseModel):
    name: str
    size: int
    kind: str


class BidWorkflow(BaseModel):
    id: str
    project_id: str
    conversation_id: str
    provider_profile_id: Optional[str] = None
    file_name: str
    file_text: str = ""
    extracted_markdown: str = ""
    confirmation_text: str = ""
    template_choice: Optional[str] = None
    status: BidWorkflowStatus
    error: Optional[str] = None
    artifacts: List[ArtifactInfo] = Field(default_factory=list)
    created_at: str
    updated_at: str


class BidWorkflowCreateResponse(BidWorkflow):
    char_count: int = 0
    message: str = ""


class BidWorkflowActionResponse(BaseModel):
    workflow: BidWorkflow
    message: str = ""


class BidWorkflowConfirmRequest(BaseModel):
    text: str


class BidWorkflowGenerateRequest(BaseModel):
    template_choice: str = "auto"
    extra_context: Optional[str] = None


class BehaviorReportEmail(BaseModel):
    id: str
    workflow_id: str
    recipient: str
    status: str
    error: Optional[str] = None
    zip_size: int = 0
    created_at: str
    sent_at: Optional[str] = None


class AuthStatus(BaseModel):
    setup_required: bool
    authenticated: bool = False
    username: Optional[str] = None


class AuthSetupRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=6)


class AuthLoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class AuthLoginResponse(BaseModel):
    token: str
    expires_at: str
    username: str


class AuthUser(BaseModel):
    id: str
    username: str
    created_at: str
    updated_at: str
    last_login_at: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=6)


class ProjectResponse(BaseModel):
    project_id: str
    stage: ProjectStage
    messages: List[Message]
    file_name: Optional[str] = None
    skill_dir: str
    extracted_markdown: str = ""
    template_choice: str = ""
    artifacts: List[ArtifactInfo] = []


class UploadResponse(BaseModel):
    project_id: str
    stage: ProjectStage
    file_name: str
    char_count: int
    message: str


class ExtractRequest(BaseModel):
    api_config: ApiConfig


class ConfirmRequest(BaseModel):
    text: str
    api_config: Optional[ApiConfig] = None


class GenerateRequest(BaseModel):
    template_choice: str
    api_config: ApiConfig


class TextResponse(BaseModel):
    project_id: str
    stage: ProjectStage
    message: str
    extracted_markdown: str = ""
    artifacts: Dict[str, str] = {}


class Preset(BaseModel):
    provider: str
    base_url: str
    model: str


class WorkbenchProject(BaseModel):
    id: str
    title: str
    workspace_path: Optional[str] = None
    created_at: str
    updated_at: str


class WorkbenchProjectCreate(BaseModel):
    title: str = "新项目"
    workspace_path: Optional[str] = None


class WorkbenchProjectUpdate(BaseModel):
    title: Optional[str] = None
    workspace_path: Optional[str] = None


class WorkbenchConversation(BaseModel):
    id: str
    project_id: str
    title: str
    provider_profile_id: Optional[str] = None
    model: Optional[str] = None
    created_at: str
    updated_at: str


class WorkbenchConversationCreate(BaseModel):
    project_id: Optional[str] = None
    title: str = "新对话"
    provider_profile_id: Optional[str] = None
    model: Optional[str] = None


class WorkbenchConversationUpdate(BaseModel):
    title: Optional[str] = None
    provider_profile_id: Optional[str] = None
    model: Optional[str] = None


class WorkbenchMessage(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    status: str = "completed"
    model: Optional[str] = None
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str


class ProviderProfile(BaseModel):
    id: str
    provider: str
    display_name: str
    base_url: str
    model: str
    credential_key: str
    has_key: bool = False
    created_at: str
    updated_at: str


class ProviderModel(BaseModel):
    id: str
    name: str


class ProviderModelsResponse(BaseModel):
    models: List[ProviderModel] = Field(default_factory=list)


class ProviderProfileCreate(BaseModel):
    provider: str = "OpenAI"
    display_name: str = "OpenAI"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"
    api_key: Optional[str] = None


class ProviderProfileUpdate(BaseModel):
    provider: Optional[str] = None
    display_name: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None


class ChatStreamRequest(BaseModel):
    conversation_id: Optional[str] = None
    project_id: Optional[str] = None
    provider_profile_id: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    message: str
    system_prompt: Optional[str] = None


class SearchResult(BaseModel):
    kind: str
    id: str
    title: str
    excerpt: str
    conversation_id: Optional[str] = None
    project_id: Optional[str] = None
