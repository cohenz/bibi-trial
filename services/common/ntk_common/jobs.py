"""Job queue abstraction so the API never runs the pipeline in-request.

* ``CeleryQueue`` (production): sends ``ntk.run_ingestion_job`` to Redis by
  task name, so the API does not import worker code.
* ``InlineQueue`` (tests / single-process dev): runs the job synchronously.
"""

from __future__ import annotations

from typing import Protocol

TASK_RUN_JOB = "ntk.run_ingestion_job"
TASK_BUILD_CLAIM = "ntk.build_claim"
TASK_VERIFY_ARTIFACT = "ntk.verify_artifact"
TASK_DELIVER_WEBHOOKS = "ntk.deliver_webhooks"
TASK_RUN_EVALUATION = "ntk.run_evaluation"
TASK_SCAN_INBOX = "ntk.scan_inbox"
TASK_CLASSIFY_INBOX = "ntk.classify_inbox_batch"
TASK_BUILD_GUIDES = "ntk.build_guides"
TASK_BUILD_BRIEFS = "ntk.build_briefs"
TASK_BUILD_DIGESTS = "ntk.build_digests"


class JobQueue(Protocol):
    def enqueue(self, task: str, *args: str) -> str: ...


class CeleryQueue:
    def __init__(self, broker_url: str):
        from celery import Celery

        self.app = Celery("ntk-api-client", broker=broker_url)
        self.app.conf.task_default_queue = "ntk"

    def enqueue(self, task: str, *args: str) -> str:
        res = self.app.send_task(task, args=list(args), queue="ntk")
        return res.id


class InlineQueue:
    def __init__(self, handlers: dict):
        self.handlers = handlers
        self.calls: list[tuple[str, tuple]] = []

    def enqueue(self, task: str, *args: str) -> str:
        self.calls.append((task, args))
        fn = self.handlers.get(task)
        if fn is not None:
            fn(*args)
        return f"inline-{len(self.calls)}"
