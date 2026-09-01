"""SQLite persistence for Bridge's passage-semantic companion foundation.

The canonical record schema remains v1. Database migration v2 adds Stage 4
runtime identity, revision, invalidation, reference, and migration metadata.
The database never owns or rewrites Scripture or native translationCore data.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterator
import uuid

from .passage_semantic_models import (
    ActorType,
    Cardinality,
    CorrectionProposal,
    DependencyRelation,
    EvidenceRecord,
    Exportability,
    LifecycleStatus,
    PassageRecord,
    PolicyBinding,
    QaDisposition,
    QaFinding,
    ReviewStatus,
    SCHEMA_ID,
    SCHEMA_VERSION,
    SemanticCoverageAccount,
    SemanticRelationship,
    SemanticUnit,
    SemanticRelation,
    TokenInstance,
    TokenLineage,
    TokenLayer,
    to_wire,
)


DATABASE_SCHEMA_VERSION = 3


class FoundationError(RuntimeError):
    pass


class FoundationValidationError(FoundationError):
    pass


class FoundationConflict(FoundationError):
    pass


_MIGRATION_V1 = r"""
CREATE TABLE policy_bindings (
    id TEXT PRIMARY KEY,
    confidence_policy_version TEXT NOT NULL,
    calibration_version TEXT NOT NULL,
    audit_policy_version TEXT NOT NULL,
    UNIQUE(confidence_policy_version, calibration_version, audit_policy_version)
);

CREATE TABLE token_lineages (
    id TEXT PRIMARY KEY,
    side TEXT NOT NULL CHECK(side IN ('SOURCE','TARGET')),
    project_id TEXT,
    logical_resource_id TEXT NOT NULL,
    book TEXT NOT NULL,
    canonical_reference_scope_json TEXT NOT NULL,
    token_layer TEXT NOT NULL CHECK(token_layer IN ('ORTHOGRAPHIC','SUBTOKEN','MORPHEME')),
    upstream_identity TEXT,
    provenance TEXT NOT NULL,
    review_status TEXT NOT NULL CHECK(review_status IN ('UNREVIEWED','AI_PROPOSED','HUMAN_APPROVED','HUMAN_REJECTED','HUMAN_MODIFIED','NEEDS_DISCUSSION')),
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('ACTIVE','INACTIVE','STALE','SUPERSEDED','QUARANTINED')),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    payload_json TEXT NOT NULL
);

CREATE TABLE token_instances (
    id TEXT PRIMARY KEY,
    lineage_id TEXT NOT NULL REFERENCES token_lineages(id),
    side TEXT NOT NULL CHECK(side IN ('SOURCE','TARGET')),
    token_layer TEXT NOT NULL CHECK(token_layer IN ('ORTHOGRAPHIC','SUBTOKEN','MORPHEME')),
    parent_instance_id TEXT REFERENCES token_instances(id),
    text_revision TEXT,
    instance_fingerprint TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(lineage_id, instance_fingerprint)
);

CREATE TABLE passage_records (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book TEXT NOT NULL,
    target_revision TEXT NOT NULL,
    target_content_hash TEXT NOT NULL,
    policy_binding_id TEXT NOT NULL REFERENCES policy_bindings(id),
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('ACTIVE','INACTIVE','STALE','SUPERSEDED','QUARANTINED')),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    payload_json TEXT NOT NULL
);

CREATE TABLE evidence_records (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('SOURCE_TEXT','TARGET_TEXT','MORPHOLOGY','TRANSLATION_NOTE','TRANSLATION_WORD','TRANSLATION_WORD_LIST','VERSIFICATION','STRUCTURE','HUMAN_NOTE','AI_RATIONALE')),
    resource_id TEXT NOT NULL,
    resource_version TEXT,
    resource_hash TEXT NOT NULL,
    occurrence_id TEXT,
    validation_status TEXT NOT NULL CHECK(validation_status IN ('NOT_CHECKED','CONSISTENT','SUPPORTING','CONFLICTING','NOT_APPLICABLE')),
    policy_binding_id TEXT NOT NULL REFERENCES policy_bindings(id),
    review_status TEXT NOT NULL CHECK(review_status IN ('UNREVIEWED','AI_PROPOSED','HUMAN_APPROVED','HUMAN_REJECTED','HUMAN_MODIFIED','NEEDS_DISCUSSION')),
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('ACTIVE','INACTIVE','STALE','SUPERSEDED','QUARANTINED')),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    payload_json TEXT NOT NULL
);

CREATE TABLE semantic_units (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('SOURCE','TARGET')),
    kind TEXT NOT NULL CHECK(kind IN ('LEXICAL','MORPHOLOGICAL','NEGATION','QUANTIFIER','PARTICIPANT','REFERENT','PREDICATE','SEMANTIC_ROLE','CLAUSE','CLAUSE_RELATION','DISCOURSE_RELATION','IMPLICIT_GRAMMATICAL','IDIOM','CONSTRUCTION','TEMPORAL','SPATIAL')),
    audit_owner_unit_id TEXT NOT NULL,
    audit_eligibility TEXT NOT NULL CHECK(audit_eligibility IN ('ELIGIBLE','CONDITIONAL','AGGREGATE_ONLY','EXCLUDED','REVIEW_ONLY')),
    semantic_obligation TEXT NOT NULL CHECK(semantic_obligation IN ('REQUIRED','CONTEXT_DEPENDENT','GRAMMATICAL','DERIVED','NON_OBLIGATORY','UNCERTAIN')),
    accounting_role TEXT NOT NULL CHECK(accounting_role IN ('PRIMARY','COMPONENT','AGGREGATE','EVIDENCE_ONLY')),
    coverage_dimension TEXT NOT NULL CHECK(coverage_dimension IN ('LEXICAL_CONTENT','POLARITY','QUANTITY','PARTICIPANT','REFERENT','PREDICATION','TEMPORAL_ASPECTUAL','SPATIAL_RELATION','CLAUSE_RELATION','DISCOURSE_RELATION','OTHER')),
    semantic_fingerprint TEXT NOT NULL,
    review_status TEXT NOT NULL CHECK(review_status IN ('UNREVIEWED','AI_PROPOSED','HUMAN_APPROVED','HUMAN_REJECTED','HUMAN_MODIFIED','NEEDS_DISCUSSION')),
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('ACTIVE','INACTIVE','STALE','SUPERSEDED','QUARANTINED')),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    payload_json TEXT NOT NULL
);

CREATE TABLE semantic_unit_dependencies (
    parent_unit_id TEXT NOT NULL REFERENCES semantic_units(id),
    child_unit_id TEXT NOT NULL REFERENCES semantic_units(id),
    relation TEXT NOT NULL CHECK(relation IN ('CONTAINS','DEPENDS_ON','DERIVED_FROM','REFINES')),
    payload_json TEXT NOT NULL,
    PRIMARY KEY(parent_unit_id, child_unit_id, relation),
    CHECK(parent_unit_id <> child_unit_id)
);

CREATE TABLE semantic_unit_relations (
    left_unit_id TEXT NOT NULL REFERENCES semantic_units(id),
    right_unit_id TEXT NOT NULL REFERENCES semantic_units(id),
    relation TEXT NOT NULL CHECK(relation IN ('COREFERS_WITH','COEXTENSIVE_WITH','MODIFIES','NEGATES','QUANTIFIES','PARTICIPANT_OF','ARGUMENT_OF','SEMANTICALLY_RELATED')),
    payload_json TEXT NOT NULL,
    PRIMARY KEY(left_unit_id, right_unit_id, relation)
);

CREATE TABLE semantic_relationships (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    review_status TEXT NOT NULL CHECK(review_status IN ('UNREVIEWED','AI_PROPOSED','HUMAN_APPROVED','HUMAN_REJECTED','HUMAN_MODIFIED','NEEDS_DISCUSSION')),
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('ACTIVE','INACTIVE','STALE','SUPERSEDED','QUARANTINED')),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    payload_json TEXT NOT NULL
);

CREATE TABLE exportability_records (
    id TEXT PRIMARY KEY,
    relationship_id TEXT NOT NULL REFERENCES semantic_relationships(id),
    format TEXT NOT NULL CHECK(format IN ('BRIDGE','CLEAN_USFM','TRANSLATIONCORE_ALIGNED_USFM','SCRIPTURE_BURRITO')),
    level TEXT NOT NULL CHECK(level IN ('FULL','PARTIAL','NOT_REPRESENTABLE','TEXT_ONLY')),
    policy_binding_id TEXT NOT NULL REFERENCES policy_bindings(id),
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('ACTIVE','INACTIVE','STALE','SUPERSEDED','QUARANTINED')),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    payload_json TEXT NOT NULL
);
CREATE UNIQUE INDEX uq_active_exportability
ON exportability_records(relationship_id, format)
WHERE lifecycle_status = 'ACTIVE';

CREATE TABLE qa_findings (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    qa_disposition TEXT NOT NULL CHECK(qa_disposition IN ('UNRESOLVED','CONFIRMED_TRANSLATION_ERROR','ACCEPTABLE_TRANSLATION','FALSE_POSITIVE','NEEDS_DISCUSSION','CORRECTED')),
    policy_binding_id TEXT NOT NULL REFERENCES policy_bindings(id),
    review_status TEXT NOT NULL CHECK(review_status IN ('UNREVIEWED','AI_PROPOSED','HUMAN_APPROVED','HUMAN_REJECTED','HUMAN_MODIFIED','NEEDS_DISCUSSION')),
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('ACTIVE','INACTIVE','STALE','SUPERSEDED','QUARANTINED')),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    payload_json TEXT NOT NULL
);

CREATE TABLE coverage_accounts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    passage_id TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('SOURCE_COVERAGE','TARGET_SUPPORT')),
    audit_owner_unit_id TEXT NOT NULL REFERENCES semantic_units(id),
    coverage_dimension TEXT NOT NULL CHECK(coverage_dimension IN ('LEXICAL_CONTENT','POLARITY','QUANTITY','PARTICIPANT','REFERENT','PREDICATION','TEMPORAL_ASPECTUAL','SPATIAL_RELATION','CLAUSE_RELATION','DISCOURSE_RELATION','OTHER')),
    semantic_fingerprint TEXT NOT NULL,
    finding_id TEXT REFERENCES qa_findings(id),
    review_status TEXT NOT NULL CHECK(review_status IN ('UNREVIEWED','AI_PROPOSED','HUMAN_APPROVED','HUMAN_REJECTED','HUMAN_MODIFIED','NEEDS_DISCUSSION')),
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('ACTIVE','INACTIVE','STALE','SUPERSEDED','QUARANTINED')),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    payload_json TEXT NOT NULL
);
CREATE UNIQUE INDEX uq_active_coverage_account
ON coverage_accounts(project_id, passage_id, direction, audit_owner_unit_id, coverage_dimension, semantic_fingerprint)
WHERE lifecycle_status = 'ACTIVE';

CREATE TABLE lexical_solutions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    source_layer TEXT CHECK(source_layer IN ('ORTHOGRAPHIC','SUBTOKEN','MORPHEME') OR source_layer IS NULL),
    target_layer TEXT CHECK(target_layer IN ('ORTHOGRAPHIC','SUBTOKEN','MORPHEME') OR target_layer IS NULL),
    authoritative INTEGER NOT NULL CHECK(authoritative IN (0,1)),
    policy_binding_id TEXT NOT NULL REFERENCES policy_bindings(id),
    review_status TEXT NOT NULL CHECK(review_status IN ('UNREVIEWED','AI_PROPOSED','HUMAN_APPROVED','HUMAN_REJECTED','HUMAN_MODIFIED','NEEDS_DISCUSSION')),
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('ACTIVE','INACTIVE','STALE','SUPERSEDED','QUARANTINED')),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    payload_json TEXT NOT NULL
);
CREATE UNIQUE INDEX uq_authoritative_active_lexical_solution
ON lexical_solutions(project_id, scope_key, profile_id, IFNULL(source_layer,'<NULL>'), IFNULL(target_layer,'<NULL>'))
WHERE authoritative = 1 AND lifecycle_status = 'ACTIVE';

CREATE TABLE lexical_groups (
    id TEXT PRIMARY KEY,
    solution_id TEXT NOT NULL REFERENCES lexical_solutions(id),
    cardinality TEXT NOT NULL CHECK(cardinality IN ('ONE_TO_ONE','ONE_TO_MANY','MANY_TO_ONE','MANY_TO_MANY','SOURCE_TO_NULL','NULL_TO_TARGET')),
    source_layer TEXT CHECK(source_layer IN ('ORTHOGRAPHIC','SUBTOKEN','MORPHEME') OR source_layer IS NULL),
    target_layer TEXT CHECK(target_layer IN ('ORTHOGRAPHIC','SUBTOKEN','MORPHEME') OR target_layer IS NULL),
    source_token_ids_json TEXT NOT NULL,
    target_token_ids_json TEXT NOT NULL,
    alignment_family_id TEXT NOT NULL,
    refines_group_id TEXT REFERENCES lexical_groups(id),
    review_status TEXT NOT NULL CHECK(review_status IN ('UNREVIEWED','AI_PROPOSED','HUMAN_APPROVED','HUMAN_REJECTED','HUMAN_MODIFIED','NEEDS_DISCUSSION')),
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('ACTIVE','INACTIVE','STALE','SUPERSEDED','QUARANTINED')),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    payload_json TEXT NOT NULL,
    CHECK(
      (cardinality = 'SOURCE_TO_NULL' AND source_layer IS NOT NULL AND target_layer IS NULL)
      OR (cardinality = 'NULL_TO_TARGET' AND source_layer IS NULL AND target_layer IS NOT NULL)
      OR (cardinality IN ('ONE_TO_ONE','ONE_TO_MANY','MANY_TO_ONE','MANY_TO_MANY') AND source_layer IS NOT NULL AND target_layer IS NOT NULL)
    )
);

CREATE TABLE active_lexical_membership (
    lexical_solution_id TEXT NOT NULL REFERENCES lexical_solutions(id),
    token_side TEXT NOT NULL CHECK(token_side IN ('SOURCE','TARGET')),
    token_layer TEXT NOT NULL CHECK(token_layer IN ('ORTHOGRAPHIC','SUBTOKEN','MORPHEME')),
    token_instance_id TEXT NOT NULL REFERENCES token_instances(id),
    lexical_group_id TEXT NOT NULL REFERENCES lexical_groups(id),
    PRIMARY KEY(lexical_solution_id, token_side, token_layer, token_instance_id)
);

CREATE TABLE correction_proposals (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    qa_finding_id TEXT NOT NULL REFERENCES qa_findings(id),
    current_target_revision TEXT NOT NULL,
    applied_target_revision TEXT,
    policy_binding_id TEXT NOT NULL REFERENCES policy_bindings(id),
    review_status TEXT NOT NULL CHECK(review_status IN ('UNREVIEWED','AI_PROPOSED','HUMAN_APPROVED','HUMAN_REJECTED','HUMAN_MODIFIED','NEEDS_DISCUSSION')),
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('ACTIVE','INACTIVE','STALE','SUPERSEDED','QUARANTINED')),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    payload_json TEXT NOT NULL
);

CREATE TABLE review_records (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    previous_review_status TEXT,
    new_review_status TEXT NOT NULL CHECK(new_review_status IN ('UNREVIEWED','AI_PROPOSED','HUMAN_APPROVED','HUMAN_REJECTED','HUMAN_MODIFIED','NEEDS_DISCUSSION')),
    previous_lifecycle_status TEXT,
    new_lifecycle_status TEXT NOT NULL CHECK(new_lifecycle_status IN ('ACTIVE','INACTIVE','STALE','SUPERSEDED','QUARANTINED')),
    previous_qa_disposition TEXT,
    new_qa_disposition TEXT,
    actor_type TEXT NOT NULL CHECK(actor_type IN ('HUMAN','AI','SYSTEM','MIGRATION')),
    actor_id TEXT NOT NULL,
    note TEXT NOT NULL,
    base_revision INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE record_dependencies (
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    depends_on_type TEXT NOT NULL,
    depends_on_id TEXT NOT NULL,
    PRIMARY KEY(record_type, record_id, depends_on_type, depends_on_id)
);

CREATE TABLE migration_quarantine (
    id TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    source_identity TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


_MIGRATION_V2 = r"""
CREATE TABLE project_metadata (
    project_id TEXT PRIMARY KEY,
    identity_fingerprint TEXT NOT NULL,
    book TEXT NOT NULL,
    target_language_id TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    path_history_json TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('ACTIVE','INACTIVE','STALE','SUPERSEDED','QUARANTINED')),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    payload_json TEXT NOT NULL
);

CREATE TABLE current_target_revisions (
    project_id TEXT NOT NULL REFERENCES project_metadata(project_id),
    book TEXT NOT NULL,
    displayed_reference TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    text_revision TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(project_id, book, displayed_reference)
);

CREATE TABLE pending_invalidations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project_metadata(project_id),
    book TEXT NOT NULL,
    displayed_reference TEXT NOT NULL,
    previous_text_hash TEXT NOT NULL,
    expected_text_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('PREPARED','APPLIED','CANCELLED','FAILED')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX ix_pending_invalidations_state
ON pending_invalidations(project_id, state, created_at);

CREATE TABLE source_resource_locks (
    project_id TEXT NOT NULL REFERENCES project_metadata(project_id),
    book TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    resource_version TEXT NOT NULL,
    resource_hash TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('ACTIVE','INACTIVE','STALE','SUPERSEDED','QUARANTINED')),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    updated_at TEXT NOT NULL,
    PRIMARY KEY(project_id, book)
);

CREATE TABLE passage_reference_records (
    passage_id TEXT NOT NULL REFERENCES passage_records(id),
    displayed_reference TEXT NOT NULL,
    project_versification TEXT NOT NULL,
    canonical_references_json TEXT NOT NULL,
    mapping_kind TEXT NOT NULL CHECK(mapping_kind IN ('SAME','MAPPED','MERGE','SPLIT','PSALM_TITLE','VERSE_BRIDGE','CHAPTER_SHIFT','AMBIGUOUS_SEGMENT')),
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    PRIMARY KEY(passage_id, displayed_reference)
);

CREATE TABLE token_lineage_candidates (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project_metadata(project_id),
    old_instance_id TEXT NOT NULL REFERENCES token_instances(id),
    new_instance_id TEXT NOT NULL REFERENCES token_instances(id),
    relation TEXT NOT NULL CHECK(relation IN ('SAME_LINEAGE','POSSIBLE_SUCCESSOR','SPLIT_FROM','MERGED_FROM','NO_CORRESPONDENCE')),
    confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
    reason_code TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('ACTIVE','INACTIVE','STALE','SUPERSEDED','QUARANTINED')),
    payload_json TEXT NOT NULL,
    UNIQUE(old_instance_id, new_instance_id, relation)
);

CREATE TABLE migration_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project_metadata(project_id),
    source_path TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    source_schema TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('IMPORTED','QUARANTINED','SKIPPED','FAILED')),
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    report_json TEXT NOT NULL,
    UNIQUE(project_id, source_path, source_hash)
);

CREATE TABLE runtime_diagnostics (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    code TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('INFO','WARNING','ERROR')),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
"""


_MIGRATION_V3 = r"""
CREATE TABLE source_inventory_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project_metadata(project_id),
    book TEXT NOT NULL,
    range_key TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    source_resource_id TEXT NOT NULL,
    source_resource_version TEXT NOT NULL,
    source_resource_hash TEXT NOT NULL,
    audit_policy_version TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('ACTIVE','INACTIVE','STALE','SUPERSEDED','QUARANTINED')),
    diagnostics_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, book, range_key, fingerprint)
);
CREATE INDEX ix_source_inventory_range
ON source_inventory_runs(project_id, book, range_key, lifecycle_status);

CREATE TABLE source_inventory_tokens (
    inventory_id TEXT NOT NULL REFERENCES source_inventory_runs(id) ON DELETE CASCADE,
    token_instance_id TEXT NOT NULL REFERENCES token_instances(id),
    language_id TEXT NOT NULL,
    upstream_identity TEXT NOT NULL,
    PRIMARY KEY(inventory_id, token_instance_id)
);

CREATE TABLE source_inventory_units (
    inventory_id TEXT NOT NULL REFERENCES source_inventory_runs(id) ON DELETE CASCADE,
    semantic_unit_id TEXT NOT NULL REFERENCES semantic_units(id),
    PRIMARY KEY(inventory_id, semantic_unit_id)
);

CREATE TABLE source_inventory_evidence (
    inventory_id TEXT NOT NULL REFERENCES source_inventory_runs(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES evidence_records(id),
    PRIMARY KEY(inventory_id, evidence_id)
);
"""


class FoundationRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.read_only = False
        self._migrate()
        self.recovery_check()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = FULL")
        conn.execute("PRAGMA journal_mode = WAL")
        if self.read_only:
            conn.execute("PRAGMA query_only = ON")
        if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            conn.close()
            raise FoundationError("SQLite foreign-key enforcement could not be enabled")
        try:
            yield conn
        finally:
            conn.close()

    def _migrate(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, schema_id TEXT NOT NULL, applied_at TEXT NOT NULL)")
            current = conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[0]
            if current > DATABASE_SCHEMA_VERSION:
                raise FoundationError(
                    f"Companion schema {current} is newer than supported v{DATABASE_SCHEMA_VERSION}"
                )
            if current < 1:
                self._apply_migration(conn, 1, _MIGRATION_V1)
                current = 1
            if current < 2:
                self._backup_before_migration(conn, current, 2)
                self._apply_migration(conn, 2, _MIGRATION_V2)
                current = 2
            if current < 3:
                self._backup_before_migration(conn, current, 3)
                self._apply_migration(conn, 3, _MIGRATION_V3)
        self._ensure_policy(PolicyBinding.foundation_v1())

    def _backup_before_migration(
        self, conn: sqlite3.Connection, current: int, target: int,
    ) -> None:
        """Create a consistent, inspectable backup before upgrading an existing DB."""
        if current <= 0 or not self.path.is_file():
            return
        root = self.path.parent / "backups"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        directory = root / f"pre-schema-v{target}-{stamp}"
        directory.mkdir(parents=True, exist_ok=False)
        backup_db = directory / "bridge-semantic-v1.sqlite3"
        destination = sqlite3.connect(str(backup_db))
        try:
            conn.backup(destination)
        finally:
            destination.close()
        digest = hashlib.sha256(backup_db.read_bytes()).hexdigest()
        manifest = {
            "reason": f"automatic backup before database migration v{current} to v{target}",
            "schemaId": SCHEMA_ID, "schemaVersion": current,
            "source": str(self.path), "sourceDatabase": str(self.path),
            "databaseSchemaVersion": current,
            "targetDatabaseSchemaVersion": target, "sha256": digest, "createdAt": self._now(),
        }
        (directory / "backup-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )

    def _apply_migration(self, conn: sqlite3.Connection, version: int, script: str) -> None:
        schema_id = SCHEMA_ID.replace("'", "''")
        applied_at = self._now().replace("'", "''")
        conn.executescript(
            "BEGIN IMMEDIATE;\n"
            + script
            + f"\nINSERT INTO schema_migrations(version,schema_id,applied_at) "
              f"VALUES({version},'{schema_id}','{applied_at}');\n"
            + f"PRAGMA user_version = {version};\nCOMMIT;"
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _policy_id(policy: PolicyBinding) -> str:
        raw = "\u241f".join((policy.confidence_policy_version, policy.calibration_version, policy.audit_policy_version))
        return "policy-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _ensure_policy(self, policy: PolicyBinding) -> str:
        policy_id = self._policy_id(policy)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO policy_bindings VALUES(?,?,?,?)",
                (policy_id, policy.confidence_policy_version, policy.calibration_version, policy.audit_policy_version),
            )
            conn.commit()
        return policy_id

    def schema_version(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[0])

    def bind_project_metadata(
        self, *, project_id: str, identity_fingerprint: str, book: str,
        target_language_id: str, resource_id: str, path: str,
    ) -> dict[str, Any]:
        now = self._now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute("SELECT * FROM project_metadata").fetchall()
            if rows and all(row["project_id"] != project_id for row in rows):
                raise FoundationConflict(
                    "Companion database belongs to a different Bridge project; refusing to merge identities"
                )
            row = next((item for item in rows if item["project_id"] == project_id), None)
            if row is None:
                paths = [path]
                payload = {
                    "projectId": project_id, "identityFingerprint": identity_fingerprint,
                    "book": book, "targetLanguageId": target_language_id,
                    "resourceId": resource_id, "pathHistory": paths,
                    "createdAt": now, "updatedAt": now,
                    "lifecycleStatus": "ACTIVE", "revision": 1,
                }
                conn.execute(
                    "INSERT INTO project_metadata VALUES(?,?,?,?,?,?,?,?,?)",
                    (project_id, identity_fingerprint, book, target_language_id, resource_id,
                     json.dumps(paths, ensure_ascii=False), "ACTIVE", 1,
                     json.dumps(payload, ensure_ascii=False)),
                )
            else:
                if row["identity_fingerprint"] != identity_fingerprint:
                    raise FoundationConflict(
                        "Project identity metadata conflicts with this companion database"
                    )
                paths = json.loads(row["path_history_json"])
                path_added = path not in paths
                if path not in paths:
                    paths.append(path)
                metadata_changed = (
                    row["book"] != book
                    or row["target_language_id"] != target_language_id
                    or row["resource_id"] != resource_id
                )
                if path_added or metadata_changed:
                    payload = json.loads(row["payload_json"])
                    payload.update({
                        "book": book, "targetLanguageId": target_language_id,
                        "resourceId": resource_id, "pathHistory": paths,
                        "updatedAt": now, "revision": int(row["revision"]) + 1,
                    })
                    conn.execute(
                        "UPDATE project_metadata SET book=?,target_language_id=?,resource_id=?,"
                        "path_history_json=?,revision=revision+1,payload_json=? WHERE project_id=?",
                        (book, target_language_id, resource_id, json.dumps(paths, ensure_ascii=False),
                         json.dumps(payload, ensure_ascii=False), project_id),
                    )
            conn.commit()
        return self.project_metadata(project_id)

    def project_metadata(self, project_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM project_metadata WHERE project_id=?", (project_id,)
            ).fetchone()
        if row is None:
            raise FoundationValidationError(f"Unknown semantic project identity: {project_id}")
        return json.loads(row[0])

    def current_target_revision(
        self, project_id: str, book: str, displayed_reference: str,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM current_target_revisions WHERE project_id=? AND book=? "
                "AND displayed_reference=?", (project_id, book, displayed_reference),
            ).fetchone()
        if row is None:
            return None
        return {
            "projectId": row["project_id"], "book": row["book"],
            "displayedReference": row["displayed_reference"], "textHash": row["text_hash"],
            "textRevision": row["text_revision"], "updatedAt": row["updated_at"],
        }

    def current_target_revisions(self, project_id: str, book: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM current_target_revisions WHERE project_id=? AND book=? "
                "ORDER BY displayed_reference", (project_id, book),
            ).fetchall()
        return [{
            "projectId": row["project_id"], "book": row["book"],
            "displayedReference": row["displayed_reference"], "textHash": row["text_hash"],
            "textRevision": row["text_revision"], "updatedAt": row["updated_at"],
        } for row in rows]

    def establish_target_revision(
        self, *, project_id: str, book: str, displayed_reference: str,
        text_hash: str, text_revision: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO current_target_revisions VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(project_id,book,displayed_reference) DO UPDATE SET "
                "text_hash=excluded.text_hash,text_revision=excluded.text_revision,updated_at=excluded.updated_at",
                (project_id, book, displayed_reference, text_hash, text_revision, self._now()),
            )
            conn.commit()

    def prepare_target_invalidation(
        self, *, project_id: str, book: str, displayed_reference: str,
        previous_text_hash: str, expected_text_hash: str,
    ) -> str:
        intent_id = str(uuid.uuid4())
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO pending_invalidations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (intent_id, project_id, book, displayed_reference, previous_text_hash,
                 expected_text_hash, "PREPARED", 0, "", now, now),
            )
            conn.commit()
        return intent_id

    def cancel_target_invalidation(self, intent_id: str, reason: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE pending_invalidations SET state='CANCELLED',last_error=?,updated_at=? "
                "WHERE id=? AND state='PREPARED'", (reason, self._now(), intent_id),
            )
            conn.commit()

    def apply_target_invalidation(
        self, intent_id: str, *, actual_text_hash: str, text_revision: str,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM pending_invalidations WHERE id=?", (intent_id,)).fetchone()
            if row is None:
                raise FoundationValidationError(f"Unknown pending invalidation: {intent_id}")
            if row["state"] == "APPLIED":
                return {"intentId": intent_id, "state": "APPLIED", "staled": 0}
            if row["state"] != "PREPARED":
                raise FoundationConflict(f"Pending invalidation is already {row['state']}")
            current = conn.execute(
                "SELECT text_hash FROM current_target_revisions WHERE project_id=? AND book=? "
                "AND displayed_reference=?",
                (row["project_id"], row["book"], row["displayed_reference"]),
            ).fetchone()
            if current is not None and current["text_hash"] != row["previous_text_hash"]:
                conn.execute(
                    "UPDATE pending_invalidations SET state='FAILED',attempt_count=attempt_count+1,"
                    "last_error=?,updated_at=? WHERE id=?",
                    ("Target revision changed after invalidation intent was prepared", self._now(), intent_id),
                )
                conn.commit()
                raise FoundationConflict(
                    "Target revision changed after invalidation intent was prepared"
                )
            if actual_text_hash != row["expected_text_hash"]:
                conn.execute(
                    "UPDATE pending_invalidations SET state='FAILED',attempt_count=attempt_count+1,"
                    "last_error=?,updated_at=? WHERE id=?",
                    ("Current target hash does not match the prepared edit", self._now(), intent_id),
                )
                conn.commit()
                raise FoundationConflict("Current target hash does not match the prepared edit")
            dependency_id = self.target_dependency_id(
                row["project_id"], row["book"], row["displayed_reference"]
            )
            staled = self._stale_generic_dependencies(
                conn, "TARGET_REFERENCE", dependency_id
            )
            conn.execute(
                "INSERT INTO current_target_revisions VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(project_id,book,displayed_reference) DO UPDATE SET "
                "text_hash=excluded.text_hash,text_revision=excluded.text_revision,updated_at=excluded.updated_at",
                (row["project_id"], row["book"], row["displayed_reference"],
                 actual_text_hash, text_revision, self._now()),
            )
            conn.execute(
                "UPDATE pending_invalidations SET state='APPLIED',attempt_count=attempt_count+1,"
                "last_error='',updated_at=? WHERE id=?", (self._now(), intent_id),
            )
            conn.commit()
        return {"intentId": intent_id, "state": "APPLIED", "staled": staled}

    def pending_invalidations(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pending_invalidations WHERE project_id=? AND state='PREPARED' "
                "ORDER BY created_at,id", (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def target_dependency_id(project_id: str, book: str, displayed_reference: str) -> str:
        return "\u241f".join((project_id, book.upper(), displayed_reference))

    @staticmethod
    def source_dependency_id(project_id: str, book: str, resource_hash: str) -> str:
        return "\u241f".join((project_id, book.upper(), resource_hash))

    def save_passage_references(
        self, passage_id: str, references: list[dict[str, Any]],
    ) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM passage_reference_records WHERE passage_id=?", (passage_id,))
            for ordinal, reference in enumerate(references):
                conn.execute(
                    "INSERT INTO passage_reference_records VALUES(?,?,?,?,?,?)",
                    (passage_id, reference["displayedReference"], reference["projectVersification"],
                     json.dumps(reference["canonicalReferences"], ensure_ascii=False),
                     reference["mappingKind"], ordinal),
                )
            conn.commit()

    def passage_references(self, passage_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM passage_reference_records WHERE passage_id=? ORDER BY ordinal",
                (passage_id,),
            ).fetchall()
        return [{
            "displayedReference": row["displayed_reference"],
            "projectVersification": row["project_versification"],
            "canonicalReferences": json.loads(row["canonical_references_json"]),
            "mappingKind": row["mapping_kind"],
        } for row in rows]

    def save_token_lineage(self, lineage: TokenLineage) -> None:
        payload = to_wire(lineage)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO token_lineages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (lineage.id, lineage.side.value, lineage.project_id, lineage.logical_resource_id, lineage.book,
                 json.dumps(list(lineage.canonical_reference_scope)), lineage.token_layer.value,
                 lineage.upstream_identity, lineage.provenance.value, lineage.review_status.value,
                 lineage.lifecycle_status.value, lineage.revision, json.dumps(payload, ensure_ascii=False)),
            )
            conn.commit()

    def save_token_instance(self, instance: TokenInstance) -> None:
        payload = to_wire(instance)
        with self._connect() as conn:
            try:
                lineage = conn.execute(
                    "SELECT side,token_layer FROM token_lineages WHERE id=?", (instance.lineage_id,)
                ).fetchone()
                if lineage is None:
                    raise FoundationValidationError(f"Unknown token lineage: {instance.lineage_id}")
                if lineage["side"] != instance.side.value or lineage["token_layer"] != instance.token_layer.value:
                    raise FoundationValidationError("Token instance side/layer must match its lineage")
                if instance.parent_instance_id is not None:
                    parent = conn.execute(
                        "SELECT side FROM token_instances WHERE id=?", (instance.parent_instance_id,)
                    ).fetchone()
                    if parent is None or parent["side"] != instance.side.value:
                        raise FoundationValidationError("Token parent must exist on the same side")
                conn.execute(
                    "INSERT INTO token_instances VALUES(?,?,?,?,?,?,?,?)",
                    (instance.id, instance.lineage_id, instance.side.value, instance.token_layer.value,
                     instance.parent_instance_id, instance.text_revision, instance.instance_fingerprint,
                     json.dumps(payload, ensure_ascii=False),),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise FoundationValidationError(f"Invalid token instance: {exc}") from exc

    def token_instance(self, instance_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM token_instances WHERE id=?", (instance_id,)).fetchone()
        if row is None:
            raise FoundationValidationError(f"Unknown token instance: {instance_id}")
        return json.loads(row[0])

    def token_instances_for_reference(
        self, *, project_id: str, book: str, displayed_reference: str,
        text_revision: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM token_instances WHERE side='TARGET' "
                "AND (? IS NULL OR text_revision=?) ORDER BY id",
                (text_revision, text_revision),
            ).fetchall()
        result = []
        for row in rows:
            payload = json.loads(row[0])
            if (
                payload.get("projectId") == project_id
                and str(payload.get("book") or "").upper() == book.upper()
                and payload.get("displayedReference") == displayed_reference
            ):
                result.append(payload)
        return sorted(result, key=lambda item: int(item.get("index") or 0))

    def save_token_lineage_candidate(
        self, *, candidate_id: str, project_id: str, old_instance_id: str,
        new_instance_id: str, relation: str, confidence: float, reason_code: str,
    ) -> None:
        payload = {
            "id": candidate_id, "projectId": project_id,
            "oldInstanceId": old_instance_id, "newInstanceId": new_instance_id,
            "relation": relation, "confidence": confidence, "reasonCode": reason_code,
            "lifecycleStatus": "INACTIVE",
        }
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO token_lineage_candidates VALUES(?,?,?,?,?,?,?,?,?)",
                (candidate_id, project_id, old_instance_id, new_instance_id, relation,
                 confidence, reason_code, "INACTIVE", json.dumps(payload, ensure_ascii=False)),
            )
            conn.commit()

    def token_lineage_candidates(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM token_lineage_candidates WHERE project_id=? ORDER BY id",
                (project_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    @staticmethod
    def target_content_hash(target_text_by_displayed_reference: dict[str, str]) -> str:
        canonical = json.dumps(
            target_text_by_displayed_reference,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def save_passage_record(self, passage: PassageRecord) -> None:
        expected_hash = self.target_content_hash(passage.target_text_by_displayed_reference)
        if passage.target_content_hash != expected_hash:
            raise FoundationValidationError("Passage target-content hash does not match current target text")
        policy_id = self._ensure_policy(passage.policy_binding)
        payload = to_wire(passage)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO passage_records VALUES(?,?,?,?,?,?,?,?,?)",
                (passage.id, passage.project_id, passage.book, passage.target_revision,
                 passage.target_content_hash, policy_id, passage.lifecycle_status.value, passage.revision,
                 json.dumps(payload, ensure_ascii=False)),
            )
            conn.commit()

    def passage_record(self, passage_id: str) -> dict[str, Any]:
        return self._load_payload("passage_records", passage_id, "passage record")

    def save_evidence_record(self, evidence: EvidenceRecord) -> None:
        if hashlib.sha256(evidence.content.encode("utf-8")).hexdigest() != evidence.content_hash:
            raise FoundationValidationError("Evidence content hash does not match its content")
        policy_id = self._ensure_policy(evidence.policy_binding)
        payload = to_wire(evidence)
        with self._connect() as conn:
            for unit_id in (*evidence.source_semantic_unit_ids, *evidence.target_semantic_unit_ids):
                if conn.execute("SELECT 1 FROM semantic_units WHERE id=?", (unit_id,)).fetchone() is None:
                    raise FoundationValidationError(f"Unknown evidence semantic unit: {unit_id}")
            conn.execute(
                "INSERT INTO evidence_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (evidence.id, evidence.project_id, evidence.kind.value, evidence.resource_id,
                 evidence.resource_version, evidence.resource_hash, evidence.occurrence_id,
                 evidence.validation_status.value, policy_id, evidence.review_status.value,
                 evidence.lifecycle_status.value, evidence.revision,
                 json.dumps(payload, ensure_ascii=False)),
            )
            conn.commit()

    def evidence_record(self, evidence_id: str) -> dict[str, Any]:
        return self._load_payload("evidence_records", evidence_id, "evidence record")

    def _load_payload(self, table: str, record_id: str, label: str) -> dict[str, Any]:
        allowed = {
            "passage_records", "evidence_records", "exportability_records",
        }
        if table not in allowed:
            raise FoundationValidationError(f"Unsupported payload table: {table}")
        with self._connect() as conn:
            row = conn.execute(f"SELECT payload_json FROM {table} WHERE id=?", (record_id,)).fetchone()
        if row is None:
            raise FoundationValidationError(f"Unknown {label}: {record_id}")
        return json.loads(row[0])

    def save_semantic_unit(self, unit: SemanticUnit) -> None:
        payload = to_wire(unit)
        with self._connect() as conn:
            for token_id in unit.token_instance_ids:
                token = conn.execute("SELECT side FROM token_instances WHERE id=?", (token_id,)).fetchone()
                if token is None:
                    raise FoundationValidationError(f"Unknown semantic-unit token instance: {token_id}")
                if token["side"] != unit.side.value:
                    raise FoundationValidationError(
                        f"Semantic-unit side does not match token instance: {token_id}"
                    )
            if unit.audit_owner_unit_id != unit.id and conn.execute(
                "SELECT 1 FROM semantic_units WHERE id=?", (unit.audit_owner_unit_id,)
            ).fetchone() is None:
                raise FoundationValidationError(
                    f"Unknown semantic-unit audit owner: {unit.audit_owner_unit_id}"
                )
            for evidence_id in unit.evidence_ids:
                if conn.execute(
                    "SELECT 1 FROM evidence_records WHERE id=?", (evidence_id,)
                ).fetchone() is None:
                    raise FoundationValidationError(
                        f"Unknown semantic-unit evidence record: {evidence_id}"
                    )
            conn.execute(
                "INSERT INTO semantic_units VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (unit.id, unit.project_id, unit.side.value, unit.kind.value, unit.audit_owner_unit_id,
                 unit.audit_eligibility.value, unit.semantic_obligation.value, unit.accounting_role.value,
                 unit.coverage_dimension.value, unit.semantic_fingerprint, unit.review_status.value,
                 unit.lifecycle_status.value, unit.revision, json.dumps(payload, ensure_ascii=False)),
            )
            conn.commit()

    def semantic_unit(self, unit_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM semantic_units WHERE id=?", (unit_id,)).fetchone()
        if row is None:
            raise FoundationValidationError(f"Unknown semantic unit: {unit_id}")
        return json.loads(row[0])

    def save_coverage_account(self, account: SemanticCoverageAccount) -> None:
        payload = to_wire(account)
        with self._connect() as conn:
            try:
                if conn.execute(
                    "SELECT 1 FROM semantic_units WHERE id=?", (account.audit_owner_unit_id,)
                ).fetchone() is None:
                    raise FoundationValidationError(
                        f"Unknown coverage-account audit owner: {account.audit_owner_unit_id}"
                    )
                for unit_id in account.member_unit_ids:
                    if conn.execute(
                        "SELECT 1 FROM semantic_units WHERE id=?", (unit_id,)
                    ).fetchone() is None:
                        raise FoundationValidationError(
                            f"Unknown coverage-account member: {unit_id}"
                        )
                conn.execute(
                    "INSERT INTO coverage_accounts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (account.id, account.project_id, account.passage_id, account.direction.value,
                     account.audit_owner_unit_id, account.coverage_dimension.value, account.semantic_fingerprint,
                     account.finding_id, account.review_status.value, account.lifecycle_status.value,
                     account.revision, json.dumps(payload, ensure_ascii=False)),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise FoundationConflict(f"Coverage account conflicts with an active obligation: {exc}") from exc

    def save_source_inventory(
        self, *, inventory_id: str, project_id: str, book: str, range_key: str,
        fingerprint: str, source_resource_id: str, source_resource_version: str,
        source_resource_hash: str, audit_policy_version: str,
        diagnostics: dict[str, Any], payload: dict[str, Any], token_rows: list[tuple[str, str, str]],
        unit_ids: list[str], evidence_ids: list[str],
    ) -> None:
        """Atomically publish one immutable, content-addressed source inventory."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            lock = conn.execute(
                "SELECT resource_id,resource_version,resource_hash,lifecycle_status "
                "FROM source_resource_locks WHERE project_id=? AND book=?",
                (project_id, book),
            ).fetchone()
            if lock is None or lock["lifecycle_status"] != "ACTIVE" or (
                lock["resource_id"], lock["resource_version"], lock["resource_hash"]
            ) != (source_resource_id, source_resource_version, source_resource_hash):
                raise FoundationValidationError(
                    "Source inventory does not match the active project source resource lock"
                )
            conn.execute(
                "UPDATE source_inventory_runs SET lifecycle_status='SUPERSEDED' "
                "WHERE project_id=? AND book=? AND range_key=? AND lifecycle_status='ACTIVE' "
                "AND fingerprint<>?",
                (project_id, book, range_key, fingerprint),
            )
            conn.execute(
                "INSERT INTO source_inventory_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (inventory_id, project_id, book, range_key, fingerprint,
                 source_resource_id, source_resource_version, source_resource_hash,
                 audit_policy_version, "ACTIVE", json.dumps(diagnostics, ensure_ascii=False),
                 json.dumps(payload, ensure_ascii=False), self._now()),
            )
            conn.executemany(
                "INSERT INTO source_inventory_tokens VALUES(?,?,?,?)",
                [(inventory_id, token_id, language_id, upstream_identity)
                 for token_id, language_id, upstream_identity in token_rows],
            )
            conn.executemany(
                "INSERT INTO source_inventory_units VALUES(?,?)",
                [(inventory_id, unit_id) for unit_id in unit_ids],
            )
            conn.executemany(
                "INSERT INTO source_inventory_evidence VALUES(?,?)",
                [(inventory_id, evidence_id) for evidence_id in evidence_ids],
            )
            conn.commit()

    def source_inventory_for_fingerprint(
        self, project_id: str, book: str, range_key: str, fingerprint: str,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM source_inventory_runs WHERE project_id=? AND book=? "
                "AND range_key=? AND fingerprint=? AND lifecycle_status='ACTIVE'",
                (project_id, book, range_key, fingerprint),
            ).fetchone()
        return None if row is None else json.loads(row[0])

    def source_inventory(self, inventory_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json,source_resource_id,source_resource_version,source_resource_hash,"
                "project_id,book,lifecycle_status FROM source_inventory_runs WHERE id=?",
                (inventory_id,),
            ).fetchone()
            if row is None:
                raise FoundationValidationError(f"Unknown source inventory: {inventory_id}")
            lock = conn.execute(
                "SELECT resource_id,resource_version,resource_hash,lifecycle_status "
                "FROM source_resource_locks WHERE project_id=? AND book=?",
                (row["project_id"], row["book"]),
            ).fetchone()
        if row["lifecycle_status"] != "ACTIVE" or lock is None or lock["lifecycle_status"] != "ACTIVE" or (
            row["source_resource_id"], row["source_resource_version"], row["source_resource_hash"]
        ) != (lock["resource_id"], lock["resource_version"], lock["resource_hash"]):
            raise FoundationValidationError(
                "Cached source inventory is stale or does not match the active source resource lock"
            )
        return json.loads(row["payload_json"])

    def quarantine_source_inventory(
        self, inventory_id: str, reason: str, payload: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE source_inventory_runs SET lifecycle_status='QUARANTINED' WHERE id=?",
                (inventory_id,),
            )
            conn.execute(
                "INSERT INTO migration_quarantine VALUES(?,?,?,?,?,?)",
                (str(uuid.uuid4()), "sourceSemantic.inventory",
                 inventory_id, "INVALID_SOURCE_INVENTORY",
                 json.dumps({"error": reason, "originalRecord": payload}, ensure_ascii=False),
                 self._now()),
            )
            conn.commit()

    def save_semantic_relationship(self, relationship: SemanticRelationship) -> None:
        payload = to_wire(relationship)
        with self._connect() as conn:
            for unit_id in (*relationship.source_semantic_unit_ids, *relationship.target_semantic_unit_ids):
                if conn.execute("SELECT 1 FROM semantic_units WHERE id=?", (unit_id,)).fetchone() is None:
                    raise FoundationValidationError(f"Unknown relationship semantic unit: {unit_id}")
            conn.execute(
                "INSERT INTO semantic_relationships VALUES(?,?,?,?,?,?)",
                (relationship.id, relationship.project_id, relationship.review_status.value,
                 relationship.lifecycle_status.value, relationship.revision,
                 json.dumps(payload, ensure_ascii=False)),
            )
            conn.commit()

    def semantic_relationship(self, relationship_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM semantic_relationships WHERE id=?", (relationship_id,)).fetchone()
        if row is None:
            raise FoundationValidationError(f"Unknown semantic relationship: {relationship_id}")
        return json.loads(row[0])

    def save_exportability(self, exportability: Exportability) -> None:
        policy_id = self._ensure_policy(exportability.policy_binding)
        payload = to_wire(exportability)
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO exportability_records VALUES(?,?,?,?,?,?,?,?)",
                    (exportability.id, exportability.relationship_id, exportability.format.value,
                     exportability.level.value, policy_id, exportability.lifecycle_status.value,
                     exportability.revision, json.dumps(payload, ensure_ascii=False)),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise FoundationConflict(f"Invalid or competing exportability record: {exc}") from exc

    def exportability(self, exportability_id: str) -> dict[str, Any]:
        return self._load_payload("exportability_records", exportability_id, "exportability")

    def create_lexical_solution(
        self, *, solution_id: str, project_id: str, scope_key: str, profile_id: str,
        source_layer: TokenLayer | None, target_layer: TokenLayer | None,
        authoritative: bool = False, policy: PolicyBinding | None = None,
    ) -> None:
        policy = policy or PolicyBinding.foundation_v1()
        policy_id = self._ensure_policy(policy)
        lifecycle = LifecycleStatus.ACTIVE if authoritative else LifecycleStatus.INACTIVE
        payload = {
            "id": solution_id, "projectId": project_id, "scopeKey": scope_key, "profileId": profile_id,
            "sourceLayer": source_layer.value if source_layer else None,
            "targetLayer": target_layer.value if target_layer else None,
            "authoritative": authoritative, "policyBinding": to_wire(policy),
            "reviewStatus": ReviewStatus.UNREVIEWED.value, "lifecycleStatus": lifecycle.value, "revision": 1,
        }
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT INTO lexical_solutions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (solution_id, project_id, scope_key, profile_id, payload["sourceLayer"], payload["targetLayer"],
                     int(authoritative), policy_id, ReviewStatus.UNREVIEWED.value, lifecycle.value, 1, json.dumps(payload)),
                )
                conn.commit()
        except sqlite3.IntegrityError as exc:
            if "uq_authoritative_active_lexical_solution" in str(exc) or "UNIQUE constraint failed" in str(exc):
                raise FoundationConflict("An authoritative active lexical solution already exists for this scope/profile/layers") from exc
            raise

    def lexical_solution(self, solution_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM lexical_solutions WHERE id=?", (solution_id,)).fetchone()
        if row is None:
            raise FoundationValidationError(f"Unknown lexical solution: {solution_id}")
        return json.loads(row[0])

    def activate_lexical_solution(
        self, solution_id: str, *, expected_revision: int, authoritative: bool,
        supersede_solution_id: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM lexical_solutions WHERE id=?", (solution_id,)).fetchone()
            if row is None:
                raise FoundationValidationError(f"Unknown lexical solution: {solution_id}")
            if int(row["revision"]) != expected_revision:
                raise FoundationConflict("Lexical solution revision conflict")
            active = conn.execute(
                "SELECT id FROM lexical_solutions WHERE project_id=? AND scope_key=? AND profile_id=? "
                "AND IFNULL(source_layer,'<NULL>')=IFNULL(?, '<NULL>') AND IFNULL(target_layer,'<NULL>')=IFNULL(?, '<NULL>') "
                "AND authoritative=1 AND lifecycle_status='ACTIVE' AND id<>?",
                (row["project_id"], row["scope_key"], row["profile_id"], row["source_layer"], row["target_layer"], solution_id),
            ).fetchone()
            if active is not None:
                if supersede_solution_id != active["id"]:
                    raise FoundationConflict("An authoritative active lexical solution already exists; explicitly supersede it")
                self._update_solution_state(conn, active["id"], LifecycleStatus.SUPERSEDED, authoritative=False)
            self._activate_memberships(conn, solution_id)
            payload = json.loads(row["payload_json"])
            payload.update({"authoritative": bool(authoritative), "lifecycleStatus": "ACTIVE", "revision": expected_revision + 1})
            changed = conn.execute(
                "UPDATE lexical_solutions SET authoritative=?,lifecycle_status='ACTIVE',revision=revision+1,payload_json=? WHERE id=? AND revision=?",
                (int(authoritative), json.dumps(payload), solution_id, expected_revision),
            ).rowcount
            if changed != 1:
                raise FoundationConflict("Lexical solution revision conflict")
            conn.commit()

    def _update_solution_state(self, conn: sqlite3.Connection, solution_id: str, status: LifecycleStatus, *, authoritative: bool) -> None:
        row = conn.execute("SELECT payload_json FROM lexical_solutions WHERE id=?", (solution_id,)).fetchone()
        if row is None:
            raise FoundationValidationError(f"Unknown superseded solution: {solution_id}")
        payload = json.loads(row[0]); payload["lifecycleStatus"] = status.value
        payload["authoritative"] = bool(authoritative); payload["revision"] = int(payload["revision"]) + 1
        conn.execute("DELETE FROM active_lexical_membership WHERE lexical_solution_id=?", (solution_id,))
        conn.execute(
            "UPDATE lexical_solutions SET authoritative=?,lifecycle_status=?,revision=revision+1,payload_json=? WHERE id=?",
            (int(authoritative), status.value, json.dumps(payload), solution_id),
        )

    def add_lexical_group(
        self, *, group_id: str, solution_id: str, cardinality: Cardinality,
        source_layer: TokenLayer | None, target_layer: TokenLayer | None,
        source_token_ids: tuple[str, ...], target_token_ids: tuple[str, ...],
        alignment_family_id: str | None = None, refines_group_id: str | None = None,
    ) -> None:
        self._validate_group(cardinality, source_layer, target_layer, source_token_ids, target_token_ids)
        policy = PolicyBinding.foundation_v1()
        payload = {
            "id": group_id, "solutionId": solution_id, "cardinality": cardinality.value,
            "sourceLayer": source_layer.value if source_layer else None,
            "targetLayer": target_layer.value if target_layer else None,
            "sourceTokenInstanceIds": list(source_token_ids), "targetTokenInstanceIds": list(target_token_ids),
            "alignmentFamilyId": alignment_family_id or group_id, "refinesGroupId": refines_group_id,
            "policyBinding": to_wire(policy), "reviewStatus": "UNREVIEWED", "lifecycleStatus": "INACTIVE", "revision": 1,
        }
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO lexical_groups VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (group_id, solution_id, cardinality.value, payload["sourceLayer"], payload["targetLayer"],
                 json.dumps(list(source_token_ids)), json.dumps(list(target_token_ids)), payload["alignmentFamilyId"],
                 refines_group_id, "UNREVIEWED", "INACTIVE", 1, json.dumps(payload)),
            )
            conn.commit()

    @staticmethod
    def _validate_group(cardinality: Cardinality, source_layer: TokenLayer | None, target_layer: TokenLayer | None,
                        source_ids: tuple[str, ...], target_ids: tuple[str, ...]) -> None:
        if len(set(source_ids)) != len(source_ids) or len(set(target_ids)) != len(target_ids):
            raise FoundationValidationError("A lexical group cannot repeat a token instance")
        if cardinality == Cardinality.SOURCE_TO_NULL:
            if not source_ids or target_ids or source_layer is None or target_layer is not None:
                raise FoundationValidationError("SOURCE_TO_NULL requires source tokens/layer and an absent target layer")
            return
        if cardinality == Cardinality.NULL_TO_TARGET:
            if source_ids or not target_ids or source_layer is not None or target_layer is None:
                raise FoundationValidationError("NULL_TO_TARGET requires target tokens/layer and an absent source layer")
            return
        if not source_ids or not target_ids or source_layer is None or target_layer is None:
            raise FoundationValidationError("A non-null lexical group requires tokens and layers on both sides")
        expected = {
            Cardinality.ONE_TO_ONE: (1, 1), Cardinality.ONE_TO_MANY: (1, None),
            Cardinality.MANY_TO_ONE: (None, 1), Cardinality.MANY_TO_MANY: (None, None),
        }[cardinality]
        s, t = expected
        if (s == 1 and len(source_ids) != 1) or (s is None and len(source_ids) < 2):
            raise FoundationValidationError(f"{cardinality.value} has invalid source cardinality")
        if (t == 1 and len(target_ids) != 1) or (t is None and len(target_ids) < 2):
            raise FoundationValidationError(f"{cardinality.value} has invalid target cardinality")

    def _activate_memberships(self, conn: sqlite3.Connection, solution_id: str) -> None:
        conn.execute("DELETE FROM active_lexical_membership WHERE lexical_solution_id=?", (solution_id,))
        groups = conn.execute("SELECT * FROM lexical_groups WHERE solution_id=?", (solution_id,)).fetchall()
        for group in groups:
            for side, layer_col, ids_col in (("SOURCE", "source_layer", "source_token_ids_json"), ("TARGET", "target_layer", "target_token_ids_json")):
                layer = group[layer_col]
                ids = json.loads(group[ids_col])
                if not ids:
                    if layer is not None:
                        raise FoundationValidationError(f"Null side of group {group['id']} must have a null layer")
                    continue
                if layer is None:
                    raise FoundationValidationError(f"Populated side of group {group['id']} must declare its layer")
                for token_id in ids:
                    token = conn.execute("SELECT side,token_layer,parent_instance_id FROM token_instances WHERE id=?", (token_id,)).fetchone()
                    if token is None:
                        raise FoundationValidationError(f"Unknown token instance in lexical group: {token_id}")
                    if token["side"] != side or token["token_layer"] != layer:
                        raise FoundationValidationError(f"Token side/layer mismatch for {token_id}")
                    try:
                        conn.execute("INSERT INTO active_lexical_membership VALUES(?,?,?,?,?)", (solution_id, side, layer, token_id, group["id"]))
                    except sqlite3.IntegrityError as exc:
                        raise FoundationConflict(f"Token instance {token_id} belongs to more than one active {layer} lexical group") from exc
            payload = json.loads(group["payload_json"]); payload["lifecycleStatus"] = "ACTIVE"; payload["revision"] += 1
            conn.execute("UPDATE lexical_groups SET lifecycle_status='ACTIVE',revision=revision+1,payload_json=? WHERE id=?", (json.dumps(payload), group["id"]))
        conflicts = conn.execute(
            "SELECT child.lexical_group_id AS child_group,parent.lexical_group_id AS parent_group,"
            "cg.refines_group_id,cg.alignment_family_id AS child_family,pg.alignment_family_id AS parent_family "
            "FROM active_lexical_membership child "
            "JOIN token_instances ti ON ti.id=child.token_instance_id "
            "JOIN active_lexical_membership parent ON parent.lexical_solution_id=child.lexical_solution_id "
            " AND parent.token_side=child.token_side AND parent.token_instance_id=ti.parent_instance_id "
            "JOIN lexical_groups cg ON cg.id=child.lexical_group_id "
            "JOIN lexical_groups pg ON pg.id=parent.lexical_group_id "
            "WHERE child.lexical_solution_id=? AND child.lexical_group_id<>parent.lexical_group_id",
            (solution_id,),
        ).fetchall()
        for conflict in conflicts:
            if conflict["refines_group_id"] != conflict["parent_group"] or conflict["child_family"] != conflict["parent_family"]:
                raise FoundationConflict(
                    f"Cross-layer group {conflict['child_group']} must explicitly refine parent group {conflict['parent_group']} in the same alignment family"
                )

    def create_minimal_semantic_unit(self, unit_id: str, *, project_id: str) -> None:
        payload = {
            "id": unit_id, "side": "SOURCE", "projectId": project_id, "book": "PHP", "kind": "LEXICAL",
            "displayedReferences": ["PHP 1:1"], "canonicalReferences": ["PHP 1:1"], "tokenInstanceIds": [],
            "tokenLineageIds": [], "rawSurface": "", "normalizedSurface": "", "semanticFeatures": {},
            "unitConfidence": {"rawScore": None, "calibratedValue": 0.0, "confidencePolicyVersion": "confidence-v1", "calibrationVersion": "calibration-v1"},
            "provenance": "DETERMINISTIC_RULE", "evidenceIds": [], "resourceValidationIds": [],
            "auditEligibility": "ELIGIBLE", "semanticObligation": "REQUIRED", "accountingRole": "PRIMARY",
            "auditOwnerUnitId": unit_id, "coverageDimension": "LEXICAL_CONTENT", "semanticFingerprint": unit_id,
            "policyBinding": to_wire(PolicyBinding.foundation_v1()), "reviewStatus": "UNREVIEWED", "lifecycleStatus": "ACTIVE", "revision": 1,
        }
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO semantic_units VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (unit_id, project_id, "SOURCE", "LEXICAL", unit_id, "ELIGIBLE", "REQUIRED", "PRIMARY",
                 "LEXICAL_CONTENT", unit_id, "UNREVIEWED", "ACTIVE", 1, json.dumps(payload)),
            )
            conn.commit()

    def add_dependency(self, parent_unit_id: str, child_unit_id: str, relation: str | DependencyRelation) -> None:
        relation = DependencyRelation(str(relation))
        if parent_unit_id == child_unit_id:
            raise FoundationValidationError("Semantic dependency DAG cannot contain a cycle")
        with self._connect() as conn:
            exists = conn.execute(
                "WITH RECURSIVE descendants(id) AS ("
                "SELECT child_unit_id FROM semantic_unit_dependencies WHERE parent_unit_id=? "
                "UNION SELECT d.child_unit_id FROM semantic_unit_dependencies d JOIN descendants x ON d.parent_unit_id=x.id"
                ") SELECT 1 FROM descendants WHERE id=? LIMIT 1",
                (child_unit_id, parent_unit_id),
            ).fetchone()
            if exists is not None:
                raise FoundationValidationError("Semantic dependency would create a cycle")
            try:
                conn.execute("INSERT INTO semantic_unit_dependencies VALUES(?,?,?,?)", (parent_unit_id, child_unit_id, relation.value, "{}"))
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise FoundationValidationError(f"Invalid semantic dependency: {exc}") from exc

    def add_semantic_relation(self, left_unit_id: str, right_unit_id: str, relation: str | SemanticRelation) -> None:
        relation = SemanticRelation(str(relation))
        with self._connect() as conn:
            conn.execute("INSERT INTO semantic_unit_relations VALUES(?,?,?,?)", (left_unit_id, right_unit_id, relation.value, "{}"))
            conn.commit()

    def create_qa_finding(self, finding_id: str, project_id: str) -> None:
        policy = PolicyBinding.foundation_v1(); policy_id = self._ensure_policy(policy)
        payload = {
            "id": finding_id, "projectId": project_id, "book": "", "passageId": "",
            "kind": "NEEDS_PASSAGE_REVIEW", "direction": "SOURCE_COVERAGE",
            "sourceSemanticUnitIds": [], "targetSemanticUnitIds": [],
            "semanticRelationshipIds": [], "evidenceIds": [], "explanation": "",
            "confidence": {"rawScore": None, "calibratedValue": 0.0,
                           "confidencePolicyVersion": policy.confidence_policy_version,
                           "calibrationVersion": policy.calibration_version},
            "currentTargetRevision": "UNBOUND", "qaDisposition": "UNRESOLVED",
            "policyBinding": to_wire(policy), "reviewStatus": "UNREVIEWED",
            "lifecycleStatus": "ACTIVE", "revision": 1,
        }
        with self._connect() as conn:
            conn.execute("INSERT INTO qa_findings VALUES(?,?,?,?,?,?,?,?)", (finding_id, project_id, "UNRESOLVED", policy_id, "UNREVIEWED", "ACTIVE", 1, json.dumps(payload)))
            conn.commit()

    def save_qa_finding(self, finding: QaFinding) -> None:
        policy_id = self._ensure_policy(finding.policy_binding)
        payload = to_wire(finding)
        with self._connect() as conn:
            for unit_id in (*finding.source_semantic_unit_ids, *finding.target_semantic_unit_ids):
                if conn.execute("SELECT 1 FROM semantic_units WHERE id=?", (unit_id,)).fetchone() is None:
                    raise FoundationValidationError(f"Unknown QA semantic unit: {unit_id}")
            for relationship_id in finding.semantic_relationship_ids:
                if conn.execute("SELECT 1 FROM semantic_relationships WHERE id=?", (relationship_id,)).fetchone() is None:
                    raise FoundationValidationError(f"Unknown QA semantic relationship: {relationship_id}")
            for evidence_id in finding.evidence_ids:
                if conn.execute("SELECT 1 FROM evidence_records WHERE id=?", (evidence_id,)).fetchone() is None:
                    raise FoundationValidationError(f"Unknown QA evidence record: {evidence_id}")
            conn.execute(
                "INSERT INTO qa_findings VALUES(?,?,?,?,?,?,?,?)",
                (finding.id, finding.project_id, finding.qa_disposition.value, policy_id,
                 finding.review_status.value, finding.lifecycle_status.value, finding.revision,
                 json.dumps(payload, ensure_ascii=False)),
            )
            conn.commit()

    def qa_finding(self, finding_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM qa_findings WHERE id=?", (finding_id,)).fetchone()
        if row is None:
            raise FoundationValidationError(f"Unknown QA finding: {finding_id}")
        return json.loads(row[0])

    def update_qa_disposition(self, finding_id: str, disposition: QaDisposition, expected_revision: int, reviewer: str) -> None:
        disposition = QaDisposition(disposition)
        review = ReviewStatus.NEEDS_DISCUSSION if disposition == QaDisposition.NEEDS_DISCUSSION else (
            ReviewStatus.UNREVIEWED if disposition == QaDisposition.UNRESOLVED else ReviewStatus.HUMAN_APPROVED
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM qa_findings WHERE id=?", (finding_id,)).fetchone()
            if row is None:
                raise FoundationValidationError(f"Unknown QA finding: {finding_id}")
            if int(row["revision"]) != expected_revision:
                raise FoundationConflict("QA finding revision conflict")
            payload = json.loads(row["payload_json"]); payload.update({"qaDisposition": disposition.value, "reviewStatus": review.value, "revision": expected_revision + 1})
            changed = conn.execute(
                "UPDATE qa_findings SET qa_disposition=?,review_status=?,revision=revision+1,payload_json=? WHERE id=? AND revision=?",
                (disposition.value, review.value, json.dumps(payload), finding_id, expected_revision),
            ).rowcount
            if changed != 1:
                raise FoundationConflict("QA finding revision conflict")
            self._append_review(conn, "QA_FINDING", finding_id, row["review_status"], review.value, row["lifecycle_status"], row["lifecycle_status"], row["qa_disposition"], disposition.value, ActorType.HUMAN, reviewer, expected_revision)
            conn.commit()

    def save_correction_proposal(self, proposal: CorrectionProposal) -> None:
        policy_id = self._ensure_policy(proposal.policy_binding); payload = to_wire(proposal)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO correction_proposals VALUES(?,?,?,?,?,?,?,?,?,?)",
                (proposal.id, proposal.project_id, proposal.qa_finding_id, proposal.current_target_revision,
                 proposal.applied_target_revision, policy_id, proposal.review_status.value, proposal.lifecycle_status.value,
                 proposal.revision, json.dumps(payload, ensure_ascii=False)),
            )
            conn.commit()

    def correction_proposal(self, proposal_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM correction_proposals WHERE id=?", (proposal_id,)).fetchone()
        if row is None:
            raise FoundationValidationError(f"Unknown correction proposal: {proposal_id}")
        return json.loads(row[0])

    def record_correction_applied(self, proposal_id: str, *, actor_type: str | ActorType, applied_target_revision: str, expected_revision: int, actor_id: str = "human") -> None:
        actor = ActorType(str(actor_type))
        if actor != ActorType.HUMAN:
            raise FoundationValidationError("Correction application requires explicit human action")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM correction_proposals WHERE id=?", (proposal_id,)).fetchone()
            if row is None:
                raise FoundationValidationError(f"Unknown correction proposal: {proposal_id}")
            if int(row["revision"]) != expected_revision:
                raise FoundationConflict("Correction proposal revision conflict")
            payload = json.loads(row["payload_json"])
            payload.update({"appliedTargetRevision": applied_target_revision, "appliedBy": actor_id, "appliedAt": self._now(),
                            "reviewStatus": "HUMAN_APPROVED", "lifecycleStatus": "ACTIVE", "revision": expected_revision + 1})
            conn.execute(
                "UPDATE correction_proposals SET applied_target_revision=?,review_status='HUMAN_APPROVED',lifecycle_status='ACTIVE',revision=revision+1,payload_json=? WHERE id=? AND revision=?",
                (applied_target_revision, json.dumps(payload, ensure_ascii=False), proposal_id, expected_revision),
            )
            finding = conn.execute("SELECT * FROM qa_findings WHERE id=?", (row["qa_finding_id"],)).fetchone()
            if finding is not None:
                q = json.loads(finding["payload_json"]); q.update({"qaDisposition": "CORRECTED", "reviewStatus": "HUMAN_APPROVED", "lifecycleStatus": "STALE", "revision": int(finding["revision"]) + 1})
                conn.execute("UPDATE qa_findings SET qa_disposition='CORRECTED',review_status='HUMAN_APPROVED',lifecycle_status='STALE',revision=revision+1,payload_json=? WHERE id=?", (json.dumps(q), finding["id"]))
            self._stale_generic_dependencies(conn, "CORRECTION_PROPOSAL", proposal_id)
            self._append_review(conn, "CORRECTION_PROPOSAL", proposal_id, row["review_status"], "HUMAN_APPROVED", row["lifecycle_status"], "ACTIVE", None, None, actor, actor_id, expected_revision)
            conn.commit()

    def add_record_dependency(self, record_type: str, record_id: str, depends_on_type: str, depends_on_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO record_dependencies VALUES(?,?,?,?)",
                (record_type, record_id, depends_on_type, depends_on_id),
            )
            conn.commit()

    def quarantine_migration_record(
        self, *, source_kind: str, source_identity: str, reason_code: str,
        payload: dict[str, Any],
    ) -> str:
        quarantine_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO migration_quarantine VALUES(?,?,?,?,?,?)",
                (quarantine_id, source_kind, source_identity, reason_code,
                 json.dumps(payload, ensure_ascii=False), self._now()),
            )
            conn.commit()
        return quarantine_id

    def migration_quarantine_records(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM migration_quarantine ORDER BY created_at,id"
            ).fetchall()
        return [
            {
                "id": row["id"], "sourceKind": row["source_kind"],
                "sourceIdentity": row["source_identity"], "reasonCode": row["reason_code"],
                "payload": json.loads(row["payload_json"]), "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def synchronize_source_lock(
        self, *, project_id: str, book: str, resource_id: str,
        resource_version: str, resource_hash: str,
    ) -> dict[str, Any]:
        now = self._now()
        changed = False
        staled = 0
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM source_resource_locks WHERE project_id=? AND book=?",
                (project_id, book),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO source_resource_locks VALUES(?,?,?,?,?,?,?,?)",
                    (project_id, book, resource_id, resource_version, resource_hash,
                     "ACTIVE", 1, now),
                )
            elif (
                row["resource_id"] != resource_id
                or row["resource_version"] != resource_version
                or row["resource_hash"] != resource_hash
            ):
                changed = True
                dependency_id = self.source_dependency_id(project_id, book, row["resource_hash"])
                staled = self._stale_generic_dependencies(conn, "SOURCE_RESOURCE", dependency_id)
                inventory_staled = conn.execute(
                    "UPDATE source_inventory_runs SET lifecycle_status='STALE' "
                    "WHERE project_id=? AND book=? AND lifecycle_status='ACTIVE'",
                    (project_id, book),
                ).rowcount
                staled += int(inventory_staled)
                conn.execute(
                    "UPDATE source_resource_locks SET resource_id=?,resource_version=?,resource_hash=?,"
                    "lifecycle_status='ACTIVE',revision=revision+1,updated_at=? "
                    "WHERE project_id=? AND book=?",
                    (resource_id, resource_version, resource_hash, now, project_id, book),
                )
            conn.commit()
        return {
            "changed": changed, "staled": staled, "resourceId": resource_id,
            "resourceVersion": resource_version, "resourceHash": resource_hash,
        }

    def source_lock(self, project_id: str, book: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM source_resource_locks WHERE project_id=? AND book=?",
                (project_id, book),
            ).fetchone()
        return dict(row) if row is not None else None

    def migration_run_for(
        self, project_id: str, source_path: str, source_hash: str,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM migration_runs WHERE project_id=? AND source_path=? AND source_hash=?",
                (project_id, source_path, source_hash),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["report"] = json.loads(result.pop("report_json"))
        return result

    def save_migration_run(
        self, *, run_id: str, project_id: str, source_path: str, source_hash: str,
        source_schema: str, status: str, started_at: str, report: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO migration_runs VALUES(?,?,?,?,?,?,?,?,?)",
                (run_id, project_id, source_path, source_hash, source_schema, status,
                 started_at, self._now(), json.dumps(report, ensure_ascii=False)),
            )
            conn.commit()

    def migration_report(self, project_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            runs = conn.execute(
                "SELECT * FROM migration_runs WHERE project_id=? ORDER BY started_at,id",
                (project_id,),
            ).fetchall()
            quarantine = conn.execute(
                "SELECT reason_code,COUNT(*) AS count FROM migration_quarantine "
                "GROUP BY reason_code ORDER BY reason_code"
            ).fetchall()
        return {
            "runs": [{
                "id": row["id"], "sourcePath": row["source_path"],
                "sourceHash": row["source_hash"], "sourceSchema": row["source_schema"],
                "status": row["status"], "startedAt": row["started_at"],
                "completedAt": row["completed_at"], "report": json.loads(row["report_json"]),
            } for row in runs],
            "quarantineByReason": {row["reason_code"]: row["count"] for row in quarantine},
        }

    def record_runtime_diagnostic(
        self, *, project_id: str, code: str, severity: str, payload: dict[str, Any],
    ) -> str:
        diagnostic_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runtime_diagnostics VALUES(?,?,?,?,?,?,NULL)",
                (diagnostic_id, project_id, code, severity,
                 json.dumps(payload, ensure_ascii=False), self._now()),
            )
            conn.commit()
        return diagnostic_id

    def stale_summary(self, project_id: str) -> dict[str, Any]:
        tables = {
            "passages": "passage_records", "tokens": "token_lineages",
            "semanticUnits": "semantic_units", "semanticRelationships": "semantic_relationships",
            "coverageAccounts": "coverage_accounts", "qaFindings": "qa_findings",
            "lexicalSolutions": "lexical_solutions", "correctionProposals": "correction_proposals",
            "evidence": "evidence_records", "exportability": "exportability_records",
        }
        counts: dict[str, int] = {}
        with self._connect() as conn:
            for label, table in tables.items():
                if table == "token_lineages":
                    counts[label] = int(conn.execute(
                        "SELECT COUNT(*) FROM token_lineages WHERE project_id=? AND lifecycle_status='STALE'",
                        (project_id,),
                    ).fetchone()[0])
                else:
                    counts[label] = int(conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE project_id=? AND lifecycle_status='STALE'",
                        (project_id,),
                    ).fetchone()[0]) if table not in {"exportability_records"} else int(conn.execute(
                        "SELECT COUNT(*) FROM exportability_records e JOIN semantic_relationships r "
                        "ON r.id=e.relationship_id WHERE r.project_id=? AND e.lifecycle_status='STALE'",
                        (project_id,),
                    ).fetchone()[0])
            pending = int(conn.execute(
                "SELECT COUNT(*) FROM pending_invalidations WHERE project_id=? AND state='PREPARED'",
                (project_id,),
            ).fetchone()[0])
            quarantined = int(conn.execute(
                "SELECT COUNT(*) FROM migration_quarantine"
            ).fetchone()[0])
        return {"counts": counts, "pendingInvalidations": pending, "quarantined": quarantined}

    @staticmethod
    def _stale_generic_dependencies(
        conn: sqlite3.Connection, dependency_type: str, dependency_id: str,
    ) -> int:
        tables = {
            "PASSAGE_RECORD": "passage_records",
            "EVIDENCE_RECORD": "evidence_records",
            "SEMANTIC_RELATIONSHIP": "semantic_relationships",
            "COVERAGE_ACCOUNT": "coverage_accounts",
            "QA_FINDING": "qa_findings",
            "LEXICAL_SOLUTION": "lexical_solutions",
            "CORRECTION_PROPOSAL": "correction_proposals",
            "EXPORTABILITY": "exportability_records",
        }
        queue: list[tuple[str, str]] = [(dependency_type, dependency_id)]
        visited: set[tuple[str, str]] = set()
        changed = 0
        while queue:
            current_type, current_id = queue.pop(0)
            if (current_type, current_id) in visited:
                continue
            visited.add((current_type, current_id))
            rows = conn.execute(
                "SELECT record_type,record_id FROM record_dependencies "
                "WHERE depends_on_type=? AND depends_on_id=?",
                (current_type, current_id),
            ).fetchall()
            for row in rows:
                record_type, record_id = row["record_type"], row["record_id"]
                table = tables.get(record_type)
                if not table:
                    continue
                record = conn.execute(
                    f"SELECT payload_json FROM {table} WHERE id=?", (record_id,),
                ).fetchone()
                if record is None:
                    continue
                payload = json.loads(record[0])
                payload["lifecycleStatus"] = "STALE"
                payload["revision"] = int(payload.get("revision", 1)) + 1
                updated = conn.execute(
                    f"UPDATE {table} SET lifecycle_status='STALE',revision=revision+1,payload_json=? "
                    "WHERE id=? AND lifecycle_status<>'STALE'",
                    (json.dumps(payload, ensure_ascii=False), record_id),
                ).rowcount
                changed += updated
                # Dependency propagation is independent of whether this record
                # was already stale. A downstream record must not remain current.
                queue.append((record_type, record_id))
        return changed

    def _append_review(self, conn: sqlite3.Connection, entity_type: str, entity_id: str,
                       previous_review: str | None, new_review: str, previous_lifecycle: str | None,
                       new_lifecycle: str, previous_disposition: str | None, new_disposition: str | None,
                       actor_type: ActorType, actor_id: str, base_revision: int) -> None:
        conn.execute(
            "INSERT INTO review_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), entity_type, entity_id, previous_review, new_review, previous_lifecycle,
             new_lifecycle, previous_disposition, new_disposition, actor_type.value, actor_id, "", base_revision, self._now()),
        )

    def review_records(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM review_records WHERE entity_type=? AND entity_id=? ORDER BY created_at,id",
                (entity_type, entity_id),
            ).fetchall()
        return [
            {
                "id": row["id"], "entityType": row["entity_type"], "entityId": row["entity_id"],
                "previousReviewStatus": row["previous_review_status"],
                "newReviewStatus": row["new_review_status"],
                "previousLifecycleStatus": row["previous_lifecycle_status"],
                "newLifecycleStatus": row["new_lifecycle_status"],
                "previousQaDisposition": row["previous_qa_disposition"],
                "newQaDisposition": row["new_qa_disposition"], "actorType": row["actor_type"],
                "actorId": row["actor_id"], "note": row["note"],
                "baseRevision": row["base_revision"], "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def import_review_record(
        self, *, record_id: str, entity_type: str, entity_id: str,
        review_status: ReviewStatus, lifecycle_status: LifecycleStatus,
        actor_type: ActorType, actor_id: str, note: str, created_at: str,
        qa_disposition: QaDisposition | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO review_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (record_id, entity_type, entity_id, None, review_status.value, None,
                 lifecycle_status.value, None,
                 qa_disposition.value if qa_disposition is not None else None,
                 actor_type.value, actor_id, note, 1, created_at),
            )
            conn.commit()

    def recovery_check(self) -> dict[str, Any]:
        problems: list[str] = []
        with self._connect() as conn:
            integrity = [r[0] for r in conn.execute("PRAGMA integrity_check").fetchall()]
            if integrity != ["ok"]:
                problems.extend(integrity)
            foreign = conn.execute("PRAGMA foreign_key_check").fetchall()
            problems.extend(f"foreign-key:{tuple(row)}" for row in foreign)
            dangling = conn.execute(
                "SELECT m.token_instance_id FROM active_lexical_membership m "
                "JOIN lexical_solutions s ON s.id=m.lexical_solution_id "
                "JOIN lexical_groups g ON g.id=m.lexical_group_id "
                "WHERE s.lifecycle_status<>'ACTIVE' OR g.lifecycle_status<>'ACTIVE'"
            ).fetchall()
            problems.extend(f"inactive-membership:{row[0]}" for row in dangling)
            competing = conn.execute(
                "SELECT project_id,scope_key,profile_id,IFNULL(source_layer,'<NULL>'),"
                "IFNULL(target_layer,'<NULL>'),COUNT(*) FROM lexical_solutions "
                "WHERE authoritative=1 AND lifecycle_status='ACTIVE' "
                "GROUP BY project_id,scope_key,profile_id,IFNULL(source_layer,'<NULL>'),"
                "IFNULL(target_layer,'<NULL>') HAVING COUNT(*)>1"
            ).fetchall()
            problems.extend(f"competing-authoritative-solution:{tuple(row)}" for row in competing)
            known_record_tables = {
                "PASSAGE_RECORD": "passage_records",
                "EVIDENCE_RECORD": "evidence_records",
                "SEMANTIC_RELATIONSHIP": "semantic_relationships",
                "COVERAGE_ACCOUNT": "coverage_accounts",
                "QA_FINDING": "qa_findings",
                "LEXICAL_SOLUTION": "lexical_solutions",
                "CORRECTION_PROPOSAL": "correction_proposals",
                "EXPORTABILITY": "exportability_records",
            }
            dependencies = conn.execute(
                "SELECT record_type,record_id,depends_on_type,depends_on_id FROM record_dependencies"
            ).fetchall()
            for dependency in dependencies:
                table = known_record_tables.get(dependency["record_type"])
                if table is None:
                    problems.append(
                        f"unknown-record-dependency-type:{dependency['record_type']}:{dependency['record_id']}"
                    )
                    continue
                if conn.execute(
                    f"SELECT 1 FROM {table} WHERE id=?", (dependency["record_id"],)
                ).fetchone() is None:
                    problems.append(
                        f"dangling-record-dependency:{dependency['record_type']}:{dependency['record_id']}"
                    )
                upstream_table = known_record_tables.get(dependency["depends_on_type"])
                if upstream_table is not None and conn.execute(
                    f"SELECT 1 FROM {upstream_table} WHERE id=?", (dependency["depends_on_id"],)
                ).fetchone() is None:
                    problems.append(
                        f"dangling-upstream-dependency:{dependency['depends_on_type']}:{dependency['depends_on_id']}"
                    )
            for row in conn.execute(
                "SELECT id,target_content_hash,payload_json FROM passage_records"
            ).fetchall():
                try:
                    payload = json.loads(row["payload_json"])
                    actual = self.target_content_hash(payload["targetTextByDisplayedReference"])
                    if actual != row["target_content_hash"] or actual != payload["targetContentHash"]:
                        problems.append(f"passage-content-hash:{row['id']}")
                except (KeyError, TypeError, json.JSONDecodeError):
                    problems.append(f"invalid-passage-payload:{row['id']}")
            for row in conn.execute("SELECT id,payload_json FROM evidence_records").fetchall():
                try:
                    payload = json.loads(row["payload_json"])
                    actual = hashlib.sha256(payload["content"].encode("utf-8")).hexdigest()
                    if actual != payload["contentHash"]:
                        problems.append(f"evidence-content-hash:{row['id']}")
                except (KeyError, TypeError, json.JSONDecodeError):
                    problems.append(f"invalid-evidence-payload:{row['id']}")
        self.read_only = bool(problems)
        return {"ok": not problems, "readOnly": self.read_only, "problems": problems, "schemaVersion": self.schema_version()}

    def backup(self, backup_root: str | Path, *, reason: str) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        directory = Path(backup_root) / stamp
        directory.mkdir(parents=True, exist_ok=False)
        backup_db = directory / "bridge-semantic-v1.sqlite3"
        with self._connect() as source:
            destination = sqlite3.connect(str(backup_db))
            try:
                source.backup(destination)
                destination.commit()
            finally:
                destination.close()
        digest = hashlib.sha256(backup_db.read_bytes()).hexdigest()
        manifest = {"schemaId": SCHEMA_ID, "schemaVersion": self.schema_version(), "sha256": digest,
                    "source": str(self.path), "reason": reason, "createdAt": self._now()}
        (directory / "backup-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return directory

    def restore(self, backup_directory: str | Path) -> None:
        directory = Path(backup_directory)
        source_db = directory / "bridge-semantic-v1.sqlite3"
        manifest_path = directory / "backup-manifest.json"
        if not source_db.exists() or not manifest_path.exists():
            raise FoundationValidationError("Backup database or manifest is missing")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if hashlib.sha256(source_db.read_bytes()).hexdigest() != manifest.get("sha256"):
            raise FoundationValidationError("Backup checksum does not match its manifest")
        safety_root = self.path.parent / "restore-safety"
        self.backup(safety_root, reason="pre-restore safety backup")
        self.read_only = False
        temp = self.path.with_suffix(self.path.suffix + ".restore")
        if temp.exists():
            temp.unlink()
        source = sqlite3.connect(str(source_db))
        destination = sqlite3.connect(str(temp))
        try:
            source.backup(destination)
            destination.commit()
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise FoundationValidationError("Restored backup failed SQLite integrity check")
        finally:
            destination.close()
            source.close()
        for suffix in ("-wal", "-shm"):
            companion = Path(str(self.path) + suffix)
            if companion.exists():
                companion.unlink()
        last_replace_error: PermissionError | None = None
        for attempt in range(6):
            try:
                os.replace(temp, self.path)
                last_replace_error = None
                break
            except PermissionError as exc:
                last_replace_error = exc
                if attempt < 5:
                    time.sleep(0.05 * (attempt + 1))
        if last_replace_error is not None:
            # Windows can deny atomic replacement of a recently opened SQLite
            # file even after every Bridge connection is closed. SQLite's own
            # online-backup API is the transaction-safe fallback; the safety
            # backup above still makes the operation recoverable.
            source = sqlite3.connect(str(temp))
            destination = sqlite3.connect(str(self.path))
            try:
                source.backup(destination)
                destination.commit()
            except sqlite3.Error as exc:
                raise FoundationValidationError(
                    "Restored database could not replace the live companion store"
                ) from exc
            finally:
                destination.close()
                source.close()
            try:
                temp.unlink()
            except OSError:
                pass
        self.read_only = False
        # Backups from an older operational schema are restored losslessly and
        # then migrated through the same guarded path before becoming writable.
        self._migrate()
        check = self.recovery_check()
        if not check["ok"]:
            raise FoundationValidationError(f"Restored backup failed recovery checks: {check['problems']}")
