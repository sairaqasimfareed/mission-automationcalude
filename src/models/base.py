from uuid import UUID, uuid4
from datetime import datetime, UTC

from pydantic import BaseModel, Field


class MissionBaseModel(BaseModel):
    """
    Base model inherited by all Mission Automation models.
    """

    id: UUID = Field(default_factory=uuid4)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))