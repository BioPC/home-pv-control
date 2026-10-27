"""Report boundary only; generation is not implemented in the foundation."""

from dataclasses import dataclass
from .codec import Record
from .control.models import PlantConfiguration, PlantSnapshot
from .execution.models import ExecutionSnapshot
from .hbc.models import HbcState


@dataclass(frozen=True)
class ReportSnapshot(Record):
    generation_id: str
    configuration: PlantConfiguration
    plant: PlantSnapshot
    execution: ExecutionSnapshot
    hbc: HbcState
    history_revision: int
