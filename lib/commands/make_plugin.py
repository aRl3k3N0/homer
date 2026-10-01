"""
make:plugin — сгенерировать скелет нового плагина Homer.

Создаёт:
    plugins/<name>/
        plugin.json
        __init__.py
        README.md
        commands/
            __init__.py
            hello.py
        lib/
            __init__.py
            helpers.py
        email/
            welcome.subject
            welcome.html
            welcome.txt
        langs/
            en.yml
            ru.yml
        templates/
            dashboard.html
        static/
            css/style.css
            js/plugin.js
        migrations/
            sqlite/
                001_init.sql
                uninstall.sql
            postgres/
                001_init.sql
                uninstall.sql
            mysql/
                001_init.sql
                uninstall.sql
"""
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from lib.console import console, Color

DESCRIPTION = "Создать скелет нового плагина"


def _slugify(name: str) -> str:
    s = name.strip().lower().replace('-', '_')
    s = re.sub(r'[^a-z0-9_]+', '_', s)
    s = re.sub(r'_+', '_', s).strip('_')
    return s


def _write(path: Path, content: str, executable: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    if executable:
        try:
            path.chmod(0o755)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
#                          ШАБЛОНЫ ФАЙЛОВ
# ═══════════════════════════════════════════════════════════════════

def _tpl_plugin_json(name: str, description: str, author: str) -> str:
    return json.dumps({
        'name': name,
        'version': '0.1.0',
        'description': description,
        'author': author,
        'homepage': '',
        'requires': [],
        'requires_homer': '>=1.0.0',
        'auto_migrate': True,
    }, ensure_ascii=False, indent=2) + '\n'


def _tpl_init(name: str) -> str:
    return f'''"""
Плагин {name}.

Точка входа Homer. Вызывается при загрузке Homer (plugin_init)
и при выключении/удалении (plugin_disable / plugin_uninstall).
"""


def plugin_init(context):
    """
    Инициализация плагина.

    context:
        config:   объект Config (config.yml)
        root_dir: Path к корню проекта

    Здесь можно:
        - регистрировать нотификаторы:   lib.notify.REGISTRY[...]
        - подписываться на события       (см. plugin_events в Homer)
        - инициализировать свои сервисы
    """
    # Пример: регистрация кастомного нотификатора
    #
    # from lib.notify import REGISTRY
    # from .lib.notifier import {name.title()}Notifier
    # REGISTRY['{name}'] = {name.title()}Notifier
    pass


def plugin_disable(context):
    """
    Вызывается при выключении плагина (без удаления данных).
    Откатите здесь всё, что навесили в plugin_init.
    """
    pass


def plugin_uninstall(context):
    """
    Вызывается перед удалением данных плагина
    (после подтверждения пользователя, до uninstall.sql).
    """
    pass
'''


def _tpl_readme(name: str, description: str) -> str:
    return f'''# Плагин `{name}`

{description}

## Установка

Плагин уже в `plugins/{name}/`. Включите его в `config.yml`:

```yaml
plugins:
  enabled: ["*"]      # все плагины
  # или явно:
  # enabled: ["{name}"]
```

Применить миграции:

```bash
./homer plugin:migrate --name={name}
```

## Команды

* ```./homer {name}:hello``` — пример команды.

## Структура

* ```commands/``` — команды Homer.
* ```lib/``` — вспомогательные модули.
* ```email/``` — шаблоны писем (Jinja2).
* ```langs/``` — переводы (YAML).
* ```templates/``` — Jinja-шаблоны для Web UI.
* ```static/``` — CSS/JS/картинки для Web UI (доступны в ```/static/plugins/{name}/```).
* ```migrations/``` — миграции БД по драйверам, ```uninstall.sql``` — при удалении.
'''
def _tpl_command_hello(name: str) -> str:
    return f'''"""
{name}:hello — пример команды плагина.
"""
from lib.console import console
from lib.i18n import t

DESCRIPTION = "Пример команды плагина"

def execute(context):
    args = context['args']
    who = args.get('name', 'world')

    # Мультиязычный вывод
    greeting = t('{name}.hello', who=who)

    console.success(greeting)
    context['logger'].info(f"hello from plugin {name}: {{who}}",
    command=context['command_name'])
    return 0
'''

def _tpl_lib_helpers(name: str) -> str:
    return f'''"""
Вспомогательные функции плагина {name}.
"""

def format_greeting(who: str) -> str:
    return f"Hello, {{who}}!"
'''

def _tpl_email_subject(name: str) -> str:
    return f'{{{name}.subject}}\n'

def _tpl_email_html(name: str) -> str:
    return f'''{{% extends "base.html" %}}
{{% block title %}}Плагин {name}{{% endblock %}}
{{% block content %}}

<p>{{{{ _('{name}.hello', who=user) }}}}</p> <p>Это письмо от плагина <b>{name}</b>.</p> {{% endblock %}} '''

def _tpl_email_txt(name: str) -> str:
    return f'''{{{{ _('{name}.hello', who=user) }}}}

--
Плагин {name}
'''

def _tpl_lang_en(name: str) -> str:
    return f'''{name}:
hello: "Hello, {{who}}!"
errors:
    required: "Required parameter is missing"
'''

def _tpl_lang_ru(name: str) -> str:
    return f'''{name}:
hello: "Привет, {{who}}!"
errors:
    required: "Не указан обязательный параметр"
'''

def _tpl_template_dashboard(name: str) -> str:
    return f'''{{% extends "base.html" %}}
{{% block title %}}Плагин {name}{{% endblock %}}
{{% block content %}}

<div class="container"> <h2>{{{{ _('{name}.hello', who='Web UI') }}}}</h2> <p>Это страница плагина <b>{name}</b>.</p> <div id="{name}-data" class="mt-3"></div> </div><script src="/static/plugins/{name}/js/plugin.js" defer></script>
{{% endblock %}}
'''

def _tpl_static_css(name: str) -> str:
    return f'''/* Стили плагина {name} */
.{name}-container {{
padding: 1rem;
border-radius: 6px;
background: #f8f9fa;
}}
'''

def _tpl_static_js(name: str) -> str:
    return f'''/**

JS плагина {name}.
*/
(function () {{
const el = document.getElementById('{name}-data');
if (!el) return;

fetch('/api/plugins/{name}/ping')
.then(r => r.json())
.then(data => {{
el.innerHTML = '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
}})
.catch(err => {{
el.innerHTML = '<div class="text-danger">' + err + '</div>';
}});
}})();
'''

def _tpl_migration_init(name: str, driver: str) -> str:
    if driver == 'sqlite':
        pk = 'INTEGER PRIMARY KEY AUTOINCREMENT'
        ts = 'TEXT'
    elif driver == 'postgres':
        pk = 'SERIAL PRIMARY KEY'
        ts = 'TIMESTAMP'
    elif driver == 'mysql':
        pk = 'INT AUTO_INCREMENT PRIMARY KEY'
        ts = 'DATETIME'
    elif driver == 'oracle':
        pk = 'NUMBER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY'
        ts = 'TIMESTAMP'
    else:
        pk = 'INTEGER PRIMARY KEY'
        ts = 'TIMESTAMP'

    return f'''-- Migration: 001_init ({driver})
-- Plugin: {name}
-- Created: {datetime.now().strftime('%Y-%m-%d %H:%M')}

CREATE TABLE IF NOT EXISTS {name}_data (
id {pk},
title VARCHAR(255) NOT NULL,
body TEXT,
created_at {ts} NOT NULL
);

CREATE INDEX IF NOT EXISTS {name}_data_created_idx
ON {name}_data (created_at);
'''

def _tpl_migration_uninstall(name: str, driver: str) -> str:
    return f'''-- Uninstall: удаляет данные плагина {name} ({driver})
-- Выполняется только при homer plugin:uninstall --name={name}

DROP TABLE IF EXISTS {name}_data;
'''

# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def execute(context):
    args = context['args']
    root = Path(context['root_dir'])

    raw_name = args.get('name') or args.get('_positional', [None])[0]
    if not raw_name:
        console.error(
        "Использование: homer make:plugin --name=my_plugin "
        "[--description='...'] [--author='...']"
        )
        return 1

    name = _slugify(raw_name)
    if not name or not name[0].isalpha():
        console.error(f"Некорректное имя плагина: {raw_name!r}")
        return 1

    description = args.get('description') or f"Плагин {name}"
    author = args.get('author') or 'Homer user'
    force = bool(args.get('force', False))
    drivers_arg = args.get('drivers')
    if drivers_arg:
        drivers = [d.strip() for d in str(drivers_arg).split(',') if d.strip()]
    else:
        drivers = ['sqlite', 'postgres', 'mysql']

    plugin_dir = root / 'plugins' / name
    if plugin_dir.exists() and not force:
        console.error(f"Плагин уже существует: {plugin_dir}")
        console.comment("Используйте --force для перезаписи")
        return 1

    if plugin_dir.exists() and force:
        shutil.rmtree(plugin_dir)

    console.section(f"Создание плагина {name}")
    console.key_value('Путь', str(plugin_dir.relative_to(root)))
    console.key_value('Описание', description)
    console.key_value('Драйверы миграций', ', '.join(drivers))

    #─── Базовые файлы ───
    _write(plugin_dir / 'plugin.json',
    _tpl_plugin_json(name, description, author))
    _write(plugin_dir / 'init.py', _tpl_init(name))
    _write(plugin_dir / 'README.md', _tpl_readme(name, description))

    #─── Команды ───
    _write(plugin_dir / 'commands' / 'init.py',
    '"""Команды плагина."""\n')
    _write(plugin_dir / 'commands' / 'hello.py', _tpl_command_hello(name))

    #─── lib ───
    _write(plugin_dir / 'lib' / 'init.py',
    f'"""Библиотеки плагина {name}."""\n')
    _write(plugin_dir / 'lib' / 'helpers.py', _tpl_lib_helpers(name))

    #─── email ───
    _write(plugin_dir / 'email' / 'welcome.subject', _tpl_email_subject(name))
    _write(plugin_dir / 'email' / 'welcome.html', _tpl_email_html(name))
    _write(plugin_dir / 'email' / 'welcome.txt', _tpl_email_txt(name))

    #─── langs ───
    _write(plugin_dir / 'langs' / 'en.yml', _tpl_lang_en(name))
    _write(plugin_dir / 'langs' / 'ru.yml', _tpl_lang_ru(name))

    #─── templates ───
    _write(plugin_dir / 'templates' / 'dashboard.html',
    _tpl_template_dashboard(name))

    #─── static ───
    _write(plugin_dir / 'static' / 'css' / 'style.css', _tpl_static_css(name))
    _write(plugin_dir / 'static' / 'js' / 'plugin.js', _tpl_static_js(name))

    #─── migrations ───
    for driver in drivers:
        d = plugin_dir / 'migrations' / driver
        _write(d / '001_init.sql', _tpl_migration_init(name, driver))
        _write(d / 'uninstall.sql', _tpl_migration_uninstall(name, driver))

    #─── .gitignore для pycache ───
    _write(plugin_dir / '.gitignore',
    'pycache/\n.pyc\n.pyo\n.cache/\n')

    console.newline()
    console.success(f"Плагин {console.bold(name)} создан")

    #─── Что дальше ───
    console.section("Дальнейшие шаги")
    console.list_item('1. Включить', 'в config.yml: plugins.enabled: ["*"] '
    f'или [{name}]')
    console.list_item('2. Проверить', f'homer plugin:check --name={name}')
    console.list_item('3. Применить миграции', f'homer plugin:migrate --name={name}')
    console.list_item('4. Запустить команду', f'homer {name}:hello --name=Иван')
    console.list_item('5. Посмотреть инфо', f'homer plugin:info --name={name}')
    return 0
