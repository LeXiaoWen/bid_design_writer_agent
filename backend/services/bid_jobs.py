from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from ..schemas import BidExecutionState
from .workbench_store import workbench_store


logger = logging.getLogger("bid_design_writer.jobs")
JobRunner = Callable[[str, str, str, str], None]


class BidJobWorker:
    def __init__(self, runner: JobRunner) -> None:
        self._runner = runner
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        workbench_store.recover_bid_jobs()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="bid-job-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    def notify(self) -> None:
        self._wake.set()

    def run_pending(self) -> None:
        """Run one job synchronously; used by deterministic API tests only."""
        job = workbench_store.claim_next_bid_job()
        if job:
            self._execute(job)

    def _run(self) -> None:
        while not self._stop.is_set():
            job = workbench_store.claim_next_bid_job()
            if job:
                self._execute(job)
                continue
            self._wake.wait(timeout=1)
            self._wake.clear()

    def _execute(self, job: dict[str, str]) -> None:
        try:
            workbench_store.update_bid_job(job["id"], progress=10, message="正在调用模型。")
            self._runner(job["id"], job["owner_user_id"], job["workflow_id"], job["kind"])
            workflow = workbench_store.get_bid_workflow(job["owner_user_id"], job["workflow_id"])
            state = (
                BidExecutionState.CANCELLED
                if workflow.status.value == "cancelled"
                else BidExecutionState.FAILED
                if workflow.status.value == "failed"
                else BidExecutionState.COMPLETED
            )
            message = "任务已取消。" if state is BidExecutionState.CANCELLED else "任务失败。" if state is BidExecutionState.FAILED else "任务已完成。"
            workbench_store.update_bid_job(job["id"], state=state, progress=100, message=message)
        except Exception as exc:
            logger.exception("bid job failed", extra={"workflow_id": job["workflow_id"], "kind": job["kind"]})
            workbench_store.update_bid_job(job["id"], state=BidExecutionState.FAILED, progress=100, message=str(exc))
