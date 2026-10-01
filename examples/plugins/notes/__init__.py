"""
Плагин notes.

Инициализируется при загрузке Homer. Может регистрировать
нотификаторы, обработчики событий, менять глобальные объекты.
"""

def plugin_init(context):
    """
    context содержит:
        config, root_dir
    """
    from lib.notify import REGISTRY
    # Пример: регистрация своего нотификатора
    # from .lib.notify import NotesNotifier
    # REGISTRY['notes'] = NotesNotifier
    pass


def plugin_disable(context):
    """Вызывается при выключении плагина (без удаления данных)."""
    pass


def plugin_uninstall(context):
    """Вызывается перед удалением данных (uninstall.sql выполняется отдельно)."""
    pass
