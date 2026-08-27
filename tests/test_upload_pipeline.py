"""Upload and the transcription pipeline."""
import io, os, sys, pathlib, tempfile
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("ENYGMA_SESSION_SECRET", "test-secret")

from src import db, config as cfg, meetings as repo      # noqa: E402
from src.ingest import upload                            # noqa: E402
from src.pipeline import runner                          # noqa: E402
from src.pipeline.stub import StubBackend                # noqa: E402
from src.pipeline.base import Backend                    # noqa: E402

MP3 = b"ID3\x03\x00\x00\x00" + b"\x11" * 4096


def setup_module(_):
    tmp = pathlib.Path(tempfile.mkdtemp())
    cfg.DB_PATH = tmp / "t.db"; cfg.DATA_DIR = tmp
    db.DB_PATH = cfg.DB_PATH;  db.DATA_DIR = cfg.DATA_DIR
    upload.UPLOADS = tmp / "uploads"
    upload.BASE_DIR = tmp
    runner.BASE_DIR = tmp
    db.migrate()


def clean():
    with db.cursor() as conn:
        for table in ("action_items", "summaries", "speakers", "transcript_segments", "recordings"):
            conn.execute(f"DELETE FROM {table}")


# ------------------------------------------------------------------ upload
def test_non_audio_is_rejected_with_a_usable_sentence():
    with pytest.raises(upload.Rejected) as exc:
        upload.check("notes.txt")
    assert "not audio" in str(exc.value)
    assert ".mp3" in str(exc.value), "the message says what would work"


def test_empty_file_is_rejected():
    clean()
    with pytest.raises(upload.Rejected):
        upload.store("silence.mp3", io.BytesIO(b""))


def test_store_derives_a_title_and_dedupes_on_content():
    clean()
    first = upload.store("2026-08-21 Quarterly_review-with-Meridian.mp3", io.BytesIO(MP3))
    assert first["duplicate"] is False
    assert first["title"] == "Quarterly review with Meridian", "timestamp and separators are cleaned"

    # Same bytes, different name. One meeting.
    again = upload.store("copy of whatever.mp3", io.BytesIO(MP3))
    assert again["duplicate"] is True
    assert again["id"] == first["id"]
    assert len(repo.listing()) == 1


def test_stored_file_lands_on_disk_with_its_size_recorded():
    clean()
    rec = upload.store("standup.wav", io.BytesIO(MP3))
    row = repo.detail(rec["id"])["recording"]
    assert row["bytes"] == len(MP3)
    assert row["source"] == "upload"
    assert row["status"] == "queued"
    assert (upload.BASE_DIR / row["audio_path"]).exists()


# ---------------------------------------------------------------- pipeline
def test_pipeline_takes_a_queued_recording_all_the_way_to_ready():
    clean()
    rec = upload.store("vendor call.mp3", io.BytesIO(MP3))
    result = runner.process_one(StubBackend())
    assert result["status"] == "ready"

    data = repo.detail(rec["id"])
    assert data["recording"]["status"] == "ready"
    assert len(data["segments"]) == 5
    assert data["segments"][0]["speaker_label"] == "SPEAKER 1"
    assert data["summary"]["abstract"]
    assert data["summary"]["decisions"][0]["at_ms"] is not None, "claims carry a timestamp"
    assert len(data["actions"]) == 2
    assert {s["label"] for s in data["speakers"]} == {"SPEAKER 1", "SPEAKER 2", "SPEAKER 3"}
    assert data["recording"]["duration_ms"], "duration comes from the last segment"


def test_nothing_queued_returns_none_rather_than_spinning():
    clean()
    assert runner.process_one(StubBackend()) is None


def test_a_failing_backend_records_a_reason_and_can_be_retried():
    clean()
    rec = upload.store("bad.mp3", io.BytesIO(MP3))

    class Broken(Backend):
        def transcribe(self, *_): raise RuntimeError("model returned no segments")

    result = runner.process_one(Broken())
    assert result["status"] == "failed"
    row = repo.detail(rec["id"])["recording"]
    assert row["status"] == "failed"
    assert "model returned no segments" in row["failure"], "the reason names the thing"

    with db.cursor() as conn:
        conn.execute("UPDATE recordings SET status='queued', failure=NULL WHERE id=?", (rec["id"],))
    assert runner.process_one(StubBackend())["status"] == "ready"


def test_reprocessing_replaces_rather_than_duplicates():
    clean()
    rec = upload.store("again.mp3", io.BytesIO(MP3))
    runner.process_one(StubBackend())
    with db.cursor() as conn:
        conn.execute("UPDATE recordings SET status='queued' WHERE id=?", (rec["id"],))
    runner.process_one(StubBackend())
    data = repo.detail(rec["id"])
    assert len(data["segments"]) == 5, "segments are replaced, not appended"
    assert len(data["speakers"]) == 3


def test_a_claimed_job_is_not_claimed_twice():
    clean()
    upload.store("one.mp3", io.BytesIO(MP3))
    first = runner.claim_next()
    second = runner.claim_next()
    assert first is not None and second is None


def test_speaker_assignment_is_exact():
    clean()
    rec = upload.store("assign.mp3", io.BytesIO(MP3))
    runner.process_one(StubBackend())
    repo.assign_speaker(rec["id"], "SPEAKER 2", "Daniel Voss")
    names = {s["label"]: s["person_name"] for s in repo.detail(rec["id"])["speakers"]}
    assert names["SPEAKER 2"] == "Daniel Voss"
    assert names["SPEAKER 1"] is None, "assigning one speaker never touches another"


def test_no_stylesheet_references_an_undefined_token():
    """The failure that has no console message: an undefined custom property
    invalidates its whole declaration and the browser drops it silently."""
    import subprocess
    root = pathlib.Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, str(root / "tools/check_tokens.py")],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout


def test_stored_paths_are_posix_shaped():
    """A Windows checkout writes uploads\\abc.mp3, which breaks the moment the
    database is copied to the Spark. Forward slashes read correctly on both."""
    clean()
    rec = upload.store("portable.mp3", io.BytesIO(MP3))
    stored = repo.detail(rec["id"])["recording"]["audio_path"]
    assert "\\" not in stored
    assert stored.startswith("uploads/")


def test_a_full_client_path_is_reduced_to_its_leaf():
    """Some browsers hand over C:\\Users\\dawud\\Desktop\\meeting.mp3."""
    clean()
    rec = upload.store(r"C:\Users\dawud\Desktop\Board meeting.mp3", io.BytesIO(MP3))
    assert rec["title"] == "Board meeting"
    assert repo.detail(rec["id"])["recording"]["original_filename"] == "Board meeting.mp3"
