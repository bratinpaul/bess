from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Numeric, SmallInteger, Text

from app.database import Base


class OperatingMode(Base):
    __tablename__ = "operating_mode"

    mode_code = Column(Text, primary_key=True)
    description = Column(Text)


class ContactorState(Base):
    __tablename__ = "contactor_state"

    state_code = Column(Text, primary_key=True)
    description = Column(Text)


class SystemTelemetry(Base):
    __tablename__ = "system_telemetry"

    system_id = Column(BigInteger, ForeignKey("battery_system.battery_system_id"), primary_key=True)
    ts = Column(DateTime(timezone=True), primary_key=True)
    mode_code = Column(Text, ForeignKey("operating_mode.mode_code"))
    soc_bms_pct = Column(Numeric(5, 2))  # SOC reported by the BMS (was soc_pct)
    soh_pct = Column(Numeric(5, 2))
    pack_voltage_v = Column(Numeric(8, 2))
    pack_current_a = Column(Numeric(9, 2))
    power_kw = Column(Numeric(9, 2))
    c_rate = Column(Numeric(6, 3))
    cell_v_avg_v = Column(Numeric(6, 4))
    cell_v_min_v = Column(Numeric(6, 4))
    cell_v_max_v = Column(Numeric(6, 4))
    cell_v_delta_mv = Column(Numeric(7, 2))
    cell_temp_avg_c = Column(Numeric(6, 2))
    cell_temp_min_c = Column(Numeric(6, 2))
    cell_temp_max_c = Column(Numeric(6, 2))
    coolant_temp_c = Column(Numeric(6, 2))
    ambient_temp_c = Column(Numeric(6, 2))
    insulation_res_kohm = Column(Numeric(9, 1))
    avail_charge_kw = Column(Numeric(9, 2))
    avail_discharge_kw = Column(Numeric(9, 2))
    cum_charge_kwh = Column(Numeric(12, 2))
    cum_discharge_kwh = Column(Numeric(12, 2))
    equiv_full_cycles = Column(Numeric(10, 3))
    contactor_state = Column(Text, ForeignKey("contactor_state.state_code"))
    alarm_level = Column(SmallInteger)
    # current sensing and SOC estimation (added to the table 2026-10)
    measured_current_a = Column(Numeric)
    current_sensor_offset_a = Column(Numeric)
    soc_coulomb_pct = Column(Numeric)
    soc_battery_telemetry_pct = Column(Numeric)
    usable_capacity_ah = Column(Numeric)
    coulombic_efficiency = Column(Numeric)
    at_rest = Column(Boolean)
    rest_duration_min = Column(Numeric)
    ocv_rested_v = Column(Numeric)
