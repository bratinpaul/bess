from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

AssetType = Literal[
    "tenant", "site", "battery_system", "battery_container", "battery_pack", "battery_module",
    "pcs", "ems_controller", "hvac_unit",
]


class AssetNodeCreate(BaseModel):
    """Add the node for an existing record; name and parent are read from the record itself."""

    asset_type: AssetType
    source_id: int


class AssetNodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset_id: UUID
    asset_type: str
    source_id: int
    asset_name: Optional[str] = None
    external_id: Optional[str] = None
    parent_asset_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    # read from the parent node
    parent_asset_type: Optional[str] = None
    parent_source_id: Optional[int] = None
    parent_name: Optional[str] = None
    child_count: int = 0


class AssetNodeDetail(AssetNodeOut):
    ancestors: list[AssetNodeOut] = []  # root first
    children: list[AssetNodeOut] = []


class AssetTreeNode(BaseModel):
    asset_id: UUID
    asset_type: str
    source_id: int
    asset_name: Optional[str] = None
    external_id: Optional[str] = None
    children: list["AssetTreeNode"] = []


class AssetSyncResult(BaseModel):
    created: int
    updated: int
