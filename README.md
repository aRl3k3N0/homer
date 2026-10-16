# Homer

[![CI](https://github.com/<user>/homer/actions/workflows/ci.yml/badge.svg)](https://github.com/<user>/homer/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/<user>/homer/branch/main/graph/badge.svg)](https://codecov.io/gh/<user>/homer)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-blue?logo=read-the-docs)](https://<user>.github.io/homer/)
[![Python](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

Консольный фреймворк для Python в стиле Laravel Artisan: cron-планировщик,
очередь задач, нотификаторы (email / telegram / slack / mattermost),
работа с Oracle / Postgres / SQLite, почта по шаблонам Jinja2
и красивый вывод в консоль.

## Документация

- [API на GitHub Pages](https://<user>.github.io/homer/)
- [Руководства](docs/index.md)
- [Примеры](examples/README.md)
- [Changelog](CHANGELOG.md)
- [Участие в разработке](CONTRIBUTING.md)

## Быстрый старт

```bash
git clone https://github.com/<user>/homer.git && cd homer
make install-dev
chmod +x homer

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .

./homer
./homer make:command --name=hello
./homer hello --name=Иван
./homer schedule:add --name=hello-hourly --command=hello --cron='0 * * * *'
./homer schedule:run --interval=30
