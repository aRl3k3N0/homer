"""
Простая i18n-подсистема Homer.

- Загружает YAML-файлы из корневого langs/ и langs/ каждого плагина.
- Формат: вложенные ключи через точку: 'webui.jobs.title'.
- Поддерживает форматирование: t('mail.welcome.subject', user='Иван').
- Fallback: если ключа нет в текущей локали — берём из fallback_locale
  (по умолчанию 'en').
"""
from .manager import I18n, get_i18n, set_locale, t

__all__ = ['I18n', 'get_i18n', 'set_locale', 't']
