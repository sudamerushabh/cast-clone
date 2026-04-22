# fastapi-todo fixture

Scratch-authored test fixture for CAST-clone Python M1 integration tests.
Stack: FastAPI + async SQLAlchemy 2.0 + Alembic + Pydantic v2.

Do **not** modify without updating the corresponding tests in
`tests/integration/test_python_m1_pipeline.py` — many assertions depend on
exact route paths, model names, and field identifiers.
