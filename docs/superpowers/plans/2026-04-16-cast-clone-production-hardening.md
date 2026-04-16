# CAST Clone Production Hardening Plan

See `/Users/rushabhsudame/cast-clone/docs/superpowers/plans/2026-04-16-cast-clone-production-hardening.md` in the
primary worktree for the canonical full plan. This file in the worktree mirrors that plan so subagents can
reference it from within the worktree.

**Goal:** Close the P0/P1 security, correctness, and robustness gaps identified in the 2026-04-16 deep-research audit.

**Jira epics:**
- CHAN-44 Security Baseline (P0)
- CHAN-45 Neo4j Writer Idempotency (P0)
- CHAN-46 Pipeline Robustness (P1)
- CHAN-47 Parser Correctness (P1)

**Execution order:** S1 → S2 → S3 (Security) → S4 → S5 → S6 (Writer) → S7 (Pipeline) → S8 (Parsers)

Full text of each task is included inline in the dispatching controller's subagent prompts; this document is a
stable anchor for commits and linking.
