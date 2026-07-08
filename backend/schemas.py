from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


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


class BidWorkflowPublic(BaseModel):
    id: str
    project_id: str
    conversation_id: str
    provider_profile_id: Optional[str] = None
    file_name: str
    extracted_markdown: str = ""
    confirmation_text: str = ""
    template_choice: Optional[str] = None
    status: BidWorkflowStatus
    error: Optional[str] = None
    artifacts: List[ArtifactInfo] = Field(default_factory=list)
    created_at: str
    updated_at: str


class BidWorkflowCreateResponse(BidWorkflowPublic):
    char_count: int = 0
    message: str = ""


class BidWorkflowActionResponse(BaseModel):
    workflow: BidWorkflowPublic
    message: str = ""


class BidWorkflowConfirmRequest(BaseModel):
    text: str


class BidWorkflowGenerateRequest(BaseModel):
    template_choice: str = "auto"
    extra_context: Optional[str] = None


class AuthStatus(BaseModel):
    setup_required: bool
    authenticated: bool = False
    username: Optional[str] = None


class AuthSetupRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=6)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        username = value.strip()
        if not username:
            raise ValueError("用户名不能为空。")
        if len(username) > 64:
            raise ValueError("用户名不能超过 64 个字符。")
        return username


class AuthLoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        username = value.strip()
        if not username:
            raise ValueError("用户名不能为空。")
        return username


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


class WebSearchConfig(BaseModel):
    provider: str = "tavily"
    has_key: bool = False
    source: str = "none"  # "db" | "env" | "none"
    max_results: int = 5
    search_depth: str = "basic"


class WebSearchConfigUpdate(BaseModel):
    api_key: Optional[str] = None
    max_results: Optional[int] = Field(default=None, ge=1, le=10)
    search_depth: Optional[str] = None

    @field_validator("search_depth")
    @classmethod
    def validate_search_depth(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        depth = value.strip()
        if depth not in {"basic", "advanced"}:
            raise ValueError("search_depth 只能是 basic 或 advanced。")
        return depth


class ChatStreamRequest(BaseModel):
    conversation_id: Optional[str] = None
    project_id: Optional[str] = None
    provider_profile_id: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    message: str
    system_prompt: Optional[str] = None
    web_search_enabled: bool = False


class SearchResult(BaseModel):
    kind: str
    id: str
    title: str
    excerpt: str
    conversation_id: Optional[str] = None
    project_id: Optional[str] = None
