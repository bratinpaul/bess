"""Arbitrage decision layer from BESS_Arbitrage_DataPack (battery_master): optimizer runs, the state each run saw,
the schedule it produced, the realized outcome, AS awards and stochastic price scenarios. Systems are
battery_master.battery_system (system_id = battery_system_id)."""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Numeric, SmallInteger, Text

from app.database import Base


class OptimizationRun(Base):
    __tablename__ = "optimization_run"
    __table_args__ = {"schema": "battery_master"}

    run_id = Column(BigInteger, primary_key=True)
    system_id = Column(BigInteger, ForeignKey("battery_master.battery_system.battery_system_id", ondelete="CASCADE"),
                       nullable=False)
    issued_at = Column(DateTime(timezone=True), nullable=False)
    horizon_start = Column(DateTime(timezone=True), nullable=False)
    horizon_end = Column(DateTime(timezone=True), nullable=False)
    resolution_min = Column(SmallInteger, nullable=False)
    method = Column(Text)
    objective = Column(Text)
    solver_status = Column(Text)
    expected_profit_usd = Column(Numeric(12, 2))
    solve_seconds = Column(Numeric(8, 3))


class DecisionState(Base):
    __tablename__ = "decision_state"
    __table_args__ = {"schema": "battery_master"}

    run_id = Column(BigInteger, ForeignKey("battery_master.optimization_run.run_id", ondelete="CASCADE"),
                    primary_key=True)
    soc_start_pct = Column(Numeric(5, 2), nullable=False)
    soh_pct = Column(Numeric(5, 2))
    usable_energy_mwh = Column(Numeric(10, 3))
    avg_cell_temp_c = Column(Numeric(5, 1))
    p_charge_avail_kw = Column(Numeric(10, 2))
    p_discharge_avail_kw = Column(Numeric(10, 2))
    cycles_used_today = Column(Numeric(5, 2))
    aux_load_forecast_kw = Column(Numeric(10, 2))
    reserved_mw_as = Column(Numeric(8, 3))


class DispatchSchedule(Base):
    __tablename__ = "dispatch_schedule"
    __table_args__ = {"schema": "battery_master"}

    run_id = Column(BigInteger, ForeignKey("battery_master.optimization_run.run_id", ondelete="CASCADE"),
                    primary_key=True)
    interval_start = Column(DateTime(timezone=True), primary_key=True)
    p_setpoint_kw = Column(Numeric(10, 2), nullable=False)
    soc_target_pct = Column(Numeric(5, 2))
    mode = Column(Text)
    market = Column(Text)
    forecast_price_mwh = Column(Numeric(10, 2))


class DispatchOutcome(Base):
    __tablename__ = "dispatch_outcome"
    __table_args__ = {"schema": "battery_master"}

    system_id = Column(BigInteger, ForeignKey("battery_master.battery_system.battery_system_id", ondelete="CASCADE"),
                       primary_key=True)
    interval_start = Column(DateTime(timezone=True), primary_key=True)
    run_id = Column(BigInteger, ForeignKey("battery_master.optimization_run.run_id", ondelete="SET NULL"))
    p_scheduled_kw = Column(Numeric(10, 2))
    p_actual_kw = Column(Numeric(10, 2))
    price_mwh = Column(Numeric(10, 2))
    energy_mwh = Column(Numeric(12, 6))
    gross_revenue_usd = Column(Numeric(12, 4))
    degradation_cost_usd = Column(Numeric(12, 4))
    grid_cost_usd = Column(Numeric(12, 4))
    net_pnl_usd = Column(Numeric(12, 4))


class AsAward(Base):
    __tablename__ = "as_award"
    __table_args__ = {"schema": "battery_master"}

    award_id = Column(BigInteger, primary_key=True)
    system_id = Column(BigInteger, ForeignKey("battery_master.battery_system.battery_system_id", ondelete="CASCADE"),
                       nullable=False)
    product_id = Column(BigInteger, ForeignKey("battery_master.as_product.product_id", ondelete="CASCADE"),
                        nullable=False)
    delivery_start = Column(DateTime(timezone=True), nullable=False)
    delivery_end = Column(DateTime(timezone=True), nullable=False)
    awarded_mw = Column(Numeric(8, 3), nullable=False)
    capacity_price_mw = Column(Numeric(10, 2))
    revenue_usd = Column(Numeric(12, 2))


class PriceScenario(Base):
    __tablename__ = "price_scenario"
    __table_args__ = {"schema": "battery_master"}

    node_id = Column(BigInteger, ForeignKey("battery_master.price_node.node_id", ondelete="CASCADE"), primary_key=True)
    issued_at = Column(DateTime(timezone=True), primary_key=True)
    scenario_id = Column(SmallInteger, primary_key=True)
    target_ts = Column(DateTime(timezone=True), primary_key=True)
    price_mwh = Column(Numeric(10, 2), nullable=False)
    probability = Column(Numeric(6, 4))
