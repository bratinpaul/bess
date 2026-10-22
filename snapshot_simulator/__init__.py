"""Snapshot simulator: writes 5-minute plant snapshot files (bess_snapshot.json format) sampled from stored
telemetry into the realtime inbox. See README.md."""
from snapshot_simulator.simulator import (  # noqa: F401
    INBOX,
    MAX_FILES,
    SimulationResult,
    SimulatorError,
    simulate,
    source_info,
)
