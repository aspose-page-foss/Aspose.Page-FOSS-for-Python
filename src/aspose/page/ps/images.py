"""Image resource storage for PS/EPS conversion."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import PsUndefinedError


@dataclass
class PsImageResource:
    """Represents a decoded image resource.

    Example:
        >>> resource = PsImageResource("img1", b"\x00", 1, 1, 8, "DeviceGray", False, False, None, None)
        >>> resource.width
        1
    """

    image_id: str
    data: bytes
    width: int
    height: int
    bits_per_component: int
    color_space: str
    interpolate: bool
    mask: bool
    filter: str | None
    filter_params: dict | None
    decode: tuple[float, ...] | None = None
    mask_polarity: bool = True


class PsImageStore:
    """Store image resources by id.

    Example:
        >>> store = PsImageStore()
        >>> image_id = store.register(PsImageResource("", b"", 1, 1, 8, "DeviceGray", False, False, None, None))
        >>> store.get(image_id).width
        1
    """

    def __init__(self) -> None:
        self._images: dict[str, PsImageResource] = {}
        self._counter = 1

    def register(self, image: PsImageResource) -> str:
        image_id = image.image_id or f"img{self._counter}"
        self._counter += 1
        if image.image_id != image_id:
            image = PsImageResource(
                image_id,
                image.data,
                image.width,
                image.height,
                image.bits_per_component,
                image.color_space,
                image.interpolate,
                image.mask,
                image.filter,
                image.filter_params,
                image.decode,
                image.mask_polarity,
            )
        self._images[image_id] = image
        return image_id

    def get(self, image_id: str) -> PsImageResource:
        if image_id not in self._images:
            raise PsUndefinedError(f"unknown image resource {image_id}")
        return self._images[image_id]

    def items(self):
        return self._images.items()
