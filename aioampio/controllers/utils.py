"""Helper functions for controllers."""

import re
import struct


def get_trailing_number(s: str) -> int | None:
    """Get trailing number from a string, e.g. 'sensor12' -> 12."""
    match = re.search(r"(\d+)$", s)
    return int(match.group(1)) if match else None


def get_entity_index(s: str) -> int | None:
    """Get entity index from a string, e.g. 'sensor12' -> 11 (0-based)."""
    entity_index = get_trailing_number(s)
    if entity_index is None or entity_index < 1:
        return None

    entity_index -= 1
    return entity_index


def generate_multican_payload(
    can_id: int, data: bytes | bytearray | memoryview
) -> list[bytes]:
    """Generate multiple CAN frames for data longer than 8 bytes."""
    b = bytes(data)  # ensure immutable bytes
    length = len(b) & 0xFF
    # header = bytes((0x14, length))
    # full = header + b # header + payload
    full = b  # payload only
    checksum = sum(full) & 0xFF

    # First chunk: [(length>>1)+2, checksum] with uint8 wrap-around
    first_byte = ((length + 1) >> 1) & 0xFF
    chunks: list[bytes] = [bytes((first_byte, checksum))]

    # Then the data, split into 2-byte pieces
    for i in range(0, len(full), 2):
        chunks.append(full[i : i + 2])

    function_code = 0x16
    payloads: list[bytes] = []
    # workaround for caneth issue with identical can_ids in multi-frame
    for _ in range(len(chunks)):
        payloads.append(bytes())  # struct.pack(">I", can_id))
    for idx, chunk in enumerate(chunks):
        # Each chunk is prefixed with [function_code, ifd]
        payload = struct.pack(">I", can_id) + bytes((function_code, idx & 0xFF)) + chunk
        payloads.append(payload)
    return payloads
