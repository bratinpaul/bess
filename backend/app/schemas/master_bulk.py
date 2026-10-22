from typing import Any, Optional

from pydantic import BaseModel


class MasterBulkEntity(BaseModel):
    key: str
    label: str
    parent: Optional[str] = None
    columns: list[dict[str, Any]]


class BulkMasterRowError(BaseModel):
    row: int
    errors: list[str]


class BulkMasterResult(BaseModel):
    entity: str
    filename: str
    total_rows: int
    valid_rows: int
    inserted: int
    updated: int
    error_count: int
    errors: list[BulkMasterRowError]
