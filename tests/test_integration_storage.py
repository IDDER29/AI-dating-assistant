"""
Integration tests for the storage layer.
Uses real temporary files — verifies atomicity, corruption handling, and pruning.
"""
import datetime
import importlib
import json
import os
import pytest
from pathlib import Path
from state import BotState


def test_save_and_load_roundtrip(tmp_path):
    from storage import save_json_data, load_json_data

    data = {"12345": [{"role": "user", "parts": ["hello"], "timestamp": "2026-06-04T12:00:00+00:00"}]}
    filepath = tmp_path / "histories.json"

    save_json_data(filepath, data)
    loaded = load_json_data(filepath, {})

    assert loaded == data
    assert loaded["12345"][0]["role"] == "user"


def test_atomic_write_calls_fsync(tmp_path, monkeypatch):
    """save_json_data must fsync before rename to guarantee durability."""
    from storage import save_json_data

    fsync_called = []
    original = os.fsync

    def patched_fsync(fd):
        fsync_called.append(fd)
        original(fd)

    monkeypatch.setattr(os, "fsync", patched_fsync)

    filepath = tmp_path / "test.json"
    save_json_data(filepath, {"key": "value"})

    assert fsync_called, "os.fsync was not called — write is not durable"
    assert filepath.exists()
    assert not filepath.with_suffix(".tmp").exists()


def test_no_tmp_file_left_on_success(tmp_path):
    from storage import save_json_data

    filepath = tmp_path / "test.json"
    save_json_data(filepath, {"ok": True})

    tmp = filepath.with_suffix(".tmp")
    assert not tmp.exists(), ".tmp file was not cleaned up after successful write"


def test_corrupt_file_backed_up(tmp_path):
    """A corrupt JSON file must be renamed to .corrupt.*.json, not silently overwritten."""
    from storage import load_json_data

    corrupt = tmp_path / "test.json"
    corrupt.write_text("{{broken{{", encoding="utf-8")

    result = load_json_data(corrupt, {"default": True})

    assert result == {"default": True}
    backups = list(tmp_path.glob("*.corrupt.*.json"))
    assert len(backups) == 1, f"Expected 1 backup file, got: {backups}"
    # Backup must contain the original corrupt content
    assert "broken" in backups[0].read_text(encoding="utf-8", errors="replace")
    # The original path gets recreated with default data by load_json_data — that is correct
    # (the corrupt data is preserved in the backup, not silently destroyed)


def test_unicode_decode_error_backed_up(tmp_path):
    """A file with invalid UTF-8 bytes is backed up, not silently overwritten."""
    from storage import load_json_data

    bad_file = tmp_path / "test.json"
    bad_file.write_bytes(b"\xff\xfe{invalid utf-8}")

    result = load_json_data(bad_file, {"fallback": True})

    assert result.get("fallback") is True
    backups = list(tmp_path.glob("*.corrupt.*.json"))
    assert len(backups) == 1


def test_prune_stale_removes_old_entries():
    """Conversations older than max_age_days are removed; recent ones stay."""
    import datetime
    from storage import prune_stale_histories

    old_ts = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=100)
    ).isoformat()
    recent_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

    state = BotState()
    state.conversation_histories = {
        "old_user":    [{"role": "user", "parts": ["hi"],  "timestamp": old_ts}],
        "recent_user": [{"role": "user", "parts": ["hey"], "timestamp": recent_ts}],
    }

    pruned = prune_stale_histories(state, max_age_days=90)

    assert pruned == 1
    assert "old_user" not in state.conversation_histories
    assert "recent_user" in state.conversation_histories


def test_prune_empty_entry_removed():
    """Entries with no turns are pruned regardless of age."""
    from storage import prune_stale_histories

    state = BotState()
    state.conversation_histories = {
        "empty_user": [],
        "normal_user": [{"role": "user", "parts": ["hi"],
                         "timestamp": "2099-01-01T00:00:00+00:00"}],
    }

    pruned = prune_stale_histories(state, max_age_days=90)

    assert pruned == 1
    assert "empty_user" not in state.conversation_histories


def test_delete_user_data_removes_history_and_memory(tmp_path, monkeypatch):
    """delete_user_data removes history, memory, and rate-limit state."""
    from storage import delete_user_data
    import settings as s

    # Point storage paths to tmp_path
    monkeypatch.setattr(s, "HISTORY_PATH", tmp_path / "histories.json")
    monkeypatch.setattr(s, "MEMORY_PATH",  tmp_path / "memories.json")
    monkeypatch.setattr(s, "WHITELIST_PATH", tmp_path / "whitelist.json")

    # Re-import storage so it picks up the patched paths
    import storage
    importlib.reload(storage)

    state = BotState()
    state.conversation_histories["12345"] = [{"role": "user", "parts": ["hi"]}]
    state.conversation_memories["12345"] = "Anna likes hiking"
    state.last_reply_times[12345] = datetime.datetime.now(datetime.timezone.utc)
    state.meeting_signals_detected.add(12345)

    result = delete_user_data(state, 12345)

    assert "conversation_turns" in result
    assert result.get("memory") is True
    assert "12345" not in state.conversation_histories
    assert "12345" not in state.conversation_memories
    assert 12345 not in state.last_reply_times
    assert 12345 not in state.meeting_signals_detected

    # Reload storage to original paths so other tests are not affected
    importlib.reload(storage)
