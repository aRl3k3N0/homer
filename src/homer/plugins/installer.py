"""
Установка плагинов из архива или URL.

Поддерживаемые источники:
    - локальный файл .zip / .tar.gz / .tgz
    - HTTP(S) URL с архивом
    - git URL (git+, https://... .git) — через subprocess git

Что делает:
    1. Скачивает/копирует архив во временный каталог.
    2. Распаковывает, определяет корень плагина
       (может быть вложен в один каталог верхнего уровня).
    3. Проверяет наличие plugin.json, читает имя и версию.
    4. Валидирует структуру.
    5. Копирует в plugins/<name>.
    6. Опционально — включает в config.yml (plugins.enabled).
    7. Опционально — применяет миграции.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from logging import root
from pathlib import Path
import shutil
import subprocess
import tarfile
from typing import Optional
import urllib.parse
import urllib.request
import zipfile

from homer.core import console


class InstallError(Exception):
    pass


@dataclass
class InstallResult:
    name: str
    version: str
    path: Path
    source: str


class PluginInstaller:
    def __init__(self, root_dir: Path, config=None):
        self.root = Path(root_dir)
        self.plugins_dir = self.root / 'plugins'
        self.config = config
        self.plugins_dir.mkdir(exist_ok=True)

    # ─────────── Публичный API ───────────

    def install(
        self,
        source,
        *,
        force=False,
        enable=False,
        migrate=False,
        expected_name=None,
        expected_checksum=None,
        verify=False,
        allow_unsigned=True,
        info=None,
    ) -> InstallResult:
        ...
        # После распаковки и определения info.name:
        if expected_checksum:
            # Считаем sha256 от файла
            if source.startswith(('http://', 'https://')):
                # Файл уже скачан во временный каталог
                archive = self._last_archive
            else:
                archive = Path(source)
            actual = 'sha256:' + hashlib.sha256(archive.read_bytes()).hexdigest()
            if actual != expected_checksum:
                raise InstallError(
                    f"Checksum не совпадает:\n  ожидался: {expected_checksum}\n  получен:  {actual}"
                )

        # Подпись (см. раздел «Signed plugins»)
        if verify:
            from homer.plugins.signing import SignatureError, TrustStore

            store = TrustStore(self.root, self.config)
            try:
                sig = store.verify(root)
            except SignatureError as e:
                if allow_unsigned:
                    console.warning(f"Плагин '{info.name}' не подписан")
                else:
                    raise InstallError(f"Подпись не найдена: {e}")
            else:
                if not sig.valid:
                    raise InstallError(f"Подпись недействительна: {sig.error}")
                if not sig.trusted:
                    raise InstallError(f"Ключ '{sig.key_id}' не в списке доверенных")

    def uninstall(
        self, name: str, *, purge_data: bool = False, driver: Optional[str] = None, db=None
    ) -> bool:
        """
        Удаляет плагин из plugins/.
        Если purge_data=True и передан db — прогоняет uninstall.sql.
        """
        target = self.plugins_dir / name
        if not target.exists():
            raise InstallError(f"Плагин '{name}' не установлен")

        if purge_data and db and driver:
            from homer.plugins.migrations import MigrationRunner
            from homer.plugins.plugin import PluginInfo

            info = PluginInfo.from_dir(target)
            runner = MigrationRunner(info, driver, db)
            runner.down_all()

        shutil.rmtree(target)
        return True

    # ─────────── Источники ───────────

    @staticmethod
    def _is_url(s: str) -> bool:
        return s.startswith(('http://', 'https://'))

    @staticmethod
    def _is_git_url(s: str) -> bool:
        return s.startswith(('git+', 'git@')) or s.endswith('.git')

    def _fetch_url(self, url: str, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        # Определяем имя файла из URL
        parsed = urllib.parse.urlparse(url)
        filename = Path(parsed.path).name or 'plugin.zip'
        out = dest_dir / filename

        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                out.write_bytes(resp.read())
        except Exception as e:
            raise InstallError(f"Скачивание {url}: {e}") from e
        return out

    def _fetch_git(self, url: str, dest_dir: Path) -> Path:
        if url.startswith('git+'):
            url = url[4:]
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / 'repo'

        cmd = ['git', 'clone', '--depth=1', url, str(target)]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=180,
                text=True,
            )
        except FileNotFoundError:
            raise InstallError("git не установлен")
        except subprocess.TimeoutExpired:
            raise InstallError(f"git clone timed out: {url}")

        if proc.returncode != 0:
            raise InstallError(f"git clone {url}: {proc.stderr.strip()}")

        # Удаляем .git
        shutil.rmtree(target / '.git', ignore_errors=True)
        return target

    def _extract(self, archive: Path, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)

        name_lower = archive.name.lower()
        try:
            if name_lower.endswith('.zip'):
                with zipfile.ZipFile(archive) as z:
                    self._safe_extract_zip(z, dest_dir)
            elif name_lower.endswith(('.tar.gz', '.tgz', '.tar.bz2', '.tar')):
                with tarfile.open(archive) as t:
                    self._safe_extract_tar(t, dest_dir)
            else:
                raise InstallError(f"Неподдерживаемый формат архива: {archive.name}")
        except zipfile.BadZipFile as e:
            raise InstallError(f"Повреждённый zip: {e}") from e
        except tarfile.TarError as e:
            raise InstallError(f"Повреждённый tar: {e}") from e

        return dest_dir

    @staticmethod
    def _safe_extract_zip(z: zipfile.ZipFile, dest: Path):
        """Защита от zip-slip."""
        for member in z.infolist():
            m_path = (dest / member.filename).resolve()
            if not str(m_path).startswith(str(dest.resolve())):
                raise InstallError(f"Небезопасный путь в архиве: {member.filename}")
        z.extractall(dest)

    @staticmethod
    def _safe_extract_tar(t: tarfile.TarFile, dest: Path):
        for member in t.getmembers():
            m_path = (dest / member.name).resolve()
            if not str(m_path).startswith(str(dest.resolve())):
                raise InstallError(f"Небезопасный путь в архиве: {member.name}")
        t.extractall(dest)

    # ─────────── Поиск корня плагина ───────────

    def _find_plugin_root(self, path: Path) -> Path:
        """
        Если в корне есть plugin.json — это корень.
        Иначе, если есть ровно один подкаталог с plugin.json —
        спускаемся в него.
        Иначе — ищем plugin.json в глубине до 2 уровней.
        """
        if (path / 'plugin.json').exists():
            return path

        children = [c for c in path.iterdir() if c.is_dir() and not c.name.startswith(('.', '_'))]
        if len(children) == 1:
            child = children[0]
            if (child / 'plugin.json').exists():
                return child

        # Глубже
        for c in path.rglob('plugin.json'):
            return c.parent

        raise InstallError("В архиве не найден plugin.json")

    # ─────────── Включение в config.yml ───────────

    def _enable_in_config(self, plugin_name: str):
        if self.config is None:
            return
        import yaml

        cfg_path = self.root / 'config.yml'
        data = self.config.all()
        plugins_cfg = data.setdefault('plugins', {})
        enabled = plugins_cfg.get('enabled') or []
        if enabled == ['*'] or enabled == '*':
            return  # уже все включены
        enabled_set = set(enabled)
        enabled_set.add(plugin_name)
        plugins_cfg['enabled'] = sorted(enabled_set)
        cfg_path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding='utf-8',
        )

    # ─────────── Миграции ───────────

    def _run_migrations(self, plugin_name: str):
        from homer.db import connect
        from homer.plugins.migrations import MigrationRunner
        from homer.plugins.plugin import PluginInfo

        sched_cfg = (self.config.get('scheduler', {}) or {}) if self.config else {}
        driver = sched_cfg.get('storage', 'sqlite')
        conn_cfg = sched_cfg.get(driver) or (
            self.config.get(f'databases.{driver}') if self.config else None
        )
        if driver == 'sqlite':
            if not conn_cfg:
                conn_cfg = {'path': 'var/scheduler.db'}
            elif 'path' not in conn_cfg:
                conn_cfg = dict(conn_cfg, path='var/scheduler.db')

        db = connect(driver, conn_cfg)
        try:
            target = self.plugins_dir / plugin_name
            info = PluginInfo.from_dir(target)
            mig_dir = info.migrations_for(driver)
            if not mig_dir:
                return
            runner = MigrationRunner(info, driver, db)
            runner.up()
        finally:
            db.close()
