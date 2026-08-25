from pydantic import BaseModel, Field


class UserUpdateRequest(BaseModel):
    nickname: str | None = Field(default=None, min_length=1, max_length=50)
    target_band: float | None = Field(default=None, ge=4.0, le=9.0)
