"use client";

import {
  ChevronRight,
  FolderKanban,
  FolderOpen,
  House,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Settings2,
  SquarePen,
  Trash2,
} from "lucide-react";

import type { AuthUser, SearchResult, WorkbenchConversation, WorkbenchProject } from "@/lib/types";
import styles from "./WorkbenchSidebar.module.css";

type WorkbenchSidebarProps = {
  collapsed: boolean;
  projects: WorkbenchProject[];
  currentProjectId: string | null;
  currentConversationId: string | null;
  projectPreviewConversations: WorkbenchConversation[];
  historyConversations: WorkbenchConversation[];
  searchQuery: string;
  searchResults: SearchResult[];
  projectsOpen: boolean;
  projectConversationsOpen: boolean;
  conversationsOpen: boolean;
  authUser: AuthUser | null;
  userPanelOpen: boolean;
  onToggleSidebar: () => void;
  onStartNewChat: () => void;
  onFocusSearch: () => void;
  onOpenConfig: () => void;
  onSearchQueryChange: (value: string) => void;
  onToggleProjects: () => void;
  onChooseWorkspace: () => void;
  onSwitchProject: (project: WorkbenchProject) => void;
  onToggleProjectConversations: () => void;
  onRemoveProject: (project: WorkbenchProject) => void;
  onOpenConversation: (conversationId: string) => void;
  onRemoveConversation: (conversation: WorkbenchConversation) => void;
  onToggleConversations: () => void;
  onToggleUserPanel: () => void;
};

function userInitials(user: AuthUser | null): string {
  const name = user?.username.trim();
  return name ? name.slice(0, 2).toUpperCase() : "未";
}

function relativeTime(value: string): string {
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return "";
  const minutes = Math.max(0, Math.round((Date.now() - timestamp) / 60_000));
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} 小时`;
  return `${Math.round(hours / 24)} 天`;
}

export function WorkbenchSidebar({
  collapsed,
  projects,
  currentProjectId,
  currentConversationId,
  projectPreviewConversations,
  historyConversations,
  searchQuery,
  searchResults,
  projectsOpen,
  projectConversationsOpen,
  conversationsOpen,
  authUser,
  userPanelOpen,
  onToggleSidebar,
  onStartNewChat,
  onFocusSearch,
  onOpenConfig,
  onSearchQueryChange,
  onToggleProjects,
  onChooseWorkspace,
  onSwitchProject,
  onToggleProjectConversations,
  onRemoveProject,
  onOpenConversation,
  onRemoveConversation,
  onToggleConversations,
  onToggleUserPanel,
}: WorkbenchSidebarProps) {
  return (
    <aside className={`${styles.sidebar} sidebar`}>
      <div className="sidebar-top">
        {!collapsed && <div className="app-mark">建筑设计标书方案助手</div>}
        <button className="ghost-icon" onClick={onToggleSidebar} aria-label="折叠菜单">
          {collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
        </button>
      </div>

      <div className="menu-block">
        <button className="menu-command" onClick={onStartNewChat} title="新对话">
          <SquarePen size={19} />
          {!collapsed && <span>新对话</span>}
        </button>
        <button className="menu-command" onClick={onFocusSearch} title="搜索">
          <Search size={19} />
          {!collapsed && <span>搜索</span>}
        </button>
        <button className="menu-command" onClick={onOpenConfig} title="模型配置">
          <Settings2 size={19} />
          {!collapsed && <span>模型配置</span>}
        </button>
      </div>

      <div className="sidebar-section">
        {!collapsed && (
          <button className="section-label section-toggle" onClick={onToggleProjects}>
            项目
            <ChevronRight className={projectsOpen ? "chevron open" : "chevron"} size={15} />
          </button>
        )}
        {!collapsed && (
          <div className="search-box">
            <Search size={16} />
            <input value={searchQuery} onChange={(event) => onSearchQueryChange(event.target.value)} placeholder="搜索项目、历史对话" />
          </div>
        )}
        {!collapsed && searchResults.length > 0 && (
          <div className="search-results">
            {searchResults.map((result) => (
              <button key={`${result.kind}-${result.id}`} onClick={() => result.conversation_id && onOpenConversation(result.conversation_id)}>
                <strong>{result.title}</strong>
                <span>{result.excerpt}</span>
              </button>
            ))}
          </div>
        )}
        {projectsOpen && (
          <div className="nav-list">
            {!collapsed && (
              <button type="button" className="workspace-picker-row" onClick={onChooseWorkspace}>
                <FolderOpen size={17} />
                <span>选择本地文件夹</span>
              </button>
            )}
            {projects.map((project) => (
              <div className="project-group" key={project.id}>
                <div className={project.id === currentProjectId ? "sidebar-item-shell project-shell active" : "sidebar-item-shell"}>
                  <button className="project-row" onClick={() => onSwitchProject(project)} title={project.workspace_path ? `${project.title}\n${project.workspace_path}` : project.title}>
                    {project.workspace_path ? <FolderKanban size={18} /> : <House size={18} />}
                    {!collapsed && <span>{project.title}</span>}
                  </button>
                  {!collapsed && project.workspace_path && project.id === currentProjectId && (
                    <button type="button" className="project-expand-toggle" onClick={onToggleProjectConversations} aria-label={projectConversationsOpen ? `收起 ${project.title} 的对话` : `展开 ${project.title} 的对话`}>
                      <ChevronRight className={projectConversationsOpen ? "chevron open" : "chevron"} size={15} />
                    </button>
                  )}
                  {!collapsed && (
                    <button type="button" className="row-delete" onClick={() => onRemoveProject(project)} aria-label={`删除项目 ${project.title}`}>
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
                {!collapsed && project.workspace_path && project.id === currentProjectId && projectConversationsOpen && projectPreviewConversations.map((conversation) => (
                  <div className={conversation.id === currentConversationId ? "sidebar-item-shell project-chat-shell active" : "sidebar-item-shell project-chat-shell"} key={conversation.id}>
                    <button className="project-chat-row" onClick={() => onOpenConversation(conversation.id)} title={conversation.title}>
                      <span>{conversation.title}</span>
                      <time>{relativeTime(conversation.updated_at)}</time>
                    </button>
                    <button type="button" className="row-delete" onClick={() => onRemoveConversation(conversation)} aria-label={`删除对话 ${conversation.title}`}>
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
        {!collapsed && (
          <button className="section-label section-toggle" onClick={onToggleConversations}>
            对话
            <ChevronRight className={conversationsOpen ? "chevron open" : "chevron"} size={15} />
          </button>
        )}
        {conversationsOpen && (
          <div className="nav-list history-list">
            {historyConversations.length === 0 && !collapsed ? (
              <div className="empty-sidebar">暂无其他对话</div>
            ) : (
              historyConversations.map((conversation) => (
                <div className={conversation.id === currentConversationId ? "sidebar-item-shell conversation-shell active" : "sidebar-item-shell conversation-shell"} key={conversation.id}>
                  <button className="conversation-row" onClick={() => onOpenConversation(conversation.id)} title={conversation.title}>
                    <MessageSquare size={16} />
                    {!collapsed && <span>{conversation.title}</span>}
                    {!collapsed && <time>{relativeTime(conversation.updated_at)}</time>}
                  </button>
                  {!collapsed && (
                    <button type="button" className="row-delete" onClick={() => onRemoveConversation(conversation)} aria-label={`删除对话 ${conversation.title}`}>
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
              ))
            )}
          </div>
        )}
      </div>

      <button type="button" className="account-card" onClick={onToggleUserPanel} title="用户信息">
        <div className="account-avatar">{userInitials(authUser)}</div>
        {!collapsed && (
          <div className="account-copy">
            <strong>{authUser?.username ?? "未登录"}</strong>
            <span>本机账号</span>
          </div>
        )}
        {!collapsed && <ChevronRight className={userPanelOpen ? "chevron open" : "chevron"} size={16} />}
      </button>
    </aside>
  );
}
