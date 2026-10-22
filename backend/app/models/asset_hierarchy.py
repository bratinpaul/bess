from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, func, String, text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class AssetHierarchy(Base):
    """One node per tenant / site / battery_system, identified by a generated UUID.

    (asset_type, source_id) is the record the node stands for: asset_type is the table name and
    source_id that record's id. tenant <- site (primary owner) <- battery_system.
    Kept in sync by app/hierarchy.py.
    """

    __tablename__ = "asset_hierarchy"
    __table_args__ = (UniqueConstraint("asset_type", "source_id", name="asset_hierarchy_source_key"),)

    asset_id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    asset_type = Column(String(50), nullable=False)
    source_id = Column(BigInteger, nullable=False)
    asset_name = Column(String(200))
    external_id = Column(String(100))
    parent_asset_id = Column(UUID(as_uuid=True), ForeignKey("asset_hierarchy.asset_id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
