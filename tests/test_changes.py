from dut_monitor.change_detection import compare_records


def test_high_materiality_deadline_change() -> None:
    old = [{"external_id": "x", "content_hash": "a", "stage1_deadline": "2026-11-17"}]
    new = [{"external_id": "x", "content_hash": "b", "stage1_deadline": "2026-11-19"}]
    changes = compare_records(old, new, "calls")
    assert changes[0]["materiality"] == "high"
    assert changes[0]["changed_fields"]["stage1_deadline"]["new"] == "2026-11-19"


def test_missing_record_is_retained() -> None:
    old = [{"external_id": "x", "content_hash": "a", "source_status": "active"}]
    new = []
    changes = compare_records(old, new, "calls")
    assert new[0]["source_status"] == "possibly_removed"
    assert changes[0]["change_type"] == "possibly_removed"
