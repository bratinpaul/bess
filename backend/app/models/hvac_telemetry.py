from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Identity, Numeric, SmallInteger, Text

from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class HvacUnit(Base):
    __tablename__ = "hvac_unit"

    hvac_id = Column(BigInteger, Identity(), primary_key=True)
    hvac_code = Column(Text, nullable=False, unique=True)
    battery_system_id = Column(BigInteger, ForeignKey("battery_system.battery_system_id"))
    manufacturer = Column(Text)
    model = Column(Text)
    hvac_type = Column(Text)
    cooling_capacity_kw = Column(Numeric(8, 2))
    status = Column(Text)
    # the record's UUID in the source system (static data loader); upsert key of the bulk loaders
    source_uuid = Column(UUID(as_uuid=True), unique=True)


class HvacCoolingMode(Base):
    __tablename__ = "hvac_cooling_mode"

    mode_code = Column(Text, primary_key=True)
    description = Column(Text)


class HvacTelemetry(Base):
    __tablename__ = "hvac_telemetry"

    hvac_id = Column(BigInteger, ForeignKey("hvac_unit.hvac_id"), primary_key=True)
    ts = Column(DateTime(timezone=True), primary_key=True)
    cooling_mode = Column(Text, ForeignKey("hvac_cooling_mode.mode_code"))
    ambient_temp_c = Column(Numeric(6, 2))
    coolant_setpoint_c = Column(Numeric(5, 2))
    coolant_supply_temp_c = Column(Numeric(6, 2))
    coolant_return_temp_c = Column(Numeric(6, 2))
    coolant_delta_t_c = Column(Numeric(6, 2))
    coolant_flow_lpm = Column(Numeric(8, 2))
    compressor_speed_pct = Column(Numeric(5, 2))
    condenser_fan_pct = Column(Numeric(5, 2))
    refrig_suction_bar = Column(Numeric(7, 2))
    refrig_discharge_bar = Column(Numeric(7, 2))
    battery_heat_load_kw = Column(Numeric(9, 2))
    cooling_capacity_kw = Column(Numeric(9, 2))
    heat_rejected_kw = Column(Numeric(9, 2))
    hvac_power_kw = Column(Numeric(9, 2))
    cop = Column(Numeric(5, 2))
    enclosure_temp_c = Column(Numeric(6, 2))
    enclosure_humidity_pct = Column(Numeric(5, 2))
    filter_dp_pa = Column(Numeric(8, 1))
    cum_energy_kwh = Column(Numeric(13, 2))
    compressor_runtime_h = Column(Numeric(10, 2))
    units_running = Column(SmallInteger)
    alarm_level = Column(SmallInteger)
    alarm_flags = Column(Text)
