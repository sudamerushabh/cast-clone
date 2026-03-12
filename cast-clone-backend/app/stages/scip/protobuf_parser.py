"""Parse SCIP protobuf index files into Python dataclasses.

SCIP (SCIP Code Intelligence Protocol) indexers produce a Protobuf file
(typically `index.scip`) containing symbol definitions, references, and
relationships for an entire codebase. This module parses that file into
lightweight Python dataclasses for consumption by the merger.

The SCIP proto schema is available at:
https://github.com/sourcegraph/scip/blob/main/scip.proto

We use raw protobuf wire-format parsing via google.protobuf to avoid
needing generated code from the .proto file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# -- Symbol Role Bit Flags --------------------------------------------------


class SymbolRole:
    """SCIP SymbolRole bit flags.

    See: https://github.com/sourcegraph/scip/blob/main/scip.proto
    """

    DEFINITION = 0x1
    IMPORT = 0x2
    WRITE_ACCESS = 0x4
    READ_ACCESS = 0x8
    GENERATED = 0x10
    TEST = 0x20
    FORWARD_DEFINITION = 0x80

    @staticmethod
    def is_definition(roles: int) -> bool:
        return bool(roles & SymbolRole.DEFINITION)

    @staticmethod
    def is_reference(roles: int) -> bool:
        """A reference is any occurrence that is NOT a definition."""
        return not SymbolRole.is_definition(roles)

    @staticmethod
    def has_write_access(roles: int) -> bool:
        return bool(roles & SymbolRole.WRITE_ACCESS)

    @staticmethod
    def has_read_access(roles: int) -> bool:
        return bool(roles & SymbolRole.READ_ACCESS)


# -- Data Classes ------------------------------------------------------------


@dataclass
class SCIPRelationship:
    """A relationship between two symbols (e.g., implementation)."""

    symbol: str
    is_implementation: bool = False
    is_reference: bool = False
    is_type_definition: bool = False


@dataclass
class SCIPOccurrence:
    """A single occurrence of a symbol in a document.

    Range format:
    - 3 elements: [line, start_col, end_col] (single line)
    - 4 elements: [start_line, start_col, end_line, end_col] (multi-line)
    """

    range: list[int]
    symbol: str
    symbol_roles: int

    @property
    def start_line(self) -> int:
        return self.range[0] if len(self.range) >= 1 else 0

    @property
    def start_col(self) -> int:
        return self.range[1] if len(self.range) >= 2 else 0

    @property
    def end_line(self) -> int:
        if len(self.range) == 4:
            return self.range[2]
        elif len(self.range) >= 1:
            return self.range[0]  # same line
        return 0

    @property
    def end_col(self) -> int:
        if len(self.range) == 4:
            return self.range[3]
        elif len(self.range) >= 3:
            return self.range[2]
        return 0

    @property
    def is_definition(self) -> bool:
        return SymbolRole.is_definition(self.symbol_roles)

    @property
    def is_reference(self) -> bool:
        return SymbolRole.is_reference(self.symbol_roles)


@dataclass
class SCIPSymbolInfo:
    """Symbol metadata: documentation, relationships."""

    symbol: str
    documentation: list[str] = field(default_factory=list)
    relationships: list[SCIPRelationship] = field(default_factory=list)


@dataclass
class SCIPDocument:
    """A single file in the SCIP index."""

    relative_path: str
    occurrences: list[SCIPOccurrence] = field(default_factory=list)
    symbols: list[SCIPSymbolInfo] = field(default_factory=list)


@dataclass
class SCIPIndex:
    """Top-level SCIP index containing all documents."""

    documents: list[SCIPDocument] = field(default_factory=list)
    metadata_tool_name: str = ""
    metadata_tool_version: str = ""


# -- Build from structured data (for testing) --------------------------------


def build_scip_index_from_data(data: dict[str, Any]) -> SCIPIndex:
    """Build an SCIPIndex from a dictionary structure.

    Useful for creating test data without protobuf serialization.
    """
    metadata = data.get("metadata", {})
    tool_info = metadata.get("tool_info", {})

    documents = []
    for doc_data in data.get("documents", []):
        occurrences = [
            SCIPOccurrence(
                range=occ.get("range", []),
                symbol=occ.get("symbol", ""),
                symbol_roles=occ.get("symbol_roles", 0),
            )
            for occ in doc_data.get("occurrences", [])
        ]

        symbols = []
        for sym_data in doc_data.get("symbols", []):
            relationships = [
                SCIPRelationship(
                    symbol=rel.get("symbol", ""),
                    is_implementation=rel.get("is_implementation", False),
                    is_reference=rel.get("is_reference", False),
                    is_type_definition=rel.get("is_type_definition", False),
                )
                for rel in sym_data.get("relationships", [])
            ]
            symbols.append(
                SCIPSymbolInfo(
                    symbol=sym_data.get("symbol", ""),
                    documentation=sym_data.get("documentation", []),
                    relationships=relationships,
                )
            )

        documents.append(
            SCIPDocument(
                relative_path=doc_data.get("relative_path", ""),
                occurrences=occurrences,
                symbols=symbols,
            )
        )

    return SCIPIndex(
        documents=documents,
        metadata_tool_name=tool_info.get("name", ""),
        metadata_tool_version=tool_info.get("version", ""),
    )


# -- Protobuf Wire Format Parser --------------------------------------------
#
# SCIP proto field numbers (from scip.proto):
#
# message Index {
#   Metadata metadata = 1;
#   repeated Document documents = 2;
# }
#
# message Metadata {
#   enum ProtocolVersion { UnspecifiedProtocolVersion = 0; }
#   ProtocolVersion version = 1;
#   ToolInfo tool_info = 2;
#   string project_root = 3;
#   bool text_document_encoding = 4;
# }
#
# message ToolInfo {
#   string name = 1;
#   string version = 2;
#   repeated string arguments = 3;
# }
#
# message Document {
#   string language = 4;
#   string relative_path = 1;
#   repeated Occurrence occurrences = 2;
#   repeated SymbolInformation symbols = 3;
#   string text = 5;
# }
#
# message Occurrence {
#   repeated int32 range = 1 [packed];
#   string symbol = 2;
#   int32 symbol_roles = 3;
#   repeated string override_documentation = 4;
#   SyntaxKind syntax_kind = 5;
#   repeated Diagnostic diagnostics = 6;
# }
#
# message SymbolInformation {
#   string symbol = 1;
#   repeated string documentation = 3;
#   repeated Relationship relationships = 4;
#   Kind kind = 5;
#   string display_name = 6;
#   SignatureDocumentation signature_documentation = 7;
#   repeated string enclosing_symbol = 8;
# }
#
# message Relationship {
#   string symbol = 1;
#   bool is_reference = 2;
#   bool is_implementation = 3;
#   bool is_type_definition = 4;
#   bool is_definition = 5;
# }


def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Decode a protobuf varint, return (value, new_position)."""
    result = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        result |= (b & 0x7F) << shift
        pos += 1
        if not (b & 0x80):
            break
        shift += 7
    return result, pos


def _decode_key(data: bytes, pos: int) -> tuple[int, int, int]:
    """Decode a protobuf field key, return (field_number, wire_type, new_position)."""
    varint, pos = _decode_varint(data, pos)
    field_number = varint >> 3
    wire_type = varint & 0x07
    return field_number, wire_type, pos


def _skip_field(data: bytes, pos: int, wire_type: int) -> int:
    """Skip over a protobuf field we don't care about."""
    if wire_type == 0:  # varint
        _, pos = _decode_varint(data, pos)
    elif wire_type == 1:  # 64-bit
        pos += 8
    elif wire_type == 2:  # length-delimited
        length, pos = _decode_varint(data, pos)
        pos += length
    elif wire_type == 5:  # 32-bit
        pos += 4
    else:
        raise ValueError(f"Unknown wire type: {wire_type}")
    return pos


def _parse_packed_int32(data: bytes) -> list[int]:
    """Parse a packed repeated int32 field."""
    result = []
    pos = 0
    while pos < len(data):
        val, pos = _decode_varint(data, pos)
        # Decode as signed int32 (zigzag not used for range in SCIP)
        if val > 0x7FFFFFFF:
            val -= 0x100000000
        result.append(val)
    return result


def _parse_occurrence(data: bytes) -> SCIPOccurrence:
    """Parse an Occurrence message from raw bytes."""
    pos = 0
    range_vals: list[int] = []
    symbol = ""
    symbol_roles = 0

    while pos < len(data):
        field_number, wire_type, pos = _decode_key(data, pos)

        if field_number == 1 and wire_type == 2:  # range (packed int32)
            length, pos = _decode_varint(data, pos)
            range_vals = _parse_packed_int32(data[pos : pos + length])
            pos += length
        elif field_number == 2 and wire_type == 2:  # symbol (string)
            length, pos = _decode_varint(data, pos)
            symbol = data[pos : pos + length].decode("utf-8", errors="replace")
            pos += length
        elif field_number == 3 and wire_type == 0:  # symbol_roles (int32)
            symbol_roles, pos = _decode_varint(data, pos)
        else:
            pos = _skip_field(data, pos, wire_type)

    return SCIPOccurrence(range=range_vals, symbol=symbol, symbol_roles=symbol_roles)


def _parse_relationship(data: bytes) -> SCIPRelationship:
    """Parse a Relationship message from raw bytes."""
    pos = 0
    symbol = ""
    is_reference = False
    is_implementation = False
    is_type_definition = False

    while pos < len(data):
        field_number, wire_type, pos = _decode_key(data, pos)

        if field_number == 1 and wire_type == 2:  # symbol
            length, pos = _decode_varint(data, pos)
            symbol = data[pos : pos + length].decode("utf-8", errors="replace")
            pos += length
        elif field_number == 2 and wire_type == 0:  # is_reference
            val, pos = _decode_varint(data, pos)
            is_reference = bool(val)
        elif field_number == 3 and wire_type == 0:  # is_implementation
            val, pos = _decode_varint(data, pos)
            is_implementation = bool(val)
        elif field_number == 4 and wire_type == 0:  # is_type_definition
            val, pos = _decode_varint(data, pos)
            is_type_definition = bool(val)
        else:
            pos = _skip_field(data, pos, wire_type)

    return SCIPRelationship(
        symbol=symbol,
        is_reference=is_reference,
        is_implementation=is_implementation,
        is_type_definition=is_type_definition,
    )


def _parse_symbol_info(data: bytes) -> SCIPSymbolInfo:
    """Parse a SymbolInformation message from raw bytes."""
    pos = 0
    symbol = ""
    documentation: list[str] = []
    relationships: list[SCIPRelationship] = []

    while pos < len(data):
        field_number, wire_type, pos = _decode_key(data, pos)

        if field_number == 1 and wire_type == 2:  # symbol
            length, pos = _decode_varint(data, pos)
            symbol = data[pos : pos + length].decode("utf-8", errors="replace")
            pos += length
        elif field_number == 3 and wire_type == 2:  # documentation
            length, pos = _decode_varint(data, pos)
            documentation.append(
                data[pos : pos + length].decode("utf-8", errors="replace")
            )
            pos += length
        elif field_number == 4 and wire_type == 2:  # relationships
            length, pos = _decode_varint(data, pos)
            relationships.append(_parse_relationship(data[pos : pos + length]))
            pos += length
        else:
            pos = _skip_field(data, pos, wire_type)

    return SCIPSymbolInfo(
        symbol=symbol, documentation=documentation, relationships=relationships
    )


def _parse_document(data: bytes) -> SCIPDocument:
    """Parse a Document message from raw bytes."""
    pos = 0
    relative_path = ""
    occurrences: list[SCIPOccurrence] = []
    symbols: list[SCIPSymbolInfo] = []

    while pos < len(data):
        field_number, wire_type, pos = _decode_key(data, pos)

        if field_number == 1 and wire_type == 2:  # relative_path
            length, pos = _decode_varint(data, pos)
            relative_path = data[pos : pos + length].decode("utf-8", errors="replace")
            pos += length
        elif field_number == 2 and wire_type == 2:  # occurrences
            length, pos = _decode_varint(data, pos)
            occurrences.append(_parse_occurrence(data[pos : pos + length]))
            pos += length
        elif field_number == 3 and wire_type == 2:  # symbols
            length, pos = _decode_varint(data, pos)
            symbols.append(_parse_symbol_info(data[pos : pos + length]))
            pos += length
        else:
            pos = _skip_field(data, pos, wire_type)

    return SCIPDocument(
        relative_path=relative_path, occurrences=occurrences, symbols=symbols
    )


def _parse_tool_info(data: bytes) -> tuple[str, str]:
    """Parse a ToolInfo message, return (name, version)."""
    pos = 0
    name = ""
    version = ""

    while pos < len(data):
        field_number, wire_type, pos = _decode_key(data, pos)

        if field_number == 1 and wire_type == 2:  # name
            length, pos = _decode_varint(data, pos)
            name = data[pos : pos + length].decode("utf-8", errors="replace")
            pos += length
        elif field_number == 2 and wire_type == 2:  # version
            length, pos = _decode_varint(data, pos)
            version = data[pos : pos + length].decode("utf-8", errors="replace")
            pos += length
        else:
            pos = _skip_field(data, pos, wire_type)

    return name, version


def _parse_metadata(data: bytes) -> tuple[str, str]:
    """Parse Metadata message, return (tool_name, tool_version)."""
    pos = 0
    tool_name = ""
    tool_version = ""

    while pos < len(data):
        field_number, wire_type, pos = _decode_key(data, pos)

        if field_number == 2 and wire_type == 2:  # tool_info
            length, pos = _decode_varint(data, pos)
            tool_name, tool_version = _parse_tool_info(data[pos : pos + length])
            pos += length
        else:
            pos = _skip_field(data, pos, wire_type)

    return tool_name, tool_version


def parse_scip_index(path: Path) -> SCIPIndex:
    """Parse a SCIP protobuf index file from disk.

    Args:
        path: Path to the .scip protobuf file.

    Returns:
        Parsed SCIPIndex containing all documents, symbols, and occurrences.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"SCIP index file not found: {path}")

    data = path.read_bytes()
    if len(data) == 0:
        return SCIPIndex()

    pos = 0
    tool_name = ""
    tool_version = ""
    documents: list[SCIPDocument] = []

    while pos < len(data):
        field_number, wire_type, pos = _decode_key(data, pos)

        if field_number == 1 and wire_type == 2:  # metadata
            length, pos = _decode_varint(data, pos)
            tool_name, tool_version = _parse_metadata(data[pos : pos + length])
            pos += length
        elif field_number == 2 and wire_type == 2:  # documents
            length, pos = _decode_varint(data, pos)
            documents.append(_parse_document(data[pos : pos + length]))
            pos += length
        else:
            pos = _skip_field(data, pos, wire_type)

    logger.info(
        "scip.parsed",
        path=str(path),
        document_count=len(documents),
        tool=tool_name,
    )

    return SCIPIndex(
        documents=documents,
        metadata_tool_name=tool_name,
        metadata_tool_version=tool_version,
    )


# -- Test Helper: Write a SCIP index file ------------------------------------


def _encode_varint(value: int) -> bytes:
    """Encode an integer as a protobuf varint."""
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def _encode_key(field_number: int, wire_type: int) -> bytes:
    """Encode a protobuf field key."""
    return _encode_varint((field_number << 3) | wire_type)


def _encode_string(field_number: int, value: str) -> bytes:
    """Encode a string field."""
    encoded = value.encode("utf-8")
    return _encode_key(field_number, 2) + _encode_varint(len(encoded)) + encoded


def _encode_varint_field(field_number: int, value: int) -> bytes:
    """Encode a varint field."""
    return _encode_key(field_number, 0) + _encode_varint(value)


def _encode_submessage(field_number: int, data: bytes) -> bytes:
    """Encode a submessage (length-delimited) field."""
    return _encode_key(field_number, 2) + _encode_varint(len(data)) + data


def _encode_packed_int32(field_number: int, values: list[int]) -> bytes:
    """Encode a packed repeated int32 field."""
    packed = b""
    for v in values:
        if v < 0:
            v += 0x100000000
        packed += _encode_varint(v)
    return _encode_key(field_number, 2) + _encode_varint(len(packed)) + packed


def write_test_scip_index(
    path: Path,
    documents: list[dict],
    tool_name: str = "test-indexer",
    tool_version: str = "1.0.0",
) -> None:
    """Write a minimal SCIP protobuf index file for testing.

    Args:
        path: Output file path.
        documents: List of document dicts with keys:
            relative_path, occurrences (list of {range, symbol, symbol_roles}),
            symbols (list of {symbol, documentation, relationships}).
        tool_name: Name of the indexer tool.
        tool_version: Version string.
    """
    # Encode ToolInfo (field 1 = name, field 2 = version)
    tool_info_data = _encode_string(1, tool_name) + _encode_string(2, tool_version)

    # Encode Metadata (field 2 = tool_info)
    metadata_data = _encode_submessage(2, tool_info_data)

    # Top-level: field 1 = metadata
    index_data = _encode_submessage(1, metadata_data)

    # Encode documents
    for doc in documents:
        doc_data = _encode_string(1, doc["relative_path"])

        for occ in doc.get("occurrences", []):
            occ_data = _encode_packed_int32(1, occ["range"])
            occ_data += _encode_string(2, occ["symbol"])
            if occ.get("symbol_roles", 0):
                occ_data += _encode_varint_field(3, occ["symbol_roles"])
            doc_data += _encode_submessage(2, occ_data)

        for sym in doc.get("symbols", []):
            sym_data = _encode_string(1, sym["symbol"])
            for doc_str in sym.get("documentation", []):
                sym_data += _encode_string(3, doc_str)
            for rel in sym.get("relationships", []):
                rel_data = _encode_string(1, rel["symbol"])
                if rel.get("is_reference"):
                    rel_data += _encode_varint_field(2, 1)
                if rel.get("is_implementation"):
                    rel_data += _encode_varint_field(3, 1)
                if rel.get("is_type_definition"):
                    rel_data += _encode_varint_field(4, 1)
                sym_data += _encode_submessage(4, rel_data)
            doc_data += _encode_submessage(3, sym_data)

        index_data += _encode_submessage(2, doc_data)

    path.write_bytes(index_data)
