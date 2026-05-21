"""Unit tests for file-based command fallback."""

from pathlib import Path
from unittest.mock import MagicMock

from icloud_docker.control.file_watch import FileCommandWatcher


class TestFileCommandWatcher:
    """Test file-based command watcher."""

    def test_pause_command(self, tmp_path):
        cmd_file = tmp_path / "commands.txt"
        cmd_file.write_text("pause\n")

        engine = MagicMock()
        watcher = FileCommandWatcher(cmd_file, engine=engine)

        result = watcher.check_commands()
        assert result == "pause"
        engine.pause.assert_called_once()
        assert cmd_file.read_text() == ""  # Cleared

    def test_resume_command(self, tmp_path):
        cmd_file = tmp_path / "commands.txt"
        cmd_file.write_text("resume\n")

        engine = MagicMock()
        watcher = FileCommandWatcher(cmd_file, engine=engine)

        result = watcher.check_commands()
        assert result == "resume"
        engine.resume.assert_called_once()

    def test_sync_command(self, tmp_path):
        cmd_file = tmp_path / "commands.txt"
        cmd_file.write_text("sync\n")

        engine = MagicMock()
        watcher = FileCommandWatcher(cmd_file, engine=engine)

        result = watcher.check_commands()
        assert result == "sync"
        engine.sync_now.assert_called_once()

    def test_unknown_command_cleared(self, tmp_path):
        cmd_file = tmp_path / "commands.txt"
        cmd_file.write_text("unknown_cmd\n")

        engine = MagicMock()
        watcher = FileCommandWatcher(cmd_file, engine=engine)

        result = watcher.check_commands()
        assert result is None
        assert cmd_file.read_text() == ""

    def test_empty_file_noop(self, tmp_path):
        cmd_file = tmp_path / "commands.txt"
        cmd_file.write_text("")

        engine = MagicMock()
        watcher = FileCommandWatcher(cmd_file, engine=engine)

        result = watcher.check_commands()
        assert result is None

    def test_nonexistent_file_noop(self, tmp_path):
        cmd_file = tmp_path / "nonexistent.txt"

        engine = MagicMock()
        watcher = FileCommandWatcher(cmd_file, engine=engine)

        result = watcher.check_commands()
        assert result is None

    def test_multiline_file_executes_first(self, tmp_path):
        cmd_file = tmp_path / "commands.txt"
        cmd_file.write_text("pause\nresume\nsync\n")

        engine = MagicMock()
        watcher = FileCommandWatcher(cmd_file, engine=engine)

        result = watcher.check_commands()
        assert result == "pause"
        engine.pause.assert_called_once()
        engine.resume.assert_not_called()

    def test_case_insensitive(self, tmp_path):
        cmd_file = tmp_path / "commands.txt"
        cmd_file.write_text("PAUSE\n")

        engine = MagicMock()
        watcher = FileCommandWatcher(cmd_file, engine=engine)

        result = watcher.check_commands()
        assert result == "pause"
        engine.pause.assert_called_once()
