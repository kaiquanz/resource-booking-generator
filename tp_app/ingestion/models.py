"""Structured models and constants shared by training-plan ingestion."""

from pydantic import BaseModel, Field


MAX_AI_FILE_BYTES = 50 * 1024 * 1024
MAX_AI_OUTPUT_TOKENS = 64_000
PDF_PAGES_PER_REQUEST = 2
DEFAULT_AI_MODEL = "gpt-5.6-luna"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
SUPPORTED_SUFFIXES = IMAGE_SUFFIXES | {
    ".pdf",
    ".csv",
    ".tsv",
    ".xlsx",
    ".xls",
    ".xlsm",
}
EVENT_COLUMNS = [
    "date",
    "start_time",
    "end_time",
    "conduct",
    "location",
    "remarks",
    "source_reference",
    "confidence",
    "needs_review",
]


class TrainingPlanEvent(BaseModel):
    """One canonical scheduled event returned by the AI reader."""

    date: str = Field(description="Calendar date in YYYY-MM-DD format")
    start_time: str = Field(description="Start time in 24-hour HH:MM format")
    end_time: str = Field(description="End time in 24-hour HH:MM format")
    conduct: str = Field(description="Training activity exactly as shown")
    location: str = Field(description="Location exactly as shown, or an empty string")
    remarks: str = Field(description="Relevant notes, or an empty string")
    source_reference: str = Field(description="Page, sheet, or visible box reference")
    confidence: float = Field(ge=0, le=1)
    needs_review: bool


class TrainingPlanExtraction(BaseModel):
    """Structured response for a complete file or one PDF chunk."""

    document_title: str
    events: list[TrainingPlanEvent]
    warnings: list[str]


EXTRACTION_PROMPT = """
Extract this training plan into individual scheduled events.

The source may be a spreadsheet, a normal PDF, a scanned PDF, or a visual
timetable made from text boxes, merged cells, colours, arrows, or pictures.
Read both text and spatial layout. Treat dates across columns, time periods down
rows, merged boxes, legends, and continuation markers as layout evidence.

Rules:
- Return one event for every distinct date, time range, conduct, and location.
- Expand boxes spanning multiple dates into one event per date when the layout
  clearly indicates that the event occurs on each date.
- Use YYYY-MM-DD dates and 24-hour HH:MM times.
- Preserve conduct and location wording; do not rename them to likely synonyms.
- Do not invent missing dates, times, activities, or locations.
- Use an empty string for a missing location or remark.
- Set needs_review=true whenever a date, time, merged-box boundary, conduct, or
  location is uncertain, and explain material uncertainty in warnings.
- Confidence is about the accuracy of the extracted row, not the importance of
  the activity.
- Ignore decorative elements and administrative headers that are not scheduled
  events.
- If the document is not a training plan, return no events and add a warning.
- Completeness is mandatory: inspect every supplied page through its final row
  and do not stop after finding a plausible partial schedule.
""".strip()

