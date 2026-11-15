from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from backend.models import Model

AccountType = Literal["home", "business"]
ExportCompensation = Literal["payment", "credit", "unspecified"]


class TariffBand(Model):
    """One contract time band in local Europe/Bucharest time.

    `days` are ISO weekdays (1 = Monday) on which an occurrence starts; `end_minute` <=
    `start_minute` means the band crosses local midnight. `valid_to` is exclusive.
    """

    band_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")]
    label: Annotated[str, Field(min_length=1, max_length=60)] | None = None
    days: Annotated[
        list[Annotated[int, Field(ge=1, le=7)]], Field(min_length=1, max_length=7)
    ]
    start_minute: Annotated[int, Field(ge=0, le=1439)]
    end_minute: Annotated[int, Field(ge=1, le=1440)]
    import_rate_ron_kwh: Annotated[float, Field(gt=0, le=10)]
    export_value_ron_kwh: Annotated[float, Field(ge=0, le=10)]
    valid_from: date | None = None
    valid_to: date | None = None


class Contract(Model):
    supplier: Annotated[str, Field(min_length=1, max_length=80)]
    pricing: Literal["fixed", "time_of_use"] = "fixed"
    # Reference rates. Power Block Offers keep using these (unchanged offer rule); a fixed
    # contract is one all-day band with exactly these rates.
    import_price_ron_kwh: Annotated[float, Field(gt=0, le=10)]
    export_price_ron_kwh: Annotated[float, Field(ge=0, le=10)]
    installed_kwp: Annotated[float, Field(gt=0, le=1000)] | None = None
    # How the contract compensates export (recorded as stated; no rule is invented).
    export_compensation: ExportCompensation = "unspecified"
    # Required for time_of_use, absent for fixed.
    bands: Annotated[list[TariffBand], Field(min_length=1, max_length=48)] | None = None
    # A new version may start later than now, never earlier (no retroactive tariff change).
    effective_from: datetime | None = None

    @model_validator(mode="after")
    def check_pricing(self):
        if self.pricing == "time_of_use" and not self.bands:
            raise ValueError("A time_of_use contract needs at least one band")
        if self.pricing == "fixed" and self.bands:
            raise ValueError("A fixed contract has no bands; use time_of_use")
        return self


class ContractVersionView(Model):
    version_id: str
    version_no: int
    pricing: Literal["fixed", "time_of_use"]
    timezone: Literal["Europe/Bucharest"]
    export_compensation: ExportCompensation
    effective_from: datetime
    valid_to: datetime | None
    # Effective bands: a fixed contract shows its single all-day band.
    bands: list[TariffBand]
    # Local weekly minutes not covered by any band (an explicit pricing gap, never zero).
    uncovered_week_minutes: int


class ContractView(Model):
    site_id: str
    contract: Contract | None
    updated_at: datetime | None
    # The version in force at the analytical time of the request, and how many exist.
    version: ContractVersionView | None = None
    version_count: int = 0


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
