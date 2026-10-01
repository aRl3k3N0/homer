from lib.console import console, Color
import time

def execute(context):
    with console.multi_progress() as mp:
        download = mp.add(100, prefix='Скачивание', show_eta=True)
        unpack   = mp.add(50,  prefix='Распаковка', color=Color.BRIGHT_CYAN)
        index    = mp.add(200, prefix='Индексация', color=Color.BRIGHT_MAGENTA)

        for i in range(100):
            time.sleep(0.03)
            download.update()
            if i % 2 == 0:
                unpack.update()
            if i % 3 == 0:
                index.update(2)
            if i == 50:
                print("→ обработана половина")   # над барами

        with console.spinner('Установка зависимостей') as sp:
            time.sleep(1.5)
            sp.set_description('Сборка колеса')
            time.sleep(1.0)
            sp.set_description('Установка')
            time.sleep(0.8)
        print("✅ Зависимости установлены")

        return 0
