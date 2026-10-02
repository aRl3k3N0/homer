"""Тесты Mailer с file-транспортом (без реального SMTP)."""

from email import policy
from email.parser import BytesParser

import pytest

from lib.mailer import Mailer


@pytest.fixture
def mailer_setup(tmp_path):
    from lib.config import Config

    tpl_dir = tmp_path / 'email'
    tpl_dir.mkdir()
    (tpl_dir / 'welcome.subject').write_text('Привет, {{ user }}!', encoding='utf-8')
    (tpl_dir / 'welcome.txt').write_text('Добро пожаловать, {{ user }}!', encoding='utf-8')
    (tpl_dir / 'welcome.html').write_text('<p>Добро пожаловать, {{ user }}!</p>', encoding='utf-8')

    cfg_file = tmp_path / 'config.yml'
    cfg_file.write_text(
        f"""
mailer:
  transport: file
  templates_dir: {tpl_dir}
  from: noreply@example.com
  from_name: Homer
  file:
    dir: {tmp_path / 'mail'}
""",
        encoding='utf-8',
    )
    return Config(cfg_file), tpl_dir


def test_render(mailer_setup):
    cfg, tpl = mailer_setup
    m = Mailer(cfg, tpl)
    r = m.render('welcome', {'user': 'Иван'})
    assert 'Иван' in r['subject']
    assert 'Иван' in r['text']
    assert 'Иван' in r['html']


def test_send_writes_file(mailer_setup, tmp_path):
    cfg, tpl = mailer_setup
    m = Mailer(cfg, tpl)
    m.send(to='user@example.com', template_name='welcome', context={'user': 'Иван'})

    out = tmp_path / 'mail'
    files = list(out.glob('*.eml'))
    assert len(files) == 1
    with files[0].open('rb') as message_file:
        message = BytesParser(policy=policy.default).parse(message_file)
    body = '\n'.join(
        part.get_content() for part in message.walk() if part.get_content_type().startswith('text/')
    )
    assert 'Иван' in body


def test_list_templates(mailer_setup):
    cfg, tpl = mailer_setup
    m = Mailer(cfg, tpl)
    assert 'welcome' in m.list_templates()
