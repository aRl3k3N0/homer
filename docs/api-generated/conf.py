"""
Конфигурация Sphinx для автогенерации API-документации Homer.

Источники — docstrings в lib/. Каждый модуль — своя .rst-страница
(см. docs/api-generated/modules/*.rst). Сборка: make docs.

Тема — Read the Docs. Markdown-файлы подключаются через myst-parser.
"""
import os
import sys
from pathlib import Path

# Добавляем корень проекта в sys.path, чтобы Sphinx видел пакет `lib`
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# ─── Метаданные проекта ───
project = 'Homer'
author = 'Homer contributors'
copyright = '2026, Homer contributors'
release = '1.0.0'
version = '1.0'

# ─── Общие настройки ───
extensions = [
    'sphinx.ext.autodoc',        # автодок из docstrings
    'sphinx.ext.autosummary',    # сводные таблицы модулей/классов
    'sphinx.ext.napoleon',       # Google/NumPy docstrings
    'sphinx.ext.viewcode',       # ссылка «[source]» на исходник
    'sphinx.ext.intersphinx',    # ссылки на Python docs
    'sphinx.ext.todo',           # .. todo:: директивы
    'myst_parser',               # поддержка Markdown
]

autosummary_generate = True
autodoc_default_options = {
    'members': True,
    'undoc-members': False,
    'show-inheritance': True,
    'special-members': '__init__, __enter__, __exit__',
    'exclude-members': '__weakref__, __dict__, __module__',
}
autodoc_typehints = 'description'
autodoc_member_order = 'bysource'
autodoc_class_signature = 'separated'
autodoc_preserve_defaults = True

napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
napoleon_use_rtype = False

# ─── Markdown через myst-parser ───
source_suffix = {
    '.rst': 'restructuredtext',
    '.md': 'markdown',
}
myst_enable_extensions = [
    'colon_fence',
    'deflist',
    'fieldlist',
    'tasklist',
]
myst_heading_anchors = 3

# ─── Ссылки на Python-стандартную библиотеку ───
intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
}

# ─── Внешний вид ───
html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
html_title = 'Homer API'
html_short_title = 'Homer'
html_theme_options = {
    'navigation_depth': 4,
    'collapse_navigation': False,
    'sticky_navigation': True,
    'includehidden': True,
    'titles_only': False,
}
html_context = {
    'display_github': False,
}

# ─── Прочее ───
templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']
todo_include_todos = True
nitpicky = False
suppress_warnings = [
    'ref.python',       # не ругаться на неразрешённые Python-ссылки
    'misc.highlighting_failure',
]

# Подавить предупреждения от модулей, зависящих от внешних библиотек
autodoc_mock_imports = [
    'cx_Oracle',
    'psycopg2',
    'jinja2',
    'requests',
]
