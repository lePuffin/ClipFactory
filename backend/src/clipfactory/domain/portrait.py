"""Source-normalized portrait framing evidence, independent of detector/vendor."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class FaceBox:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        if (
            not all(isfinite(value) for value in (self.x, self.y, self.width, self.height))
            or min(self.x, self.y) < 0
            or min(self.width, self.height) <= 0
            or self.x + self.width > 1
            or self.y + self.height > 1
        ):
            raise ValueError("face box must lie inside the normalized source frame")
