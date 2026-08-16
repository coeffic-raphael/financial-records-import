"""The upload limit must bound MEMORY, not merely reject afterwards.

Reading a body in full and then measuring it makes the limit functional only: an
oversized file is entirely resident before being refused, and several files in
one request multiply that. The limit has to be enforced while reading.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest
from fastapi import UploadFile

from app.api.batches import UPLOAD_CHUNK_BYTES, _spool_upload
from app.api.errors import APIError
from app.providers.mock import MockProvider

VALID_PDF = b"%PDF-1.4 minimal"
LIMIT = 10 * 1024 * 1024


@pytest.fixture
def client(client_with_provider):
    return client_with_provider(MockProvider(records=[{"reference": "R-1"}]))


def _upload(client, batch_id, files):
    return client.post(f"/api/batches/{batch_id}/uploads/pdf", files=files)


def _temp_files_before() -> set[Path]:
    return set(Path(tempfile.gettempdir()).glob("*.pdf"))


class LazyStream:
    """A stream that manufactures bytes on demand and counts what it served.

    Nothing large is ever allocated, so the test can describe a 500 MB upload
    without holding one -- and what it measures is the property that matters:
    how much of the body the server chose to consume.
    """

    def __init__(self, total: int) -> None:
        self.total = total
        self.served = 0

    def read(self, size: int = -1) -> bytes:
        if self.served >= self.total:
            return b""
        count = self.total - self.served if size < 0 else min(size, self.total - self.served)
        self.served += count
        return b"%PDF" + b"x" * (count - 4) if self.served == count else b"x" * count


class TestReadingStopsAtTheThreshold:
    """The limit is enforced WHILE reading, not after the body is resident."""

    def _spool(self, total: int, limit: int = LIMIT) -> LazyStream:
        stream = LazyStream(total)
        upload = UploadFile(file=stream, filename="huge.pdf")
        asyncio.run(_spool_upload(upload, limit, "document.pdf"))
        return stream

    def test_an_oversized_body_is_abandoned_early(self):
        oversized = 500 * 1024 * 1024  # half a gigabyte, never allocated

        with pytest.raises(APIError) as raised:
            self._spool(oversized)

        assert raised.value.status_code == 413

    def test_only_a_fraction_of_the_body_is_consumed(self):
        stream = LazyStream(500 * 1024 * 1024)
        upload = UploadFile(file=stream, filename="huge.pdf")

        with pytest.raises(APIError):
            asyncio.run(_spool_upload(upload, LIMIT, "document.pdf"))

        assert stream.served <= LIMIT + UPLOAD_CHUNK_BYTES, (
            f"{stream.served} bytes were read before refusing a {stream.total} byte upload"
        )
        assert stream.served < stream.total / 10

    def test_a_file_within_the_limit_is_read_in_full(self):
        stream = LazyStream(UPLOAD_CHUNK_BYTES * 3)
        upload = UploadFile(file=stream, filename="ok.pdf")

        _, path = asyncio.run(_spool_upload(upload, LIMIT, "document.pdf"))

        assert stream.served == stream.total
        assert path.stat().st_size == stream.total
        path.unlink(missing_ok=True)

    def test_the_chunk_size_is_small(self):
        assert UPLOAD_CHUNK_BYTES <= 256 * 1024


class TestSpooledFilesAreCleanedUp:
    def test_a_successful_extraction_removes_its_temporary_file(self, client, batch):
        before = _temp_files_before()
        _upload(client, batch["id"], [("files", ("ok.pdf", VALID_PDF, "application/pdf"))])

        assert _temp_files_before() - before == set()

    def test_a_rejected_upload_leaves_nothing_behind(self, client, batch):
        before = _temp_files_before()
        _upload(
            client,
            batch["id"],
            [
                ("files", ("ok.pdf", VALID_PDF, "application/pdf")),
                ("files", ("bad.pdf", b"not a pdf", "application/pdf")),
            ],
        )

        assert _temp_files_before() - before == set(), (
            "the file spooled before the rejection must be removed"
        )

    def test_a_failed_extraction_still_removes_its_file(
        self, client_with_provider, batch, monkeypatch
    ):
        from app.services import pdf_extraction

        monkeypatch.setattr(
            pdf_extraction,
            "persist_records",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        client = client_with_provider(MockProvider(records=[{"reference": "R-1"}]))

        before = _temp_files_before()
        _upload(client, batch["id"], [("files", ("ok.pdf", VALID_PDF, "application/pdf"))])

        assert _temp_files_before() - before == set()


class TestJobsAreCreatedTogether:
    def test_all_jobs_appear_at_once(self, client, batch):
        response = _upload(
            client,
            batch["id"],
            [("files", (f"f{index}.pdf", VALID_PDF, "application/pdf")) for index in range(4)],
        )

        assert response.status_code == 202
        assert len(client.get(f"/api/batches/{batch['id']}/jobs").json()) == 4
