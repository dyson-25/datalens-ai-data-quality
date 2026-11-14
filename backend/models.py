from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class IngestRequest(StrictModel):
    sheet: str | None = Field(default=None, max_length=100)
    header: int | None = Field(default=0, ge=0, le=100)
    delimiter: str | None = Field(default=None, min_length=1, max_length=1)
    encoding: Literal['utf-8', 'utf-8-sig', 'utf-16', 'cp1252', 'latin-1'] | None = None


class Operation(StrictModel):
    kind: Literal['trim', 'normalize_missing', 'drop_duplicates', 'to_numeric', 'to_date', 'fill_missing', 'drop_column', 'case', 'map_categories', 'handle_infinity', 'outliers']
    column: str | None = Field(default=None, max_length=1000)
    params: dict[str, Any] = Field(default_factory=dict)


class VersionRequest(StrictModel):
    expected_version: int = Field(ge=0)
    expected_revision: int = Field(ge=0)


class PreviewRequest(VersionRequest):
    operation: Operation


class ApplyRequest(VersionRequest):
    preview_id: str = Field(min_length=36, max_length=36)
    approved: Literal[True]

    @field_validator('approved', mode='before')
    @classmethod
    def explicit_approval(cls, value):
        if value is not True:
            raise ValueError('Approval must be the JSON boolean true.')
        return value


class RestoreRequest(VersionRequest):
    version: int = Field(ge=0)


class AnomalyRequest(StrictModel):
    method: Literal['iqr', 'mad', 'isolation_forest'] = 'iqr'
    columns: list[str] = Field(min_length=1, max_length=20)
    threshold: float | None = Field(default=None, gt=0, le=20, allow_inf_nan=False)


class DomainRule(StrictModel):
    min: float | None = Field(default=None, allow_inf_nan=False)
    max: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode='after')
    def check_bounds(self):
        if self.min is None and self.max is None:
            raise ValueError('Specify a minimum or maximum.')
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError('Minimum cannot exceed maximum.')
        return self


class DomainQualityRequest(StrictModel):
    domain_rules: dict[str, DomainRule] = Field(min_length=1, max_length=100)


class EmptyRequest(StrictModel):
    pass


class DatasetResponse(StrictModel):
    dataset_id: str
    filename: str
    active_version: int | None
    revision: int
    created_at: float
    expires_at: float


class UploadResponse(DatasetResponse):
    token: str
    inspection: dict[str, Any]


class JobCreated(StrictModel):
    job_id: str


class ProfileResponse(BaseModel):
    model_config = ConfigDict(extra='allow')
    rows: int
    columns: int
    total_cells: int
    missing_cells: int
    missing_percentage: float
    duplicate_rows: int
    memory_bytes: int
    column_profiles: list[dict[str, Any]]


class JobResponse(StrictModel):
    job_id: str
    status: Literal['queued', 'running', 'succeeded', 'failed', 'timed_out']
    error: str | None = None
    result: dict[str, Any] | None = None
