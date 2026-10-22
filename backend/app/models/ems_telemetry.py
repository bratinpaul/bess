from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Identity, Numeric, SmallInteger, Text

from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class EmsController(Base):
    __tablename__ = "ems_controller"

    ems_id = Column(BigInteger, Identity(), primary_key=True)
    ems_code = Column(Text, nullable=False, unique=True)
    battery_system_id = Column(BigInteger, ForeignKey("battery_system.battery_system_id"))
    manufacturer = Column(Text)
    model = Column(Text)
    firmware_version = Column(Text)
    control_mode = Column(Text)
    # the record's UUID in the source system (static data loader); upsert key of the bulk loaders
    source_uuid = Column(UUID(as_uuid=True), unique=True)


class EmsDispatchMode(Base):
    __tablename__ = "ems_dispatch_mode"

    mode_code = Column(Text, primary_key=True)
    description = Column(Text)


class EmsGridService(Base):
    __tablename__ = "ems_grid_service"

    service_code = Column(Text, primary_key=True)
    description = Column(Text)


class EmsTelemetry(Base):
    __tablename__ = "ems_telemetry"

    ems_id = Column(BigInteger, ForeignKey("ems_controller.ems_id"), primary_key=True)
    ts = Column(DateTime(timezone=True), primary_key=True)
    dispatch_mode = Column(Text, ForeignKey("ems_dispatch_mode.mode_code"))
    grid_service = Column(Text, ForeignKey("ems_grid_service.service_code"))
    market_price_mwh = Column(Numeric(10, 2))
    p_setpoint_kw = Column(Numeric(10, 2))
    poi_active_power_kw = Column(Numeric(10, 2))
    poi_reactive_power_kvar = Column(Numeric(10, 2))
    tracking_error_kw = Column(Numeric(10, 2))
    grid_frequency_hz = Column(Numeric(6, 3))
    poi_voltage_kv = Column(Numeric(8, 3))
    agc_signal = Column(Numeric(6, 3))
    plant_soc_pct = Column(Numeric(5, 2))
    target_soc_pct = Column(Numeric(5, 2))
    avail_charge_kw = Column(Numeric(10, 2))
    avail_discharge_kw = Column(Numeric(10, 2))
    avail_charge_energy_kwh = Column(Numeric(12, 2))
    avail_discharge_energy_kwh = Column(Numeric(12, 2))
    aux_load_kw = Column(Numeric(9, 2))
    aux_load_pct = Column(Numeric(6, 2))
    cum_import_kwh = Column(Numeric(14, 2))
    cum_export_kwh = Column(Numeric(14, 2))
    revenue_cum_usd = Column(Numeric(14, 2))
    units_online = Column(SmallInteger)
    plant_available = Column(SmallInteger)
    alarm_level = Column(SmallInteger)
