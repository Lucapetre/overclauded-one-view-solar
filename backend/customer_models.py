from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from backend.models import Model

AccountType = Literal["home", "business"]


class Contract(Model):
    supplier: Annotated[str, Field(min_length=1, max_length=80)]
    pricing: Literal["fixed"] = "fixed"
    import_price_ron_kwh: Annotated[float, Field(gt=0, le=10)]
    export_price_ron_kwh: Annotated[float, Field(ge=0, le=10)]
    installed_kwp: Annotated[float, Field(gt=0, le=1000)] | None = None


class ContractView(Model):
    site_id: str
    contract: Contract | None
    updated_at: datetime | None


class RequestType(Model):
    id: str
    label: str
    routed_to: str


class SupportRequestCreate(Model):
    site_id: Annotated[str, Field(min_length=1, max_length=96)]
    request_type: Annotated[str, Field(min_length=1, max_length=64)]
    description: Annotated[str, Field(min_length=1, max_length=2000)]
    immediate_danger: bool = False


class SupportReplyCreate(Model):
    text: Annotated[str, Field(min_length=1, max_length=1000)]


class SupportReply(Model):
    author: str
    kind: Literal["customer", "staff"]
    text: str
    created_at: datetime


class SupportMeeting(Model):
    start: datetime
    end: datetime
    crew_name: str


class SupportMedia(Model):
    media_id: str
    filename: str
    content_type: Literal["video/mp4", "video/webm"]
    size_bytes: int


class SupportRequest(Model):
    request_id: str
    site_id: str
    site_alias: str
    requested_by: str
    request_type: str
    request_label: str
    priority: Literal["standard", "immediate_danger"]
    routed_to: str
    description: str
    status: Literal["awaiting_review", "answered"]
    created_at: datetime
    updated_at: datetime
    replies: list[SupportReply]
    incident_id: str | None
    meeting: SupportMeeting | None
    media: SupportMedia | None


class LessonStep(Model):
    title: str
    text: str


class LessonQuestion(Model):
    text: str
    options: list[str]


class Lesson(Model):
    id: str
    title: str
    summary: str
    minutes: int
    reward_ron: float
    steps: list[LessonStep]
    example: str
    questions: list[LessonQuestion]
    completed: bool


class LessonCatalog(Model):
    lessons: list[Lesson]
    total_reward_ron: float
    reward_note: str


class LessonAnswers(Model):
    answers: Annotated[list[Annotated[int, Field(ge=0, le=9)]], Field(max_length=10)]


class LessonResult(Model):
    lesson_id: str
    passed: bool
    correct: int
    total: int
    reward_ron: float
    already_completed: bool
    total_reward_ron: float
