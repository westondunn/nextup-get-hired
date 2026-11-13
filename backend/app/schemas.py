from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DiagnosticOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source: Literal["manual", "scheduler"]
    status: Literal["queued", "succeeded", "publish_failed", "failed"]
    created_at: datetime
    completed_at: datetime | None
    worker: str | None
    result: dict | None
    error_message: str | None = None
