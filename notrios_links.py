"""Conversion bounds shared by the publication importer and future link adapter."""
from dataclasses import dataclass, fields

from notrios_archive import NotriosError


@dataclass(frozen=True)
class ConversionLimits:
    max_body_bytes: int = 16777216
    max_projected_body_bytes: int = 33554432
    max_links_per_note: int = 10000
    max_resource_relations_per_note: int = 10000
    max_fragment_bytes: int = 1024
    batch_rows: int = 1000
    batch_bytes: int = 33554432
    copy_chunk_bytes: int = 1048576

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or not 0 < value <= field.default:
                raise NotriosError("limit", f"invalid conversion limit: {field.name}")


DEFAULT_CONVERSION_LIMITS = ConversionLimits()
