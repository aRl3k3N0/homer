# API: Config

Модуль `lib.config` — обёртка над `config.yml`.

## Импорт

```pycon
from lib.config import Config
```

## Создание

```pycon
mailer = Mailer(config, root_dir / 'email')
```

Второй аргумент — путь к шаблонам. Если не указать, берётся из ```mailer.templates_dir``` (по умолчанию ```email```).

## Транспорты

Задаётся через ```mailer.transport``` в конфиге:

| Транспорт      | Когда использовать                                                        |
|----------------|---------------------------------------------------------------------------|
| ```smtp```     | Стандартный SMTP. Полноценные multipart-письма, TLS/SSL.                  |
| ```mailx```    | Утилита ```mailx/nail```. Письмо как plain text (HTML не поддерживается). |
| ```sendmail``` | Локальный MTA через ```sendmail -t```.                                    |
| ```file```     | Пишет ```.eml``` в директорию — отладка.                                  |

## Отправка

```pycon
mailer.send(
    to='user@example.com',
    template_name='welcome',
    context={'user': 'Иван', 'version': '1.0'},
)
```

Полный набор параметров:

```pycon
mailer.send(
    to=['a@example.com', 'b@example.com'],  # может быть строка
    cc='manager@example.com',
    bcc='archive@example.com',
    reply_to='support@example.com',
    template_name='report',
    subject='Отчёт за март',                # переопределить тему
    context={'period': 'март', 'total': 100},
    attachments=['/path/to/report.pdf'],
    from_addr='noreply@example.com',
    from_name='Homer',
)
```

## Рендер без отправки

```pycon
rendered = mailer.render('welcome', {'user': 'Иван'})
rendered['subject']   # тема
rendered['html']      # HTML-тело
rendered['text']      # text-тело
```

## Шаблоны

Каталог ```email/```:

```
email/
├── base.html
├── welcome.subject
├── welcome.html
├── welcome.txt
├── notifications/
│   ├── job_ok.subject
│   ├── job_ok.html
│   ├── job_ok.txt
│   ├── job_failed.subject
│   ├── job_failed.html
│   └── job_failed.txt
```

* ```<name>.subject``` — тема (обязателен, если не переопределять ```subject=```).
* ```<name>.html``` — HTML-версия.
* ```<name>.txt``` — текстовая версия.
* Хотя бы один из ```.html```/```.txt``` должен существовать.

## Jinja2

Если установлен ```Jinja2``` — шаблоны полноценные:

```html
{% extends "base.html" %}

{% block title %}Отчёт за {{ period }}{% endblock %}

{% block content %}
  <table>
  {% for row in rows %}
    <tr>
      <td>{{ row.name }}</td>
      <td>{{ row.value|num }}</td>
    </tr>
  {% endfor %}
  </table>
  {% if errors %}
    <p style="color:red">Ошибок: {{ errors }}</p>
  {% endif %}
{% endblock %}
```

Полезные встроенные фильтры и глобалы:

* ```{{ x|num }}``` — разделение тысяч пробелом.
* ```{{ dt|dt }}``` — дата ```%d.%m.%Y %H:%M```.
* ```{{ dt|dt('%Y-%m-%d') }}``` — свой формат.
* ```{{ app_name }}```, ```{{ app_version }}``` — из конфига.

Если ```Jinja2``` не установлен — работает упрощённый рендер: ```{{ key }}``` и ```{{ key|default }}```.

## Проверка

```bash
homer mail:check
```

Покажет транспорт, отправителя, папку шаблонов и список доступных шаблонов.

## Список шаблонов из кода

```pycon
for name in mailer.list_templates():
    print(name)   # 'welcome', 'notifications/job_ok', ...
```

## Ошибки

```MailError``` — общая ошибка (транспорт, шаблон, вложение).

## Пример: отправить отчёт

```pycon
from datetime import datetime
from lib.mailer import Mailer

def execute(context):
    mailer = Mailer(context['config'], context['root_dir'] / 'email')
    mailer.send(
        to='ops@example.com',
        template_name='report',
        context={
            'period': '2026-09',
            'total': 12840,
            'errors': 30,
            'generated_at': datetime.now(),
            'rows': [{'name': 'a', 'value': 100}, ...],
        },
        attachments=['/var/reports/2026-09.pdf'],
    )
    return 0
```
