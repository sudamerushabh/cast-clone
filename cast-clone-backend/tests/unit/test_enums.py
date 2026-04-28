# tests/unit/test_enums.py
from app.models.enums import AnalysisStatus, Confidence, EdgeKind, NodeKind


def test_node_kind_has_core_types():
    assert NodeKind.CLASS.value == "CLASS"
    assert NodeKind.FUNCTION.value == "FUNCTION"
    assert NodeKind.MODULE.value == "MODULE"
    assert NodeKind.TABLE.value == "TABLE"
    assert NodeKind.API_ENDPOINT.value == "API_ENDPOINT"


def test_edge_kind_has_core_types():
    assert EdgeKind.CALLS.value == "CALLS"
    assert EdgeKind.CONTAINS.value == "CONTAINS"
    assert EdgeKind.INHERITS.value == "INHERITS"
    assert EdgeKind.IMPLEMENTS.value == "IMPLEMENTS"
    assert EdgeKind.INJECTS.value == "INJECTS"
    assert EdgeKind.READS.value == "READS"
    assert EdgeKind.WRITES.value == "WRITES"


def test_confidence_ordering():
    assert Confidence.HIGH.value > Confidence.MEDIUM.value > Confidence.LOW.value


def test_analysis_status_values():
    assert AnalysisStatus.CREATED.value == "created"
    assert AnalysisStatus.ANALYZING.value == "analyzing"
    assert AnalysisStatus.ANALYZED.value == "analyzed"
    assert AnalysisStatus.FAILED.value == "failed"


def test_edge_kind_includes_pydantic_endpoint_edges():
    assert EdgeKind.ACCEPTS.value == "ACCEPTS"
    assert EdgeKind.RETURNS.value == "RETURNS"
    assert EdgeKind("ACCEPTS") is EdgeKind.ACCEPTS
    assert EdgeKind("RETURNS") is EdgeKind.RETURNS
