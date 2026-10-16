"""Тесты ArgumentParser."""

from homer.core.arguments import ArgumentParser


def test_parse_simple():
    p = ArgumentParser()
    p.parse(['hello', '--name=Иван', '--count=3'])
    assert p.command == 'hello'
    assert p.options['name'] == 'Иван'
    assert p.options['count'] == 3


def test_parse_flags():
    p = ArgumentParser()
    p.parse(['cmd', '--dry-run', '--verbose'])
    assert p.options['dry-run'] is True
    assert p.options['verbose'] is True


def test_parse_types():
    p = ArgumentParser()
    p.parse(['cmd', '--i=42', '--f=3.14', '--b=true', '--s=text'])
    assert p.options['i'] == 42
    assert p.options['f'] == 3.14
    assert p.options['b'] is True
    assert p.options['s'] == 'text'


def test_positional():
    p = ArgumentParser()
    p.parse(['cmd', 'foo', 'bar'])
    assert p.options['_positional'] == ['foo', 'bar']


def test_empty():
    p = ArgumentParser()
    p.parse([])
    assert p.command is None
