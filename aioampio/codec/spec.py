# pylint: disable=invalid-name

"""Field-specification DSL for decoding Ampio CAN payloads.

This module defines a small set of composable field extractors (specs) that
describe how to parse a `memoryview` into a Python dictionary.  The same DSL
is used throughout the codec layer to keep decoders concise and testable.

Key ideas
---------
- Each spec implements two methods:
    * min_len()  -> int   : minimal payload length needed for the field
    * extract(data, out)  : bool  (True on success; may mutate `out`)
- `decode_payload()` applies a sequence of specs and returns a dict
  (or None if a required field is unavailable).
- Shorthands (U8, I16, BitFlag, EnumMasked, etc.) keep decoders ergonomic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

__all__ = [
    "_FieldSpec",
    "BeScalar",
    "Bit",
    "BitFlag",
    "BoolMask",
    "Const",
    "Enum16",
    "Enum8",
    "EnumField",
    "EnumMasked",
    "I16",
    "I32",
    "I8",
    "Mask",
    "OptionalField",
    "Repeat",
    "Scalar",
    "U16",
    "U32",
    "U8",
    "decode_payload",
    "decode_series",
    "required_len",
]

# ---------------------------------------------------------------------------
# Core field-spec types
# ---------------------------------------------------------------------------


class _FieldSpec:
    """Abstract base for all field extractors."""

    def min_len(self) -> int:
        """Return minimal number of bytes required for this field."""

    def extract(self, data: memoryview, out: dict[str, Any]) -> bool:
        """Extract the field from `data` into `out`. Return True on success."""


@dataclass(frozen=True)
class Const(_FieldSpec):
    """Inject a constant value under `name`."""

    name: str
    value: Any

    def min_len(self) -> int:
        return 0

    def extract(self, data: memoryview, out: dict[str, Any]) -> bool:  # noqa: ARG002
        out[self.name] = self.value
        return True


@dataclass(frozen=True)
class Scalar(_FieldSpec):
    """Read an integer slice then apply an affine transform.

    value = (int.from_bytes(slice, endian, signed) + add) * mul
    The result can optionally be rounded to `ndigits`. If `ndigits` is None and the
    value is integral, it is stored as `int` to avoid spuriously introducing floats.
    """

    name: str
    offset: int
    size: int
    signed: bool = False
    endian: str = "little"
    add: float = 0.0
    mul: float = 1.0
    ndigits: int | None = None

    def min_len(self) -> int:
        return self.offset + self.size

    def extract(self, data: memoryview, out: dict[str, Any]) -> bool:
        end = self.offset + self.size
        if end > len(data):
            return False
        raw = int.from_bytes(data[self.offset : end], self.endian, signed=self.signed)
        val: float = (raw + self.add) * self.mul
        if self.ndigits is not None:
            val = round(val, self.ndigits)
        out[self.name] = (
            int(val) if self.ndigits is None and float(val).is_integer() else val
        )
        return True


@dataclass(frozen=True)
class Mask(_FieldSpec):
    """Extract masked bits from a single byte.

    If `as_bool` is True, store a boolean (masked != 0). Otherwise store the
    integer value after right-shifting by `shift`.
    """

    name: str
    offset: int
    mask: int
    shift: int = 0
    as_bool: bool = False

    def min_len(self) -> int:
        return self.offset + 1

    def extract(self, data: memoryview, out: dict[str, Any]) -> bool:
        if self.offset >= len(data):
            return False
        v = (data[self.offset] & self.mask) >> self.shift
        out[self.name] = bool(v) if self.as_bool else v
        return True


@dataclass(frozen=True)
class OptionalField(_FieldSpec):
    """Wrap another spec as optional.

    If the inner spec fails (e.g., data too short), this spec still returns True.
    When `set_default_on_missing` is True and the inner spec exposes a `name`,
    the `default` value is stored under that name even if the inner spec failed.
    """

    inner: _FieldSpec
    default: Any | None = None
    set_default_on_missing: bool = False

    def min_len(self) -> int:
        # Optional fields do not increase the hard length requirement.
        return 0

    def extract(self, data: memoryview, out: dict[str, Any]) -> bool:
        field_name: str | None = getattr(self.inner, "name", None)
        if self.inner.min_len() <= len(data) and self.inner.extract(data, out):
            return True
        if self.set_default_on_missing and field_name is not None:
            out[field_name] = self.default
        return True


class EnumField(_FieldSpec):
    """Map a numeric code to a string label, from a masked byte or scalar.

    Modes
    -----
    - masked enum: provide `mask` (and optional `shift`) to read one byte at `offset`
    - scalar enum: omit `mask`, set `size` to 1 or 2 to read u8/u16 (little-endian)

    Mapping
    -------
    - `mapping`: dict[int, str] maps code -> label
    - `default`: fallback label when code not in mapping (if None, use `str(code)`)
    """

    def __init__(
        self,
        name: str,
        offset: int,
        size: int = 1,
        *,
        mask: int | None = None,
        shift: int = 0,
        mapping: Optional[Mapping[int, str]] = None,
        default: Optional[str] = None,
    ) -> None:
        self.name = name
        self.offset = offset
        self.size = size
        self.mask = mask
        self.shift = shift
        self.mapping = dict(mapping) if mapping else {}
        self.default = default

    def min_len(self) -> int:
        need = 1 if self.mask is not None else self.size
        return self.offset + need

    def extract(self, data: memoryview, out: dict[str, Any]) -> bool:
        if len(data) < self.min_len():
            return False

        if self.mask is not None:
            code = (int(data[self.offset]) & self.mask) >> self.shift
        else:
            if self.size == 1:
                code = int(data[self.offset])
            elif self.size == 2:
                end = self.offset + 2
                code = int.from_bytes(data[self.offset : end], "little", signed=False)
            else:
                return False

        out[self.name] = self._map(code)
        return True

    # convenience (not used by decode_payload)
    def decode(self, data: memoryview) -> tuple[str, Any] | None:
        """Decode a single enum field; return (name, value) or None on failure."""
        tmp: dict[str, Any] = {}
        if not self.extract(data, tmp):
            return None
        return (self.name, tmp[self.name])

    def _map(self, value: int) -> str:
        if value in self.mapping:
            return self.mapping[value]
        return self.default if self.default is not None else str(value)


@dataclass(frozen=True)
class Repeat(_FieldSpec):
    """Decode a repeated element into a list.

    The list is stored under `name`. Each element is described by `element_specs`
    with offsets relative to that element's start. Elements start at
    `base_offset + i*stride` for i in [0..count). If `sparse` is True, incomplete
    elements are skipped; otherwise decoding stops at the first incomplete element.
    """

    name: str
    element_specs: Sequence[_FieldSpec]
    count: int
    base_offset: int
    stride: int
    sparse: bool = False

    def min_len(self) -> int:
        # Lenient: do not force a pre-length requirement. `extract` decodes
        # as many full elements as available.
        return 0

    def extract(self, data: memoryview, out: dict[str, Any]) -> bool:
        items: list[dict[str, Any]] = []
        for i in range(self.count):
            delta = self.base_offset + i * self.stride
            shifted = tuple(_shift_spec(s, delta) for s in self.element_specs)
            payload = decode_payload(data, shifted)
            if payload is None:
                if self.sparse:
                    continue
                break
            items.append(payload)
        out[self.name] = items
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def required_len(specs: Sequence[_FieldSpec]) -> int:
    """Compute the minimal data length required by a sequence of specs."""
    m = 0
    for s in specs:
        m = max(m, s.min_len())
    return m


def decode_payload(
    data: memoryview, specs: Sequence[_FieldSpec]
) -> dict[str, Any] | None:
    """Apply specs to `data` and return a payload dict; return None on failure."""
    out: dict[str, Any] = {}
    if len(data) < required_len(specs):
        return None
    for s in specs:
        if not s.extract(data, out):
            return None
    return out


def decode_series(
    data: memoryview,
    count: int,
    element_specs: Callable[[int], Sequence[_FieldSpec]],
) -> list[dict[str, Any]]:
    """Decode `count` elements using `element_specs(i)` with absolute offsets.

    Elements that can't be fully decoded (insufficient data) are skipped.
    """
    out: list[dict[str, Any]] = []
    for i in range(count):
        specs = element_specs(i)
        payload = decode_payload(data, specs)
        if payload is not None:
            out.append(payload)
    return out


def _shift_spec(spec: _FieldSpec, delta: int) -> _FieldSpec:
    """Return a copy of `spec` with its offsets shifted by `delta` bytes."""
    if isinstance(spec, Scalar):
        return Scalar(
            spec.name,
            spec.offset + delta,
            spec.size,
            signed=spec.signed,
            endian=spec.endian,
            add=spec.add,
            mul=spec.mul,
            ndigits=spec.ndigits,
        )
    if isinstance(spec, Mask):
        return Mask(
            spec.name,
            spec.offset + delta,
            spec.mask,
            shift=spec.shift,
            as_bool=spec.as_bool,
        )
    if isinstance(spec, EnumField):
        return EnumField(
            spec.name,
            spec.offset + delta,
            size=spec.size,
            mask=spec.mask,
            shift=spec.shift,
            mapping=spec.mapping,
            default=spec.default,
        )
    if isinstance(spec, Const):
        return spec
    if isinstance(spec, OptionalField):
        return OptionalField(
            _shift_spec(spec.inner, delta),
            default=spec.default,
            set_default_on_missing=spec.set_default_on_missing,
        )
    return spec


# ---------------------------------------------------------------------------
# Shorthands / sugar
# ---------------------------------------------------------------------------


def U8(
    name: str,
    offset: int,
    *,
    add: float = 0.0,
    mul: float = 1.0,
    ndigits: int | None = None,
) -> Scalar:
    """Unsigned 8-bit integer at `offset`, with optional affine transform."""
    return Scalar(
        name,
        offset,
        1,
        signed=False,
        endian="little",
        add=add,
        mul=mul,
        ndigits=ndigits,
    )


def I8(
    name: str,
    offset: int,
    *,
    add: float = 0.0,
    mul: float = 1.0,
    ndigits: int | None = None,
) -> Scalar:
    """Signed 8-bit integer at `offset`, with optional affine transform."""
    return Scalar(
        name, offset, 1, signed=True, endian="little", add=add, mul=mul, ndigits=ndigits
    )


def U16(
    name: str,
    offset: int,
    *,
    endian: str = "little",
    add: float = 0.0,
    mul: float = 1.0,
    ndigits: int | None = None,
) -> Scalar:
    """Unsigned 16-bit integer at `offset` (`endian`), with optional transform."""
    return Scalar(
        name, offset, 2, signed=False, endian=endian, add=add, mul=mul, ndigits=ndigits
    )


def I16(
    name: str,
    offset: int,
    *,
    endian: str = "little",
    add: float = 0.0,
    mul: float = 1.0,
    ndigits: int | None = None,
) -> Scalar:
    """Signed 16-bit integer at `offset` (`endian`), with optional transform."""
    return Scalar(
        name, offset, 2, signed=True, endian=endian, add=add, mul=mul, ndigits=ndigits
    )


def U32(
    name: str,
    offset: int,
    *,
    endian: str = "little",
    add: float = 0.0,
    mul: float = 1.0,
    ndigits: int | None = None,
) -> Scalar:
    """Unsigned 32-bit integer at `offset` (`endian`), with optional transform."""
    return Scalar(
        name, offset, 4, signed=False, endian=endian, add=add, mul=mul, ndigits=ndigits
    )


def I32(
    name: str,
    offset: int,
    *,
    endian: str = "little",
    add: float = 0.0,
    mul: float = 1.0,
    ndigits: int | None = None,
) -> Scalar:
    """Signed 32-bit integer at `offset` (`endian`), with optional transform."""
    return Scalar(
        name, offset, 4, signed=True, endian=endian, add=add, mul=mul, ndigits=ndigits
    )


def BeScalar(
    name: str,
    offset: int,
    size: int,
    *,
    signed: bool = False,
    add: float = 0.0,
    mul: float = 1.0,
    ndigits: int | None = None,
) -> Scalar:
    """Big-endian integer slice at `offset` with optional transform."""
    return Scalar(
        name,
        offset,
        size,
        signed=signed,
        endian="big",
        add=add,
        mul=mul,
        ndigits=ndigits,
    )


def BoolMask(name: str, offset: int, mask: int, shift: int = 0) -> Mask:
    """Boolean mask from byte at `offset` (True if `(byte & mask) >> shift` != 0)."""
    return Mask(name, offset, mask, shift=shift, as_bool=True)


def Bit(name: str, offset: int, bit: int, *, as_bool: bool = False) -> Mask:
    """Single-bit extractor from a byte at `offset`."""
    return Mask(name, offset, 1 << bit, shift=bit, as_bool=as_bool)


def BitFlag(name: str, offset: int, bit: int) -> Mask:
    """Boolean single-bit extractor (True/False)."""
    return Bit(name, offset, bit, as_bool=True)


def Enum8(
    name: str,
    offset: int,
    mapping: Optional[Mapping[int, str]] = None,
    default: Optional[str] = None,
) -> EnumField:
    """u8 enum → label."""
    return EnumField(name, offset, size=1, mapping=mapping, default=default)


def Enum16(
    name: str,
    offset: int,
    mapping: Optional[Mapping[int, str]] = None,
    default: Optional[str] = None,
) -> EnumField:
    """u16 (little-endian) enum → label."""
    return EnumField(name, offset, size=2, mapping=mapping, default=default)


def EnumMasked(
    name: str,
    offset: int,
    *,
    mask: int,
    shift: int = 0,
    mapping: Optional[Mapping[int, str]] = None,
    default: Optional[str] = None,
) -> EnumField:
    """Masked enum from a single byte ( (byte & mask) >> shift )."""
    return EnumField(
        name, offset, size=1, mask=mask, shift=shift, mapping=mapping, default=default
    )
