"""Тесты Config."""
from lib.config import Config


def test_get_simple(tmp_path):
    f = tmp_path / 'c.yml'
    f.write_text('app:\n  name: Homer\n  version: 1.2\n', encoding='utf-8')
    c = Config(f)
    assert c.get('app.name') == 'Homer'
    assert c.get('app.version') == 1.2


def test_get_default(tmp_path):
    f = tmp_path / 'c.yml'
    f.write_text('app:\n  name: Homer\n', encoding='utf-8')
    c = Config(f)
    assert c.get('missing', 'def') == 'def'
    assert c.get('app.missing', 42) == 42


def test_missing_file(tmp_path):
    c = Config(tmp_path / 'nope.yml')
    assert c.get('any', 'x') == 'x'


def test_contains(tmp_path):
    f = tmp_path / 'c.yml'
    f.write_text('a: 1\n', encoding='utf-8')
    c = Config(f)
    assert 'a' in c
    assert 'b' not in c