from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Numeric, SmallInteger, Text

from app.database import Base


class PcsMode(Base):
    __tablename__ = "pcs_mode"

    mode_code = Column(Text, primary_key=True)
    description = Column(Text)


class PcsGridService(Base):
    __tablename__ = "pcs_grid_service"

    service_code = Column(Text, primary_key=True)
    description = Column(Text)


class PcsBreakerState(Base):
    __tablename__ = "pcs_breaker_state"

    state_code = Column(Text, primary_key=True)
    description = Column(Text)


class PcsTelemetry(Base):
    __tablename__ = "pcs_telemetry"

    pcs_id = Column(BigInteger, ForeignKey("pcs.pcs_id"), primary_key=True)
    ts = Column(DateTime(timezone=True), primary_key=True)
    mode_code = Column(Text, ForeignKey("pcs_mode.mode_code"))
    grid_service = Column(Text, ForeignKey("pcs_grid_service.service_code"))
    ac_active_power_kw = Column(Numeric(9, 2))
    ac_reactive_power_kvar = Column(Numeric(9, 2))
    ac_apparent_power_kva = Column(Numeric(9, 2))
    power_factor = Column(Numeric(5, 3))
    ac_frequency_hz = Column(Numeric(6, 3))
    ac_voltage_ab_v = Column(Numeric(8, 2))
    ac_voltage_bc_v = Column(Numeric(8, 2))
    ac_voltage_ca_v = Column(Numeric(8, 2))
    ac_current_a_a = Column(Numeric(9, 2))
    ac_current_b_a = Column(Numeric(9, 2))
    ac_current_c_a = Column(Numeric(9, 2))
    thd_voltage_pct = Column(Numeric(5, 2))
    thd_current_pct = Column(Numeric(5, 2))
    dc_voltage_v = Column(Numeric(8, 2))
    dc_current_a = Column(Numeric(9, 2))
    dc_power_kw = Column(Numeric(9, 2))
    efficiency_pct = Column(Numeric(5, 2))
    igbt_temp_c = Column(Numeric(6, 2))
    heatsink_temp_c = Column(Numeric(6, 2))
    inlet_coolant_temp_c = Column(Numeric(6, 2))
    ambient_temp_c = Column(Numeric(6, 2))
    avail_charge_kw = Column(Numeric(9, 2))
    avail_discharge_kw = Column(Numeric(9, 2))
    ac_energy_import_kwh = Column(Numeric(13, 2))
    ac_energy_export_kwh = Column(Numeric(13, 2))
    breaker_state = Column(Text, ForeignKey("pcs_breaker_state.state_code"))
    alarm_level = Column(SmallInteger)
