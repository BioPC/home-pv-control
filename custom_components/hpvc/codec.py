"""Strict JSON codec for immutable, HA-independent records."""

from __future__ import annotations
from dataclasses import fields, is_dataclass
from enum import Enum
import math
import types
from typing import Union, get_args, get_origin, get_type_hints


class SchemaError(ValueError):
    """Untrusted persisted/imported data violates a contract."""


class Record:
    def to_dict(self) -> dict:
        return encode(self)

    @classmethod
    def from_dict(cls, value: dict):
        return decode(cls, value)


def encode(value):
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            field.name: encode(getattr(value, field.name)) for field in fields(value)
        }
    if isinstance(value, tuple):
        return [encode(item) for item in value]
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise SchemaError(f"Unsupported/non-finite record value: {type(value).__name__}")


def decode(kind, value):
    origin, args = get_origin(kind), get_args(kind)
    if origin in (Union, types.UnionType):
        for option in args:
            try:
                return decode(option, value)
            except (SchemaError, ValueError, TypeError):
                pass
        raise SchemaError(f"Invalid optional/union value for {kind}")
    if kind is type(None):
        if value is not None:
            raise SchemaError("Expected explicit null")
        return None
    if origin is tuple:
        if not isinstance(value, (list, tuple)):
            raise SchemaError("Expected array")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(decode(args[0], item) for item in value)
        if len(value) != len(args):
            raise SchemaError("Tuple length mismatch")
        return tuple(decode(typ, item) for typ, item in zip(args, value))
    if isinstance(kind, type) and issubclass(kind, Enum):
        if not isinstance(value, str):
            raise SchemaError("Expected enum string")
        try:
            return kind(value)
        except ValueError as err:
            raise SchemaError(f"Unknown {kind.__name__}") from err
    if isinstance(kind, type) and is_dataclass(kind):
        if not isinstance(value, dict):
            raise SchemaError("Expected record object")
        expected = {field.name for field in fields(kind)}
        if set(value) != expected:
            raise SchemaError(
                f"{kind.__name__}: missing/extra fields {set(value) ^ expected}"
            )
        hints = get_type_hints(kind)
        try:
            return kind(**{name: decode(hints[name], value[name]) for name in expected})
        except (TypeError, ValueError) as err:
            raise SchemaError(f"Invalid {kind.__name__}: {err}") from err
    if kind is float:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise SchemaError("Expected finite number")
        return float(value)
    if kind in (str, bool, int):
        if type(value) is not kind:
            raise SchemaError(f"Expected {kind.__name__}")
        return value
    raise SchemaError(f"Unsupported record annotation {kind}")
