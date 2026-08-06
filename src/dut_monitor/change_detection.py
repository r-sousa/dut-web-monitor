from __future__ import annotations

from typing import Any


IGNORED_CHANGE_FIELDS = {"retrieved_at"}


def natural_identity(record: dict[str, Any], dataset: str) -> tuple[Any, ...] | None:
    if dataset == "newsletters":
        return (record.get("archive_url"), str(record.get("issue_label") or "").casefold())
    if dataset == "webinars" and record.get("episode_number") is not None:
        return (record.get("episode_number"),)
    if dataset == "news":
        return (record.get("canonical_url"),)
    return None


def index_records(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {record["external_id"]: record for record in records}


def compare_records(old_records: list[dict[str, Any]], new_records: list[dict[str, Any]], dataset: str) -> list[dict[str, Any]]:
    old_index = index_records(old_records)
    new_index = index_records(new_records)
    changes: list[dict[str, Any]] = []

    for external_id in sorted(new_index.keys() - old_index.keys()):
        changes.append({"dataset": dataset, "external_id": external_id, "change_type": "new", "materiality": "standard", "changed_fields": {}})

    for external_id in sorted(old_index.keys() & new_index.keys()):
        old = old_index[external_id]
        new = new_index[external_id]
        if old.get("content_hash") == new.get("content_hash"):
            new["retrieved_at"] = old.get("retrieved_at", new.get("retrieved_at"))
            continue
        changed_fields: dict[str, dict[str, Any]] = {}
        for key in sorted(set(old) | set(new)):
            if key in IGNORED_CHANGE_FIELDS or old.get(key) == new.get(key):
                continue
            changed_fields[key] = {"old": old.get(key), "new": new.get(key)}
        high_fields = {"opening_date", "stage1_deadline", "stage2_deadline", "start_date", "status"}
        changes.append({"dataset": dataset, "external_id": external_id, "change_type": "modified", "materiality": "high" if high_fields.intersection(changed_fields) else "standard", "changed_fields": changed_fields})

    new_natural_ids = {identity for record in new_records if (identity := natural_identity(record, dataset)) is not None}
    retained_records: list[dict[str, Any]] = []
    for external_id in sorted(old_index.keys() - new_index.keys()):
        old_record = old_index[external_id]
        identity = natural_identity(old_record, dataset)
        if identity is not None and identity in new_natural_ids:
            continue
        retained = dict(old_record)
        retained["source_status"] = "possibly_removed"
        retained_records.append(retained)
        changes.append({"dataset": dataset, "external_id": external_id, "change_type": "possibly_removed", "materiality": "high", "changed_fields": {"source_status": {"old": old_record.get("source_status"), "new": "possibly_removed"}}})

    new_records.extend(retained_records)
    return changes
