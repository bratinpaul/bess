from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Numeric, Text

from app.database import Base


class SocReference(Base):
    """Independent ground-truth SOC of a plant battery system at a moment (rest-OCV / full-charge / lab anchors) - the
    label the SOC estimators are scored against (battery_master; joined to system_telemetry by v_soc_features)."""

    __tablename__ = "soc_reference"
    __table_args__ = {"schema": "battery_master"}

    system_id = Column(BigInteger, ForeignKey("battery_system.battery_system_id", ondelete="CASCADE"),
                       primary_key=True)
    ts = Column(DateTime(timezone=True), primary_key=True)
    soc_true_pct = Column(Numeric, nullable=False)
    method = Column(Text)
    note = Column(Text)
