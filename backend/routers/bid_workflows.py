from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile

from ..schemas import (
    BidWorkflowActionResponse,
    BidWorkflowConfirmRequest,
    BidWorkflowCreateResponse,
    BidWorkflowGenerateRequest,
    BidWorkflowPublic,
    BidWorkflowStatus,
)
from ..services.workbench_store import workbench_store
from .dependencies import current_user


def create_router(
    *,
    api_config_from_profile: Callable[[str, str], Any],
    read_upload_with_limit: Callable[[UploadFile], Awaitable[bytes]],
    parse_document: Callable[[str, bytes], str],
    enqueue_bid_job: Callable[[str, str, str], Any],
    public_bid_workflow: Callable[[Any], BidWorkflowPublic],
    save_behavior_report: Callable[[str, str], Any],
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/bid-workflows", response_model=BidWorkflowCreateResponse)
    async def create_bid_workflow(
        request: Request,
        conversation_id: str = Form(...),
        provider_profile_id: str = Form(...),
        file: UploadFile = File(...),
    ):
        user_id = current_user(request).id
        try:
            workbench_store.get_conversation(user_id, conversation_id)
            api_config_from_profile(user_id, provider_profile_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="对话或模型配置不存在。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        file_name = file.filename or "uploaded"
        try:
            content = await read_upload_with_limit(file)
            file_text = parse_document(file_name, content)
            workflow = workbench_store.create_bid_workflow(user_id, conversation_id, file_name, file_text, provider_profile_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="对话或模型配置不存在。") from exc

        workbench_store.add_message(user_id, conversation_id, "user", f"已上传招标文件：{file_name}")
        workbench_store.add_message(user_id, conversation_id, "assistant", "文件已解析。可以开始阶段一信息提取。")
        return BidWorkflowCreateResponse(**workflow.model_dump(exclude={"file_text"}), char_count=len(file_text), message="文件解析完成。")

    @router.get("/api/v1/bid-workflows", response_model=list[BidWorkflowPublic])
    def list_bid_workflows(request: Request, conversation_id: str | None = Query(default=None)):
        return [public_bid_workflow(workflow) for workflow in workbench_store.list_bid_workflows(current_user(request).id, conversation_id)]

    @router.get("/api/v1/bid-workflows/{workflow_id}", response_model=BidWorkflowPublic)
    def get_bid_workflow(workflow_id: str, request: Request):
        try:
            return public_bid_workflow(workbench_store.get_bid_workflow(current_user(request).id, workflow_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="标书工作流不存在。") from exc

    @router.post("/api/v1/bid-workflows/{workflow_id}/extract", response_model=BidWorkflowActionResponse)
    def extract_bid_workflow(workflow_id: str, request: Request):
        user_id = current_user(request).id
        try:
            workflow = workbench_store.get_bid_workflow(user_id, workflow_id)
            api_config_from_profile(user_id, workflow.provider_profile_id or "")
            if workflow.status in {BidWorkflowStatus.EXTRACTING, BidWorkflowStatus.GENERATING}:
                raise ValueError("当前工作流正在执行中。")
            if workflow.status == BidWorkflowStatus.COMPLETED:
                raise ValueError("当前工作流已完成。")
            workflow = workbench_store.update_bid_workflow_status(user_id, workflow_id, BidWorkflowStatus.EXTRACTING)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="标书工作流或模型配置不存在。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        workbench_store.add_message(user_id, workflow.conversation_id, "assistant", "正在执行阶段一信息提取。")
        workflow = enqueue_bid_job(user_id, workflow_id, "extraction")
        return BidWorkflowActionResponse(workflow=public_bid_workflow(workflow), message="阶段一信息提取已开始。")

    @router.post("/api/v1/bid-workflows/{workflow_id}/confirm", response_model=BidWorkflowActionResponse)
    def confirm_bid_workflow(workflow_id: str, request: Request, payload: BidWorkflowConfirmRequest):
        user_id = current_user(request).id
        try:
            workflow = workbench_store.get_bid_workflow(user_id, workflow_id)
            if not workflow.extracted_markdown:
                raise ValueError("请先完成阶段一信息提取。")
            if workflow.status in {BidWorkflowStatus.EXTRACTING, BidWorkflowStatus.GENERATING}:
                raise ValueError("当前工作流正在执行中。")
            workflow = workbench_store.save_bid_confirmation(user_id, workflow_id, payload.text)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="标书工作流不存在。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        workbench_store.add_message(user_id, workflow.conversation_id, "user", payload.text)
        try:
            save_behavior_report(user_id, workflow_id)
        except Exception as report_exc:
            print(f"[behavior-report] failed to save report on confirm for {workflow_id}: {report_exc}")
        return BidWorkflowActionResponse(workflow=public_bid_workflow(workflow), message="阶段一信息已确认。")

    @router.post("/api/v1/bid-workflows/{workflow_id}/generate", response_model=BidWorkflowActionResponse)
    def generate_bid_workflow(workflow_id: str, request: Request, payload: BidWorkflowGenerateRequest):
        user_id = current_user(request).id
        try:
            workflow = workbench_store.get_bid_workflow(user_id, workflow_id)
            api_config_from_profile(user_id, workflow.provider_profile_id or "")
            if not workflow.extracted_markdown:
                raise ValueError("请先完成阶段一信息提取。")
            if not workflow.confirmation_text:
                raise ValueError("请先确认阶段一信息。")
            if workflow.status in {BidWorkflowStatus.EXTRACTING, BidWorkflowStatus.GENERATING}:
                raise ValueError("当前工作流正在执行中。")
            confirmation_text = workflow.confirmation_text
            if payload.extra_context:
                confirmation_text = f"{confirmation_text}\n\n补充信息：{payload.extra_context}"
            workbench_store.save_bid_confirmation(user_id, workflow_id, confirmation_text)
            workbench_store.save_bid_template_choice(user_id, workflow_id, "auto")
            if payload.extra_context:
                try:
                    save_behavior_report(user_id, workflow_id)
                except Exception as report_exc:
                    print(f"[behavior-report] failed to save report on generate for {workflow_id}: {report_exc}")
            workflow = workbench_store.update_bid_workflow_status(user_id, workflow_id, BidWorkflowStatus.GENERATING)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="标书工作流或模型配置不存在。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        workbench_store.add_message(user_id, workflow.conversation_id, "assistant", "正在按当前招标约束动态生成阶段二设计方案。")
        workflow = enqueue_bid_job(user_id, workflow_id, "generation")
        return BidWorkflowActionResponse(workflow=public_bid_workflow(workflow), message="阶段二设计方案生成已开始。")

    @router.post("/api/v1/bid-workflows/{workflow_id}/cancel", response_model=BidWorkflowActionResponse)
    def cancel_bid_workflow(workflow_id: str, request: Request):
        user_id = current_user(request).id
        try:
            workflow = workbench_store.get_bid_workflow(user_id, workflow_id)
            if workflow.status == BidWorkflowStatus.COMPLETED:
                raise ValueError("当前工作流已完成，不能取消。")
            if workflow.status == BidWorkflowStatus.CANCELLED:
                return BidWorkflowActionResponse(workflow=public_bid_workflow(workflow), message="标书工作流已取消。")
            workflow = workbench_store.update_bid_workflow_status(user_id, workflow_id, BidWorkflowStatus.CANCELLED)
            workbench_store.cancel_bid_jobs(workflow_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="标书工作流不存在。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        workbench_store.add_message(user_id, workflow.conversation_id, "assistant", "当前标书流程已取消。")
        return BidWorkflowActionResponse(workflow=public_bid_workflow(workflow), message="标书工作流已取消。")

    return router
