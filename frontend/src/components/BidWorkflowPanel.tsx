"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, History, Loader2, Pencil, RotateCcw, Save, WandSparkles, X } from "lucide-react";

import { getBidArtifactVersion, getBidArtifactVersionDiff, listBidArtifactVersions, restoreBidArtifactVersion, rewriteBidArtifactSection, updateBidArtifactContent } from "@/lib/api";
import type { BidArtifact, BidWorkflow } from "@/lib/types";
import styles from "./BidWorkflowPanel.module.css";

type BidWorkflowPanelProps = {
  workflow: BidWorkflow | null;
  workflows: BidWorkflow[];
  currentConversationId: string | null;
  confirmation: string;
  extraContext: string;
  isBusy: boolean;
  onConfirmationChange: (value: string) => void;
  onExtraContextChange: (value: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
  onGenerate: () => void;
  onRetry: () => void;
  onRefresh: () => Promise<void>;
  onSelectWorkflow: (workflow: BidWorkflow) => void;
  onDownloadArtifact: (name: string) => void;
  onDownloadZip: () => void;
};

function statusText(status: BidWorkflow["status"]): string {
  return {
    uploaded: "已上传",
    extracting: "阶段一提取中",
    extraction_ready: "待确认",
    generating: "阶段二生成中",
    completed: "已完成",
    failed: "执行失败",
    cancelled: "已取消",
  }[status];
}

function executionText(workflow: BidWorkflow): string {
  const execution = workflow.execution;
  if (!execution) return statusText(workflow.status);
  return `${execution.message || statusText(workflow.status)}${execution.state === "running" ? ` ${execution.progress}%` : ""}`;
}

function formatVersionTime(value: string): string {
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return "未知时间";
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(timestamp);
}

function ArtifactVersionPanel({ workflowId, artifact, onRefresh }: { workflowId: string; artifact: BidArtifact; onRefresh: () => Promise<void> }) {
  const queryClient = useQueryClient();
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [baseVersion, setBaseVersion] = useState<number | null>(null);
  const [compareVersion, setCompareVersion] = useState<number | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [draftContent, setDraftContent] = useState("");
  const versionsQuery = useQuery({
    queryKey: ["artifact-versions", workflowId, artifact.name],
    queryFn: () => listBidArtifactVersions(workflowId, artifact.name),
  });
  const contentQuery = useQuery({
    queryKey: ["artifact-version", workflowId, artifact.name, selectedVersion],
    queryFn: () => getBidArtifactVersion(workflowId, artifact.name, selectedVersion!),
    enabled: selectedVersion !== null,
  });
  const diffQuery = useQuery({
    queryKey: ["artifact-version-diff", workflowId, artifact.name, baseVersion, compareVersion],
    queryFn: () => getBidArtifactVersionDiff(workflowId, artifact.name, baseVersion!, compareVersion!),
    enabled: baseVersion !== null && compareVersion !== null && baseVersion !== compareVersion,
  });
  useEffect(() => {
    const versions = versionsQuery.data ?? [];
    if (versions.length < 2) return;
    setBaseVersion((current) => current ?? versions[1].version);
    setCompareVersion((current) => current ?? versions[0].version);
  }, [versionsQuery.data]);
  const restoreMutation = useMutation({
    mutationFn: () => restoreBidArtifactVersion(workflowId, artifact.name, selectedVersion!),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["artifact-versions", workflowId, artifact.name] });
      await onRefresh();
    },
  });
  const saveMutation = useMutation({
    mutationFn: () => updateBidArtifactContent(workflowId, artifact.name, draftContent),
    onSuccess: async () => {
      setIsEditing(false);
      await queryClient.invalidateQueries({ queryKey: ["artifact-versions", workflowId, artifact.name] });
      await queryClient.invalidateQueries({ queryKey: ["artifact-version", workflowId, artifact.name] });
      await onRefresh();
    },
  });
  const error = versionsQuery.error ?? contentQuery.error ?? diffQuery.error ?? restoreMutation.error ?? saveMutation.error;
  const versions = versionsQuery.data ?? [];

  return (
    <section className={styles.versionPanel} aria-label={`${artifact.name} 版本记录`}>
      <div className={styles.versionHeader}>
        <strong>版本记录</strong>
        <span>选择版本查看内容或恢复</span>
      </div>
      {versionsQuery.isLoading ? <div className="workflow-note">正在读取版本记录…</div> : (
        <div className={styles.versionList} role="list">
          {versions.map((item) => (
            <button
              type="button"
              key={item.version}
              className={selectedVersion === item.version ? styles.versionItemActive : styles.versionItem}
              aria-pressed={selectedVersion === item.version}
              onClick={() => setSelectedVersion(item.version)}
            >
              <span>v{item.version}</span>
              <time>{formatVersionTime(item.created_at)}</time>
              <em>{item.size.toLocaleString()} B</em>
            </button>
          ))}
        </div>
      )}
      {versions.length >= 2 && (
        <div className={styles.diffControls}>
          <label>
            基准版本
            <select value={baseVersion ?? ""} onChange={(event) => setBaseVersion(Number(event.target.value))} aria-label={`${artifact.name} 基准版本`}>
              {versions.map((item) => <option key={item.version} value={item.version}>v{item.version}</option>)}
            </select>
          </label>
          <label>
            对比版本
            <select value={compareVersion ?? ""} onChange={(event) => setCompareVersion(Number(event.target.value))} aria-label={`${artifact.name} 对比版本`}>
              {versions.map((item) => <option key={item.version} value={item.version}>v{item.version}</option>)}
            </select>
          </label>
        </div>
      )}
      {error && <div className="workflow-error">{error instanceof Error ? error.message : String(error)}</div>}
      {diffQuery.data && (
        <section className={styles.diffPanel} aria-label={`${artifact.name} 版本差异`}>
          <strong>v{diffQuery.data.base_version} → v{diffQuery.data.compare_version} 差异</strong>
          <pre>{diffQuery.data.lines.map((line, index) => <span className={line.kind === "added" ? styles.diffAdded : line.kind === "removed" ? styles.diffRemoved : styles.diffUnchanged} key={`${line.kind}-${index}`}>{line.kind === "added" ? "+ " : line.kind === "removed" ? "- " : "  "}{line.content || " "}{"\n"}</span>)}</pre>
        </section>
      )}
      {contentQuery.data && (
        <div className={styles.versionPreview}>
          <div className={styles.versionPreviewHeader}>
            <strong>v{contentQuery.data.version} 预览</strong>
            <div className={styles.versionActions}>
              {isEditing ? (
                <>
                  <button type="button" onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending || draftContent === contentQuery.data.content}>
                    <Save size={14} />
                    {saveMutation.isPending ? "保存中" : "保存新版本"}
                  </button>
                  <button type="button" onClick={() => setIsEditing(false)} disabled={saveMutation.isPending}>
                    <X size={14} />
                    取消
                  </button>
                </>
              ) : (
                <>
                  <button type="button" onClick={() => { setDraftContent(contentQuery.data.content); setIsEditing(true); }}>
                    <Pencil size={14} />
                    编辑此版本
                  </button>
                  <button type="button" onClick={() => restoreMutation.mutate()} disabled={restoreMutation.isPending}>
                    <RotateCcw size={14} />
                    {restoreMutation.isPending ? "恢复中" : "恢复为当前版本"}
                  </button>
                </>
              )}
            </div>
          </div>
          {isEditing ? (
            <label className={styles.editorLabel}>
              编辑内容
              <textarea value={draftContent} onChange={(event) => setDraftContent(event.target.value)} rows={14} aria-label={`编辑 v${contentQuery.data.version} 内容`} />
            </label>
          ) : <pre>{contentQuery.data.content}</pre>}
        </div>
      )}
    </section>
  );
}

function ArtifactSectionRewritePanel({ workflowId, artifact, onRefresh }: { workflowId: string; artifact: BidArtifact; onRefresh: () => Promise<void> }) {
  const queryClient = useQueryClient();
  const [isOpen, setIsOpen] = useState(false);
  const [heading, setHeading] = useState("");
  const [instruction, setInstruction] = useState("");
  const rewriteMutation = useMutation({
    mutationFn: () => rewriteBidArtifactSection(workflowId, artifact.name, { heading: heading.trim(), instruction: instruction.trim() }),
    onSuccess: async () => {
      setInstruction("");
      setIsOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["artifact-versions", workflowId, artifact.name] });
      await onRefresh();
    },
  });
  const canSubmit = heading.trim().length > 0 && instruction.trim().length > 0 && !rewriteMutation.isPending;

  return (
    <>
      <button type="button" className={styles.versionButton} onClick={() => setIsOpen((current) => !current)} aria-expanded={isOpen}>
        <WandSparkles size={14} />
        <span>AI 改章节</span>
      </button>
      {isOpen && (
        <form className={styles.rewritePanel} onSubmit={(event) => { event.preventDefault(); if (canSubmit) rewriteMutation.mutate(); }}>
          <label>
            章节标题
            <input value={heading} onChange={(event) => setHeading(event.target.value)} placeholder="例如：总体设计策略" aria-label={`${artifact.name} 章节标题`} />
          </label>
          <label>
            修改要求
            <textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} rows={3} placeholder="说明需要保留、补充或调整的内容" aria-label={`${artifact.name} 章节修改要求`} />
          </label>
          {rewriteMutation.error && <div className="workflow-error">{rewriteMutation.error instanceof Error ? rewriteMutation.error.message : String(rewriteMutation.error)}</div>}
          <div className={styles.rewriteActions}>
            <button type="button" onClick={() => setIsOpen(false)} disabled={rewriteMutation.isPending}>取消</button>
            <button type="submit" disabled={!canSubmit}>{rewriteMutation.isPending ? "正在重写…" : "仅重写此章节"}</button>
          </div>
        </form>
      )}
    </>
  );
}

export function BidWorkflowPanel({
  workflow,
  workflows,
  currentConversationId,
  confirmation,
  extraContext,
  isBusy,
  onConfirmationChange,
  onExtraContextChange,
  onCancel,
  onConfirm,
  onGenerate,
  onRetry,
  onRefresh,
  onSelectWorkflow,
  onDownloadArtifact,
  onDownloadZip,
}: BidWorkflowPanelProps) {
  const [versionArtifactName, setVersionArtifactName] = useState<string | null>(null);
  if (!workflow || workflow.conversation_id !== currentConversationId) return null;
  const proposal = workflow.artifacts.find((artifact) => artifact.kind === "proposal");
  const versionArtifact = workflow.artifacts.find((artifact) => artifact.name === versionArtifactName) ?? null;
  const conversationWorkflows = workflows.filter((item) => item.conversation_id === currentConversationId);

  return (
    <section className={`${styles.panel} workflow-panel`}>
      {conversationWorkflows.length > 1 && (
        <div className={styles.workflowSelector} role="tablist" aria-label="标段工作流">
          {conversationWorkflows.map((item) => (
            <button
              type="button"
              key={item.id}
              role="tab"
              aria-selected={item.id === workflow.id}
              className={item.id === workflow.id ? styles.workflowSelectorActive : styles.workflowSelectorItem}
              onClick={() => onSelectWorkflow(item)}
            >
              <span>{item.file_name}</span>
              <em>{executionText(item)}</em>
            </button>
          ))}
        </div>
      )}
      <div className="workflow-header">
        <div>
          <span>{executionText(workflow)}</span>
          <strong>{workflow.file_name}</strong>
        </div>
        <div className="workflow-header-tools">
          {["uploaded", "extracting", "extraction_ready", "generating", "failed"].includes(workflow.status) && (
            <>
              {["extracting", "generating"].includes(workflow.status) && <Loader2 size={18} className="spin-icon" />}
              <button type="button" onClick={onCancel}>取消</button>
            </>
          )}
          {workflow.status === "completed" && <CheckCircle2 size={18} />}
        </div>
      </div>

      {workflow.status === "extraction_ready" && !workflow.confirmation_text && (
        <div className="workflow-actions">
          <label>
            确认信息
            <textarea value={confirmation} onChange={(event) => onConfirmationChange(event.target.value)} rows={3} />
          </label>
          <button type="button" onClick={onConfirm} disabled={isBusy}>确认阶段一</button>
        </div>
      )}

      {workflow.confirmation_text && !["completed", "cancelled"].includes(workflow.status) && (
        <div className="workflow-actions">
          <div className="workflow-note">目录结构将按当前招标范围、评分、成果和格式要求动态编排，不套用固定模板。</div>
          <label>
            补充信息
            <textarea value={extraContext} onChange={(event) => onExtraContextChange(event.target.value)} rows={3} placeholder="企业优势、类似业绩、设计团队或章节偏好" />
          </label>
          <button type="button" onClick={onGenerate} disabled={isBusy || workflow.status === "generating"}>生成设计方案</button>
        </div>
      )}

      {workflow.status === "failed" && (
        <div className="workflow-error">
          <span>{workflow.error ?? "执行失败"}</span>
          <button type="button" onClick={onRetry} disabled={isBusy}>重试当前阶段</button>
        </div>
      )}

      {workflow.status === "completed" && (
        <div className="artifact-list">
          <div className="artifact-primary-actions">
            {proposal ? (
              <button type="button" className="artifact-primary-button" onClick={() => onDownloadArtifact(proposal.name)}>
                <Download size={15} />
                <span>下载 Markdown 文件</span>
              </button>
            ) : (
              <button type="button" className="artifact-primary-button" onClick={onRefresh}>
                <Download size={15} />
                <span>刷新成果文件</span>
              </button>
            )}
            {workflow.artifacts.length > 0 && (
              <button type="button" className="artifact-primary-button" onClick={onDownloadZip}>
                <Download size={15} />
                <span>下载 ZIP 包</span>
              </button>
            )}
          </div>
          {workflow.artifacts.length > 0 ? workflow.artifacts.map((artifact) => (
            <div className={styles.artifactRow} key={artifact.name}>
              <button type="button" onClick={() => onDownloadArtifact(artifact.name)}>
                <Download size={15} />
                <span>{artifact.name}</span>
              </button>
              <button type="button" className={styles.versionButton} onClick={() => setVersionArtifactName((current) => current === artifact.name ? null : artifact.name)} aria-expanded={versionArtifactName === artifact.name}>
                <History size={14} />
                <span>版本</span>
              </button>
              <ArtifactSectionRewritePanel workflowId={workflow.id} artifact={artifact} onRefresh={onRefresh} />
            </div>
          )) : <div className="workflow-note">阶段二已完成，正在等待成果文件同步。</div>}
          {versionArtifact && <ArtifactVersionPanel key={versionArtifact.name} workflowId={workflow.id} artifact={versionArtifact} onRefresh={onRefresh} />}
        </div>
      )}
    </section>
  );
}
