"""Read-only adapter boundary; no concrete actuator adapters in this phase."""

from typing import Protocol
from ..control.models import (
    ControllerConfiguration,
    ControllerObservation,
    RepresentedTarget,
)


class ControllerAdapter(Protocol):
    def represent(
        self, config: ControllerConfiguration, allocated_target_w: float
    ) -> RepresentedTarget:
        """Describe a representable target without executing it."""

    def normalize(self, config: ControllerConfiguration) -> ControllerObservation:
        """Describe observations without performing actuator writes."""
