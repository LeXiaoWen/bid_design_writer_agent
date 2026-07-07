from dataclasses import dataclass, field
from typing import Dict, List, Optional
from uuid import uuid4

from ..schemas import Message, ProjectStage
from .artifacts import list_artifacts
from .skill_loader import resolve_skill_dir


@dataclass
class Project:
    project_id: str
    stage: ProjectStage = ProjectStage.INIT
    messages: List[Message] = field(default_factory=list)
    file_name: Optional[str] = None
    file_text: str = ""
    extracted_markdown: str = ""
    template_choice: str = ""
    artifacts: Dict[str, str] = field(default_factory=dict)

    def add_message(self, role: str, content: str) -> None:
        self.messages.append(Message(role=role, content=content))


class ProjectStore:
    def __init__(self) -> None:
        self._projects: Dict[str, Project] = {}

    def create(self) -> Project:
        project = Project(project_id=str(uuid4()))
        project.add_message(
            "assistant",
            "请先配置 OpenAI 兼容 API 并上传招标文件。我会先提取关键信息，待你确认后再生成设计方案。",
        )
        self._projects[project.project_id] = project
        return project

    def get(self, project_id: str) -> Project:
        if project_id not in self._projects:
            raise KeyError(project_id)
        return self._projects[project_id]

    def to_response(self, project: Project):
        from ..schemas import ProjectResponse

        return ProjectResponse(
            project_id=project.project_id,
            stage=project.stage,
            messages=project.messages,
            file_name=project.file_name,
            skill_dir=str(resolve_skill_dir()),
            extracted_markdown=project.extracted_markdown,
            template_choice=project.template_choice,
            artifacts=list_artifacts(project.artifacts),
        )


store = ProjectStore()
