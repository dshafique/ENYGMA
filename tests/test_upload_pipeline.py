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


# --------------------------------------------------------------- salvage
def test_a_truncated_transcript_is_recovered_rather_than_thrown_away():
    """The real failure: JSONDecodeError at char 7755. An hour of correctly
    transcribed speech was discarded because of the last four characters."""
    import json
    from src.pipeline.gemini import segments_from

    whole = json.dumps({"segments": [
        {"speaker": f"SPEAKER {i % 3 + 1}", "start": "00:00", "end": "00:05",
         "text": f"Segment number {i} of the meeting."} for i in range(170)]})

    rows, salvaged = segments_from(whole)
    assert len(rows) == 170 and salvaged is False

    cut = whole[:7755]
    try:
        json.loads(cut)
        raise AssertionError("that should not have parsed")
    except json.JSONDecodeError:
        pass
    rows, salvaged = segments_from(cut)
    assert salvaged is True
    assert len(rows) == 73, "everything before the cut should survive"
    assert all(r.get("text") for r in rows)


def test_salvage_is_not_confused_by_braces_or_quotes_in_speech():
    import json
    from src.pipeline.gemini import segments_from
    marker = '{"retain": true}'
    payload = json.dumps({"segments": [{
        "speaker": "SPEAKER 1", "start": "00:00", "end": "00:09",
        "text": 'He wrote ' + marker + ' on the board and said "that is the fix".'}]})
    rows, salvaged = segments_from(payload)
    assert len(rows) == 1 and not salvaged
    assert marker in rows[0]["text"]


def test_a_refusal_or_prose_reply_is_not_mistaken_for_a_transcript():
    from src.pipeline.gemini import segments_from
    rows, _ = segments_from("I'm sorry, I can't help with that.")
    assert rows == []


def test_a_salvaged_transcript_tells_the_operator_it_is_incomplete():
    """Silently incomplete is worse than failed. The recording still becomes
    usable, and carries a note saying how far it got."""
    import json
    from src.pipeline.gemini import GeminiBackend

    whole = json.dumps({"segments": [
        {"speaker": "SPEAKER 1", "start": "00:00", "end": f"{i // 60:02d}:{i % 60:02d}",
         "text": f"Line {i}."} for i in range(1, 90)]})

    class Cut:
        class files:
            @staticmethod
            def upload(file): raise AssertionError("inline expected")
        class interactions:
            @staticmethod
            def create(**kw):
                class R: output_text = whole[:3000]
                return R()

    import pathlib, tempfile
    audio = pathlib.Path(tempfile.mkdtemp()) / "m.mp3"
    audio.write_bytes(b"ID3" + b"\x01" * 256)
    out = GeminiBackend(client=Cut()).transcribe(audio, "audio/mpeg")
    assert 0 < len(out.segments) < 89
    assert out.note and "cut off" in out.note
    assert "Re-run" in out.note


def test_the_request_carries_a_schema_so_malformed_json_is_impossible():
    import json, pathlib, tempfile
    from src.pipeline.gemini import GeminiBackend, TRANSCRIPT_SCHEMA
    seen = {}

    class Fake:
        class files:
            @staticmethod
            def upload(file): raise AssertionError("inline expected")
        class interactions:
            @staticmethod
            def create(**kw):
                seen.update(kw)
                class R: output_text = json.dumps({"segments": [
                    {"speaker": "SPEAKER 1", "start": "00:00", "end": "00:04", "text": "ok"}]})
                return R()

    audio = pathlib.Path(tempfile.mkdtemp()) / "m.mp3"
    audio.write_bytes(b"ID3" + b"\x02" * 128)
    GeminiBackend(client=Fake()).transcribe(audio, "audio/mpeg")

    fmt = seen["response_format"]
    assert fmt["type"] == "text"
    assert fmt["mime_type"] == "application/json"
    assert fmt["schema"] == TRANSCRIPT_SCHEMA
    assert seen["generation_config"]["max_output_tokens"] >= 8192
    # response_mime_type on its own is what produced
    # "responseFormat must be set when responseMimeType is set".
    assert "response_mime_type" not in seen


def test_a_rejected_request_key_costs_a_retry_not_the_transcription():
    """The audio has already been uploaded by this point. A wrong guess about the
    request's shape must never be what loses the meeting."""
    import json, pathlib, tempfile
    from src.pipeline.gemini import GeminiBackend
    calls = []

    class Picky:
        class files:
            @staticmethod
            def upload(file): raise AssertionError("inline expected")
        class interactions:
            @staticmethod
            def create(**kw):
                calls.append(sorted(kw))
                if "response_format" in kw or "generation_config" in kw:
                    raise RuntimeError(
                        "Error code: 400 - {'error': {'code': 'invalid_request'}}")
                class R: output_text = json.dumps({"segments": [
                    {"speaker": "SPEAKER 1", "start": "00:00", "end": "00:07",
                     "text": "recovered anyway"}]})
                return R()

    audio = pathlib.Path(tempfile.mkdtemp()) / "m.mp3"
    audio.write_bytes(b"ID3" + b"\x03" * 128)
    backend = GeminiBackend(client=Picky())
    out = backend.transcribe(audio, "audio/mpeg")

    assert len(calls) == 2, "one constrained attempt, one plain retry"
    assert calls[1] == ["input", "model"], "the retry is the minimum request"
    assert out.segments[0].text == "recovered anyway"
    assert backend.degraded and "invalid_request" in backend.degraded


def test_a_real_failure_is_not_retried_and_not_swallowed():
    """Only request-shape rejections are worth a second call. Retrying a rate
    limit or an auth failure just uploads the audio twice."""
    import pathlib, tempfile
    from src.pipeline.gemini import GeminiBackend
    calls = []

    class Broken:
        class files:
            @staticmethod
            def upload(file): raise AssertionError("inline expected")
        class interactions:
            @staticmethod
            def create(**kw):
                calls.append(kw)
                raise RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")

    audio = pathlib.Path(tempfile.mkdtemp()) / "m.mp3"
    audio.write_bytes(b"ID3" + b"\x04" * 128)
    try:
        GeminiBackend(client=Broken()).transcribe(audio, "audio/mpeg")
        raise AssertionError("should have raised")
    except RuntimeError as exc:
        assert "429" in str(exc)
    assert len(calls) == 1, "a rate limit must not be retried"


# ---------------------------------------------------- long audio and speakers
def test_windows_cover_the_whole_recording_and_overlap():
    from src.pipeline.chunking import plan
    from src.config import config
    window = config.CHUNK_MINUTES * 60_000
    overlap = config.CHUNK_OVERLAP_SECONDS * 1000

    assert plan(10 * 60_000) == [(0, 10 * 60_000)], "short audio is not split"

    total = 52 * 60_000
    windows = plan(total)
    assert len(windows) >= 3
    assert windows[0][0] == 0
    assert windows[-1][0] + windows[-1][1] == total, "the end must be covered"
    for (a_off, a_len), (b_off, _b_len) in zip(windows, windows[1:]):
        assert b_off < a_off + a_len, "consecutive windows must overlap"
        assert (a_off + a_len) - b_off >= overlap - 1, "overlap must be big enough to match on"
        assert a_len <= window, "no window may exceed the diarization limit"


def test_labels_are_carried_across_a_join_by_matching_the_repeated_speech():
    """Each window is diarized independently, so window 2's SPEAKER 1 is a
    different person from window 1's. The overlap is what identifies them."""
    from src.pipeline.base import Segment
    from src.pipeline.stitch import join

    first = [
        Segment("SPEAKER 1", 0, 10_000, "Let us start with where the quarter landed."),
        Segment("SPEAKER 2", 10_000, 20_000, "Revenue came in four percent under forecast."),
        Segment("SPEAKER 1", 20_000, 30_000, "And the integration timeline with Halcyon."),
        Segment("SPEAKER 2", 30_000, 40_000, "Their staging does not support webhook retries."),
    ]
    # The second window heard the same last two turns, but numbered the voices
    # the other way round.
    second = [
        Segment("SPEAKER 2", 20_000, 30_000, "And the integration timeline with Halcyon."),
        Segment("SPEAKER 1", 30_000, 40_000, "Their staging does not support webhook retries."),
        Segment("SPEAKER 1", 40_000, 50_000, "So we move the date and say so in writing."),
        Segment("SPEAKER 2", 50_000, 60_000, "Agreed. I will send the revised scope."),
    ]

    merged = join([(0, first), (20_000, second)], overlap_ms=20_000)
    times = [s.start_ms for s in merged]
    assert times == sorted(times) and len(times) == len(set(times)), "no duplicated speech"
    by_time = {s.start_ms: s.speaker_label for s in merged}
    assert by_time[40_000] == "SPEAKER 2", "the mapping must survive the join"
    assert by_time[50_000] == "SPEAKER 1"
    assert len({s.speaker_label for s in merged}) == 2, "two voices, not four"


def test_a_voice_only_in_the_later_window_becomes_a_new_speaker_not_a_wrong_one():
    from src.pipeline.base import Segment
    from src.pipeline.stitch import join
    first = [
        Segment("SPEAKER 1", 0, 10_000, "Opening remarks about the schedule."),
        Segment("SPEAKER 2", 10_000, 20_000, "A question about the reporting module."),
    ]
    second = [
        Segment("SPEAKER 1", 10_000, 20_000, "A question about the reporting module."),
        Segment("SPEAKER 2", 20_000, 30_000, "Someone who had not spoken until now."),
    ]
    merged = join([(0, first), (10_000, second)], overlap_ms=10_000)
    labels = [s.speaker_label for s in merged]
    assert labels[:2] == ["SPEAKER 1", "SPEAKER 2"]
    assert labels[2] not in ("SPEAKER 1", "SPEAKER 2"), "a third voice is a third label"


def test_a_long_recording_without_ffmpeg_says_so_instead_of_lying():
    """The collapse is silent: the transcript looks complete and is simply wrong
    after the limit. If it cannot be split, that has to be said out loud."""
    import pathlib, tempfile, json
    from src.pipeline import chunking, gemini

    audio = pathlib.Path(tempfile.mkdtemp()) / "long.mp3"
    audio.write_bytes(b"ID3" + b"\x09" * 512)

    class Fake:
        class files:
            @staticmethod
            def upload(file): raise AssertionError("inline expected")
        class interactions:
            @staticmethod
            def create(**kw):
                class R: output_text = json.dumps({"segments": [
                    {"speaker": "SPEAKER 1", "start": "00:00", "end": "00:05", "text": "hi"}]})
                return R()

    real_duration, real_have = chunking.duration_ms, chunking.have_ffmpeg
    chunking.duration_ms = lambda p: 52 * 60_000
    chunking.have_ffmpeg = lambda: False
    try:
        out = gemini.GeminiBackend(client=Fake()).transcribe(audio, "audio/mpeg")
    finally:
        chunking.duration_ms, chunking.have_ffmpeg = real_duration, real_have

    assert out.note and "ffmpeg" in out.note
    assert "52 minutes" in out.note


def test_end_to_end_windowing_prevents_the_collapse(tmp_path):
    """The whole path, with real ffmpeg cuts and a model that behaves the way the
    real one does: correct speakers inside the limit, one label past it.

    Without windowing this recording comes back as a monologue after the limit.
    With it, both voices survive to the end.
    """
    import json, shutil, subprocess, pytest
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg not available on this host")

    from src.config import config
    from src.pipeline import gemini, chunking

    audio = tmp_path / "long.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=60",
                    "-c:a", "libmp3lame", "-b:a", "32k", str(audio)], check=True)

    LIMIT_S = 20                      # pretend diarization dies after 20 seconds

    from src.pipeline.chunking import plan
    old_min, old_ovl = config.CHUNK_MINUTES, config.CHUNK_OVERLAP_SECONDS
    config.CHUNK_MINUTES = 0.25       # 15 second windows
    config.CHUNK_OVERLAP_SECONDS = 5
    windows = plan(60_000)
    assert len(windows) > 1, "the recording must actually be split for this test"
    pending = [length for _offset, length in windows]

    class Collapsing:
        """Transcribes exactly the audio it is handed, diarizing correctly for the
        first LIMIT_S of it and then emitting a single label -- which is the
        behaviour observed on the real thing. Each window starts its own clock at
        zero, as the real model does."""
        class files:
            @staticmethod
            def upload(file): raise AssertionError("inline expected")
        class interactions:
            @staticmethod
            def create(**kw):
                length_s = pending.pop(0) // 1000
                segs, t, turn = [], 0, 0
                while t < length_s:
                    speaker = f"SPEAKER {turn % 2 + 1}" if t < LIMIT_S else "SPEAKER 1"
                    segs.append({"speaker": speaker,
                                 "start": f"{t // 60:02d}:{t % 60:02d}",
                                 "end": f"{min(t + 5, length_s) // 60:02d}:"
                                        f"{min(t + 5, length_s) % 60:02d}",
                                 "text": f"Utterance {turn} of this window."})
                    t += 5
                    turn += 1
                class R: output_text = json.dumps({"segments": segs})
                return R()

    try:
        out = gemini.GeminiBackend(client=Collapsing()).transcribe(audio, "audio/mpeg")
    finally:
        config.CHUNK_MINUTES, config.CHUNK_OVERLAP_SECONDS = old_min, old_ovl

    assert out.note and "windows" in out.note
    late = [s for s in out.segments if (s.start_ms or 0) > 30_000]
    assert late, "the tail of the recording must be present"
    assert len({s.speaker_label for s in late}) > 1, \
        "attribution collapsed to one speaker despite windowing"
    times = [s.start_ms for s in out.segments]
    assert times == sorted(times), "segments must come out in order"


def test_an_unmeasurable_recording_says_so_rather_than_transcribing_blind():
    """Without ffprobe there is no way to know whether a recording needed
    splitting. Transcribing it whole and saying nothing is how a half-wrong
    transcript comes to look like a right one."""
    import pathlib, tempfile, json
    from src.pipeline import chunking, gemini

    audio = pathlib.Path(tempfile.mkdtemp()) / "unknown.mp3"
    audio.write_bytes(b"ID3" + b"\x0a" * 256)

    class Fake:
        class files:
            @staticmethod
            def upload(file): raise AssertionError("inline expected")
        class interactions:
            @staticmethod
            def create(**kw):
                class R: output_text = json.dumps({"segments": [
                    {"speaker": "SPEAKER 1", "start": "00:00", "end": "00:05", "text": "hi"}]})
                return R()

    real = chunking.duration_ms
    chunking.duration_ms = lambda p: None
    try:
        out = gemini.GeminiBackend(client=Fake()).transcribe(audio, "audio/mpeg")
    finally:
        chunking.duration_ms = real

    assert out.note, "an unmeasurable recording must carry a warning"
    assert "ffprobe" in out.note and "not trustworthy" in out.note


def test_two_different_warnings_about_one_recording_both_survive():
    """A truncated transcript on an unmeasurable file has two things worth
    saying. Writing one note over the other loses whichever came first."""
    import pathlib, tempfile, json
    from src.pipeline import chunking, gemini

    whole = json.dumps({"segments": [
        {"speaker": "SPEAKER 1", "start": "00:00", "end": "00:05", "text": f"Line {i}."}
        for i in range(60)]})

    class Cut:
        class files:
            @staticmethod
            def upload(file): raise AssertionError("inline expected")
        class interactions:
            @staticmethod
            def create(**kw):
                class R: output_text = whole[:1500]
                return R()

    audio = pathlib.Path(tempfile.mkdtemp()) / "m.mp3"
    audio.write_bytes(b"ID3" + b"\x0b" * 256)
    real = chunking.duration_ms
    chunking.duration_ms = lambda p: None
    try:
        out = gemini.GeminiBackend(client=Cut()).transcribe(audio, "audio/mpeg")
    finally:
        chunking.duration_ms = real

    assert "cut off" in out.note, "the truncation warning must survive"
    assert "ffprobe" in out.note, "the unmeasurable warning must survive"
