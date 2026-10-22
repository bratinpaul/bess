from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Numeric, SmallInteger, Text

from app.database import Base


class Market(Base):
    """Market / exchange a node settles in (battery_master); read-only here."""

    __tablename__ = "market"
    __table_args__ = {"schema": "battery_master"}

    market_id = Column(BigInteger, primary_key=True)
    market_code = Column(Text, nullable=False, unique=True)
    name = Column(Text, nullable=False)
    currency = Column(Text, nullable=False)
    timezone = Column(Text, nullable=False)
    dam_settlement_min = Column(SmallInteger, nullable=False)


class PriceNode(Base):
    """Settlement node / bidding zone the plant is priced at (battery_master); read-only here."""

    __tablename__ = "price_node"
    __table_args__ = {"schema": "battery_master"}

    node_id = Column(BigInteger, primary_key=True)
    market_id = Column(BigInteger, ForeignKey("battery_master.market.market_id"), nullable=False)
    node_code = Column(Text, nullable=False, unique=True)
    name = Column(Text)
    node_type = Column(Text)
    site_id = Column(BigInteger, ForeignKey("battery_master.site.site_id"))


class DamPrice(Base):
    """Day-ahead market cleared energy price per node and delivery block (battery_master hypertable)."""

    __tablename__ = "dam_price"
    __table_args__ = {"schema": "battery_master"}

    node_id = Column(BigInteger, ForeignKey("battery_master.price_node.node_id", ondelete="CASCADE"), primary_key=True)
    delivery_start = Column(DateTime(timezone=True), primary_key=True)
    block_minutes = Column(SmallInteger, nullable=False, default=60)
    price_mwh = Column(Numeric(10, 2), nullable=False)
    cleared_mw = Column(Numeric(10, 2))


class RtPrice(Base):
    """Real-time / imbalance settlement price per node and interval (battery_master hypertable)."""

    __tablename__ = "rt_price"
    __table_args__ = {"schema": "battery_master"}

    node_id = Column(BigInteger, ForeignKey("battery_master.price_node.node_id", ondelete="CASCADE"), primary_key=True)
    interval_start = Column(DateTime(timezone=True), primary_key=True)
    block_minutes = Column(SmallInteger, nullable=False, default=15)
    price_mwh = Column(Numeric(10, 2), nullable=False)


class PriceForecast(Base):
    """Probabilistic price forecast (P10 / P50 / P90) per node, issue vintage and target hour (hypertable)."""

    __tablename__ = "price_forecast"
    __table_args__ = {"schema": "battery_master"}

    node_id = Column(BigInteger, ForeignKey("battery_master.price_node.node_id", ondelete="CASCADE"), primary_key=True)
    issued_at = Column(DateTime(timezone=True), primary_key=True)
    target_ts = Column(DateTime(timezone=True), primary_key=True)
    horizon_h = Column(Numeric(6, 2))
    p10_mwh = Column(Numeric(10, 2))
    p50_mwh = Column(Numeric(10, 2), nullable=False)
    p90_mwh = Column(Numeric(10, 2))
    model = Column(Text)
