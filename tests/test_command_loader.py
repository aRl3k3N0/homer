"""Тесты CommandLoader."""
from lib.command_loader import CommandLoader


def test_load_simple(sample_command_dir):
    loader = CommandLoader(sample_command_dir)
    commands = loader.load_commands()
    assert 'hello' in commands
    assert commands['hello']['description'] == 'Привет'


def test_load_nested(sample_command_dir):
    loader = CommandLoader(sample_command_dir)
    commands = loader.load_commands()
    assert 'report:daily' in commands


def test_empty_dir(tmp_path):
    loader = CommandLoader(tmp_path / 'nope')
    assert loader.load_commands() == {}