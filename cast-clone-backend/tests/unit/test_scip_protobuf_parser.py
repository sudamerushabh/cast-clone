"""Tests for SCIP protobuf parser.

Since SCIP indexers are external tools that may not be available,
all tests use synthetic data that mirrors the SCIP protobuf format.
"""

import pytest

from app.stages.scip.protobuf_parser import (
    SCIPDocument,
    SCIPIndex,
    SCIPOccurrence,
    SCIPRelationship,
    SCIPSymbolInfo,
    SymbolRole,
    build_scip_index_from_data,
    parse_scip_index,
)


class TestSymbolRole:
    def test_definition_flag(self):
        assert SymbolRole.is_definition(0x1)
        assert not SymbolRole.is_definition(0x0)
        assert not SymbolRole.is_definition(0x8)

    def test_reference_flag(self):
        # A reference has ReadAccess (0x8) but NOT Definition (0x1)
        assert SymbolRole.is_reference(0x8)
        assert SymbolRole.is_reference(0x0)  # no flags = reference (default)
        assert not SymbolRole.is_reference(0x1)  # definition is not a reference

    def test_implementation_check(self):
        # Implementation is detected via SCIPRelationship, not roles
        # But ReadAccess + Definition combo exists
        assert SymbolRole.is_definition(0x1 | 0x8)

    def test_write_access(self):
        assert SymbolRole.has_write_access(0x4)
        assert SymbolRole.has_write_access(0x1 | 0x4)
        assert not SymbolRole.has_write_access(0x8)


class TestSCIPOccurrence:
    def test_create_with_3_element_range(self):
        """3-element range: [line, start_col, end_col] (single line)."""
        occ = SCIPOccurrence(
            range=[10, 5, 20],
            symbol="maven . com/example 1.0 UserService#",
            symbol_roles=0x1,
        )
        assert occ.start_line == 10
        assert occ.start_col == 5
        assert occ.end_line == 10
        assert occ.end_col == 20
        assert occ.is_definition

    def test_create_with_4_element_range(self):
        """4-element range: [start_line, start_col, end_line, end_col] (multi-line)."""
        occ = SCIPOccurrence(
            range=[10, 5, 15, 20],
            symbol="maven . com/example 1.0 UserService#createUser().",
            symbol_roles=0x0,
        )
        assert occ.start_line == 10
        assert occ.start_col == 5
        assert occ.end_line == 15
        assert occ.end_col == 20
        assert not occ.is_definition

    def test_empty_range_defaults(self):
        occ = SCIPOccurrence(range=[], symbol="x", symbol_roles=0)
        assert occ.start_line == 0
        assert occ.start_col == 0
        assert occ.end_line == 0
        assert occ.end_col == 0


class TestSCIPSymbolInfo:
    def test_create(self):
        sym = SCIPSymbolInfo(
            symbol="maven . com/example 1.0 UserService#",
            documentation=["A service for managing users."],
            relationships=[],
        )
        assert sym.symbol == "maven . com/example 1.0 UserService#"
        assert "managing users" in sym.documentation[0]

    def test_with_relationships(self):
        rel = SCIPRelationship(
            symbol="maven . com/example 1.0 UserServiceInterface#",
            is_implementation=True,
            is_reference=False,
            is_type_definition=False,
        )
        sym = SCIPSymbolInfo(
            symbol="maven . com/example 1.0 UserServiceImpl#",
            documentation=[],
            relationships=[rel],
        )
        assert len(sym.relationships) == 1
        assert sym.relationships[0].is_implementation


class TestSCIPDocument:
    def test_create(self):
        doc = SCIPDocument(
            relative_path="src/main/java/com/example/UserService.java",
            occurrences=[
                SCIPOccurrence(
                    range=[10, 13, 24],
                    symbol="maven . com/example 1.0 UserService#",
                    symbol_roles=0x1,
                ),
            ],
            symbols=[
                SCIPSymbolInfo(
                    symbol="maven . com/example 1.0 UserService#",
                    documentation=["User service class."],
                    relationships=[],
                ),
            ],
        )
        assert doc.relative_path.endswith("UserService.java")
        assert len(doc.occurrences) == 1
        assert len(doc.symbols) == 1


class TestSCIPIndex:
    def test_create_empty(self):
        idx = SCIPIndex(
            documents=[],
            metadata_tool_name="test",
            metadata_tool_version="1.0",
        )
        assert len(idx.documents) == 0

    def test_create_with_documents(self):
        doc = SCIPDocument(
            relative_path="src/App.java",
            occurrences=[],
            symbols=[],
        )
        idx = SCIPIndex(
            documents=[doc],
            metadata_tool_name="scip-java",
            metadata_tool_version="0.8.0",
        )
        assert len(idx.documents) == 1
        assert idx.metadata_tool_name == "scip-java"


class TestBuildSCIPIndexFromData:
    """Test building SCIPIndex from structured data."""

    def test_build_from_dict(self):
        data = {
            "metadata": {"tool_info": {"name": "scip-java", "version": "0.8.0"}},
            "documents": [
                {
                    "relative_path": "src/main/java/com/example/UserService.java",
                    "occurrences": [
                        {
                            "range": [10, 13, 24],
                            "symbol": "maven . com/example 1.0 UserService#",
                            "symbol_roles": 1,
                        },
                        {
                            "range": [15, 8, 30],
                            "symbol": (
                                "maven . com/example 1.0 UserService#createUser()."
                            ),
                            "symbol_roles": 1,
                        },
                        {
                            "range": [20, 12, 35],
                            "symbol": "maven . com/example 1.0 UserRepository#save().",
                            "symbol_roles": 0,
                        },
                    ],
                    "symbols": [
                        {
                            "symbol": "maven . com/example 1.0 UserService#",
                            "documentation": ["Manages user lifecycle."],
                            "relationships": [],
                        },
                        {
                            "symbol": (
                                "maven . com/example 1.0 UserService#createUser()."
                            ),
                            "documentation": ["Creates a new user."],
                            "relationships": [],
                        },
                    ],
                },
            ],
        }
        idx = build_scip_index_from_data(data)
        assert len(idx.documents) == 1
        assert len(idx.documents[0].occurrences) == 3
        assert len(idx.documents[0].symbols) == 2
        assert idx.metadata_tool_name == "scip-java"

    def test_build_with_implementation_relationship(self):
        data = {
            "metadata": {"tool_info": {"name": "scip-java", "version": "0.8.0"}},
            "documents": [
                {
                    "relative_path": "src/UserServiceImpl.java",
                    "occurrences": [],
                    "symbols": [
                        {
                            "symbol": "maven . com/example 1.0 UserServiceImpl#",
                            "documentation": [],
                            "relationships": [
                                {
                                    "symbol": "maven . com/example 1.0 UserService#",
                                    "is_implementation": True,
                                    "is_reference": False,
                                    "is_type_definition": False,
                                },
                            ],
                        },
                    ],
                },
            ],
        }
        idx = build_scip_index_from_data(data)
        rels = idx.documents[0].symbols[0].relationships
        assert len(rels) == 1
        assert rels[0].is_implementation
        assert rels[0].symbol == "maven . com/example 1.0 UserService#"

    def test_build_empty(self):
        data = {
            "metadata": {"tool_info": {"name": "test", "version": "0.0"}},
            "documents": [],
        }
        idx = build_scip_index_from_data(data)
        assert len(idx.documents) == 0


class TestParseSCIPIndex:
    """Test parsing real protobuf bytes.

    We construct valid protobuf bytes manually to test the parser
    without depending on actual SCIP indexers.
    """

    def test_parse_nonexistent_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_scip_index(tmp_path / "nonexistent.scip")

    def test_parse_empty_file_returns_empty_index(self, tmp_path):
        scip_file = tmp_path / "index.scip"
        scip_file.write_bytes(b"")
        idx = parse_scip_index(scip_file)
        assert len(idx.documents) == 0

    def test_parse_valid_protobuf_file(self, tmp_path):
        """Build a minimal valid SCIP protobuf and parse it."""
        from app.stages.scip.protobuf_parser import write_test_scip_index

        scip_file = tmp_path / "index.scip"
        write_test_scip_index(
            scip_file,
            documents=[
                {
                    "relative_path": "src/App.java",
                    "occurrences": [
                        {
                            "range": [5, 10, 20],
                            "symbol": "test . App#",
                            "symbol_roles": 1,
                        },
                    ],
                    "symbols": [
                        {
                            "symbol": "test . App#",
                            "documentation": ["App class"],
                            "relationships": [],
                        },
                    ],
                },
            ],
            tool_name="test-indexer",
            tool_version="1.0.0",
        )
        idx = parse_scip_index(scip_file)
        assert len(idx.documents) == 1
        assert idx.documents[0].relative_path == "src/App.java"
        assert len(idx.documents[0].occurrences) == 1
        assert idx.documents[0].occurrences[0].symbol == "test . App#"
        assert idx.documents[0].occurrences[0].is_definition
        assert len(idx.documents[0].symbols) == 1
        assert idx.metadata_tool_name == "test-indexer"
