from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Numeric, SmallInteger, Text

from app.database import Base


class AsProduct(Base):
    """Ancillary-service product the asset can bid (battery_master); read-only here."""

    __tablename__ = "as_product"
    __table_args__ = {"schema": "battery_master"}

    product_id = Column(BigInteger, primary_key=True)
    market_id = Column(BigInteger, ForeignKey("battery_master.market.market_id"), nullable=False)
    product_code = Column(Text, nullable=False, unique=True)
    name = Column(Text, nullable=False)
    direction = Column(Text)
    min_bid_mw = Column(Numeric(8, 3))
    sustain_minutes = Column(SmallInteger)
    response_seconds = Column(SmallInteger)
    settlement = Column(Text)
    description = Column(Text)


class AsPrice(Base):
    """Ancillary-service capacity / performance clearing price per product and delivery block (hypertable)."""

    __tablename__ = "as_price"
    __table_args__ = {"schema": "battery_master"}

    product_id = Column(BigInteger, ForeignKey("battery_master.as_product.product_id", ondelete="CASCADE"),
                        primary_key=True)
    delivery_start = Column(DateTime(timezone=True), primary_key=True)
    block_minutes = Column(SmallInteger, nullable=False, default=60)
    capacity_price_mw = Column(Numeric(10, 2))
    performance_price = Column(Numeric(10, 2))
