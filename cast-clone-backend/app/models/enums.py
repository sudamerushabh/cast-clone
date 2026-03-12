"""Enumeration types for graph nodes, edges, confidence levels, and analysis status."""

from enum import Enum, StrEnum


class NodeKind(StrEnum):
    APPLICATION = "APPLICATION"
    MODULE = "MODULE"
    CLASS = "CLASS"
    INTERFACE = "INTERFACE"
    FUNCTION = "FUNCTION"
    FIELD = "FIELD"
    TABLE = "TABLE"
    COLUMN = "COLUMN"
    VIEW = "VIEW"
    STORED_PROCEDURE = "STORED_PROCEDURE"
    API_ENDPOINT = "API_ENDPOINT"
    ROUTE = "ROUTE"
    MESSAGE_TOPIC = "MESSAGE_TOPIC"
    CONFIG_FILE = "CONFIG_FILE"
    CONFIG_ENTRY = "CONFIG_ENTRY"
    LAYER = "LAYER"
    COMPONENT = "COMPONENT"
    COMMUNITY = "COMMUNITY"
    TRANSACTION = "TRANSACTION"


class EdgeKind(StrEnum):
    CALLS = "CALLS"
    INHERITS = "INHERITS"
    IMPLEMENTS = "IMPLEMENTS"
    DEPENDS_ON = "DEPENDS_ON"
    IMPORTS = "IMPORTS"
    CONTAINS = "CONTAINS"
    INJECTS = "INJECTS"
    READS = "READS"
    WRITES = "WRITES"
    MAPS_TO = "MAPS_TO"
    HAS_COLUMN = "HAS_COLUMN"
    REFERENCES = "REFERENCES"
    EXPOSES = "EXPOSES"
    HANDLES = "HANDLES"
    CALLS_API = "CALLS_API"
    RENDERS = "RENDERS"
    PRODUCES = "PRODUCES"
    CONSUMES = "CONSUMES"
    STARTS_AT = "STARTS_AT"
    ENDS_AT = "ENDS_AT"
    INCLUDES = "INCLUDES"
    PASSES_PROP = "PASSES_PROP"
    MANAGES = "MANAGES"
    MIDDLEWARE_CHAIN = "MIDDLEWARE_CHAIN"


class Confidence(int, Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3


class AnalysisStatus(StrEnum):
    CREATED = "created"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    FAILED = "failed"
