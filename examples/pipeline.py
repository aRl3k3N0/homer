from lib.console import console
import time

def execute(context):
    with console.task_tree('Деплой релиза', transient=False) as tree:
        with tree.task('Скачивание артефактов', total=10, show_eta=True) as t:
            for _ in range(10):
                time.sleep(0.05)
                t.update()

        with tree.task('Распаковка', total=5) as t:
            for _ in range(5):
                time.sleep(0.1)
                t.update()

        # Вложенная задача-родитель с дочерними
        with tree.task('Сборка', total=20) as parent:
            with tree.task('Компиляция', total=15, parent=parent._id) as c:
                for _ in range(15):
                    time.sleep(0.05)
                    c.update()
                    parent.update()
            with tree.task('Линковка', total=5, parent=parent._id) as l:
                for _ in range(5):
                    time.sleep(0.1)
                    l.update()
                    parent.update()

        tree.task_done('Тесты (пропущено — кеш)', status='skipped')
        tree.task_done('Миграции БД', status='done')
        tree.task_done('Прогрев кеша', status='warning',
                       error='2 ключа не удалось прогреть')

    print("✅ Деплой завершён")
    return 0
