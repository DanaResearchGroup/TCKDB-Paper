"""What the curation step reads back from the instance."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "snapshot"


@pytest.fixture(scope="module")
def curation():
    sys.path.insert(0, str(SNAPSHOT_DIR))
    try:
        import curation as module

        yield module
    finally:
        sys.path.remove(str(SNAPSHOT_DIR))


class _PagedCurator:
    """Answers the artifact search in pages of ``page`` records, ``total`` records in all."""

    def __init__(self, total: int, page: int) -> None:
        self.total, self.page, self.calls = total, page, []

    def ok(self, method, path, params=None, **_):
        self.calls.append(dict(params or {}))
        start = int((params or {}).get("cursor") or 0)
        end = min(start + self.page, self.total)
        return {"records": [{"n": i} for i in range(start, end)], "next_cursor": str(end) if end < self.total else None}


def test_the_artifact_count_reads_every_page(curation):
    curator = _PagedCurator(total=203, page=200)
    assert curation._artifact_count(curator, "calc_x") == 203
    assert [c.get("cursor") for c in curator.calls] == [None, "200"]
    assert all(c["calculation_ref"] == "calc_x" for c in curator.calls)
