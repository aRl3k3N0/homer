"""
Директория с командами Homer.

Каждая команда — это отдельный .py файл с функцией execute(context).
Имя команды формируется из пути:
  commands/idm/main.py       -> idm
  commands/cmdb/update.py    -> cmdb:update
  commands/report/daily.py   -> report:daily
"""