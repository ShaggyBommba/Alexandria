from __future__ import annotations
from enum import Enum


class JobKind(str, Enum):
    EMAIL_SEND = "email.send"
    SEND_EMAIL = EMAIL_SEND
    WEBHOOK_SEND = "webhook.send"
    SPLIT_CHECK = "split.check"
    PROCESS_PAYMENT = "process_payment"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
