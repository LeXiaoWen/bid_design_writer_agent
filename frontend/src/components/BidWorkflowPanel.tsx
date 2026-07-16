"use client";

import { CheckCircle2, Download, Loader2 } from "lucide-react";

import type { BidWorkflow } from "@/lib/types";
import styles from "./BidWorkflowPanel.module.css";

type BidWorkflowPanelProps = {
  workflow: BidWorkflow | null;
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
  onRefresh: () => void;
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

export function BidWorkflowPanel({
  workflow,
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
  onDownloadArtifact,
  onDownloadZip,
}: BidWorkflowPanelProps) {
  if (!workflow || workflow.conversation_id !== currentConversationId) return null;
  const proposal = workflow.artifacts.find((artifact) => artifact.kind === "proposal");

  return (
    <section className={`${styles.panel} workflow-panel`}>
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
            <button type="button" key={artifact.name} onClick={() => onDownloadArtifact(artifact.name)}>
              <Download size={15} />
              <span>{artifact.name}</span>
            </button>
          )) : <div className="workflow-note">阶段二已完成，正在等待成果文件同步。</div>}
        </div>
      )}
    </section>
  );
}
