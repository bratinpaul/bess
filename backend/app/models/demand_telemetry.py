from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Numeric, SmallInteger, Text

from app.database import Base


class MeteringPoint(Base):
    """A metering point of a site (battery_master.metering_point), e.g. the feeder serving the site load."""

    __tablename__ = "metering_point"
    __table_args__ = {"schema": "battery_master"}

    metering_point_id = Column(BigInteger, primary_key=True)
    site_id = Column(BigInteger, ForeignKey("site.site_id"), nullable=False)
    mp_code = Column(Text, nullable=False)
    mp_type = Column(Text, nullable=False)
    voltage_kv = Column(Numeric)
    description = Column(Text)


class DemandTariff(Base):
    """A site's demand charge: price per kW of the billed peak, the peak window (hours), ratchet."""

    __tablename__ = "demand_tariff"
    __table_args__ = {"schema": "battery_master"}

    tariff_id = Column(BigInteger, primary_key=True)
    site_id = Column(BigInteger, nullable=False)
    name = Column(Text, nullable=False)
    demand_charge_per_kw = Column(Numeric)
    peak_window_start = Column(Numeric)
    peak_window_end = Column(Numeric)
    measurement_minutes = Column(SmallInteger)
    ratchet_pct = Column(Numeric)
    valid_from = Column(Date)


class DemandTelemetry(Base):
    """Site load at a metering point (5-min): gross load, behind-the-meter generation, net load, reactive power."""

    __tablename__ = "demand_telemetry"
    __table_args__ = {"schema": "battery_telemetry"}

    metering_point_id = Column(BigInteger, ForeignKey("battery_master.metering_point.metering_point_id"), primary_key=True)
    ts = Column(DateTime(timezone=True), primary_key=True)
    gross_load_kw = Column(Numeric)
    behind_meter_gen_kw = Column(Numeric)
    net_load_kw = Column(Numeric)
    load_reactive_kvar = Column(Numeric)
