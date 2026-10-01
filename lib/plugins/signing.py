"""
Подпись и верификация плагинов через ed25519.

Зависимость: cryptography>=41
    pip install cryptography

Формат plugin.sig — JSON:
    {
      "algorithm": "ed25519",
      "key_id": "publisher@example.com",
      "signature": "<base64>",
      "signed_files_checksum": "<hex sha256>",
      "signed_at": "2026-09-22T12:00:00Z"
    }

Что подписывается:
    canonical_string = \
        "plugin.json\n" + sha256(plugin.json) + "\n" +
        "files\n" +
        для каждого файла (отсортированного по rel-пути):
            rel_path + "\n" + sha256(file) + "\n"

Файл plugin.sig и .git/ и __pycache__/ исключаются из подсчёта.
"""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives import serialization
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False


EXCLUDE_PARTS = ('__pycache__', '.git', '.cache', '.mypy_cache',
                 '.pytest_cache', '.ruff_cache')
EXCLUDE_SUFFIXES = ('.pyc', '.pyo', '.swp')
EXCLUDE_NAMES = ('plugin.sig',)


class SignatureError(Exception):
    pass


@dataclass
class SignatureInfo:
    algorithm: str
    key_id: str
    signature: str          # base64
    signed_files_checksum: str
    signed_at: Optional[str]
    valid: Optional[bool] = None
    trusted: Optional[bool] = None
    error: Optional[str] = None


# ─────────── Канонизация ───────────

def _hash_file(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def _iter_files(plugin_dir: Path):
    """Возвращает (rel_path, path) для всех файлов, включая plugin.json."""
    for f in sorted(plugin_dir.rglob('*')):
        if not f.is_file():
            continue
        rel = f.relative_to(plugin_dir)
        if any(part in EXCLUDE_PARTS for part in rel.parts):
            continue
        if f.suffix in EXCLUDE_SUFFIXES:
            continue
        if rel.name in EXCLUDE_NAMES:
            continue
        yield str(rel).replace('\\', '/'), f


def canonical_string(plugin_dir: Path) -> tuple[str, str]:
    """
    Возвращает (canonical_string, files_checksum_hex).
    """
    plugin_dir = Path(plugin_dir)
    parts = []

    # plugin.json первым
    manifest = plugin_dir / 'plugin.json'
    if not manifest.exists():
        raise SignatureError(f"Нет plugin.json в {plugin_dir}")
    manifest_hash = _hash_file(manifest)
    parts.append(f"plugin.json\n{manifest_hash}\n")

    parts.append("files\n")
    for rel, path in _iter_files(plugin_dir):
        parts.append(f"{rel}\n{_hash_file(path)}\n")

    canonical = ''.join(parts)
    checksum = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    return canonical, checksum


# ─────────── Генерация ключей ───────────

def generate_keypair(key_id: str) -> tuple[str, str]:
    """
    Генерирует приватный и публичный ключи ed25519.
    Возвращает (private_pem, public_pem) в PEM-формате.
    """
    if not _HAS_CRYPTO:
        raise SignatureError(
            "Требуется cryptography. Установите: pip install cryptography"
        )
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode('utf-8')

    pub = priv.public_key()
    pub_pem = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode('utf-8')

    return priv_pem, pub_pem


# ─────────── Подпись ───────────

def sign_plugin(plugin_dir: Path, private_pem: str,
                key_id: str) -> SignatureInfo:
    """
    Подписывает плагин. Записывает plugin.sig в корень.
    """
    if not _HAS_CRYPTO:
        raise SignatureError("Требуется cryptography")

    canonical, checksum = canonical_string(plugin_dir)
    priv = serialization.load_pem_private_key(
        private_pem.encode('utf-8'), password=None,
    )
    if not isinstance(priv, Ed25519PrivateKey):
        raise SignatureError("Ключ должен быть ed25519")

    signature = priv.sign(canonical.encode('utf-8'))
    sig_b64 = base64.b64encode(signature).decode('ascii')

    info = SignatureInfo(
        algorithm='ed25519',
        key_id=key_id,
        signature=sig_b64,
        signed_files_checksum=checksum,
        signed_at=datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        valid=True,
    )

    sig_path = plugin_dir / 'plugin.sig'
    sig_path.write_text(json.dumps({
        'algorithm': info.algorithm,
        'key_id': info.key_id,
        'signature': info.signature,
        'signed_files_checksum': info.signed_files_checksum,
        'signed_at': info.signed_at,
    }, indent=2), encoding='utf-8')

    return info


# ─────────── Верификация ───────────

def load_signature(plugin_dir: Path) -> Optional[SignatureInfo]:
    sig_path = plugin_dir / 'plugin.sig'
    if not sig_path.exists():
        return None
    try:
        data = json.loads(sig_path.read_text(encoding='utf-8'))
    except Exception as e:
        raise SignatureError(f"plugin.sig: невалидный JSON: {e}")
    return SignatureInfo(
        algorithm=data.get('algorithm', ''),
        key_id=data.get('key_id', ''),
        signature=data.get('signature', ''),
        signed_files_checksum=data.get('signed_files_checksum', ''),
        signed_at=data.get('signed_at'),
    )


def verify_plugin(plugin_dir: Path, public_pem: str,
                  expected_key_id: Optional[str] = None) -> SignatureInfo:
    """
    Проверяет подпись плагина.
    Возвращает SignatureInfo с valid=True/False.
    """
    info = load_signature(plugin_dir)
    if info is None:
        raise SignatureError("plugin.sig не найден")

    if info.algorithm != 'ed25519':
        raise SignatureError(f"Неподдерживаемый алгоритм: {info.algorithm}")

    if expected_key_id and info.key_id != expected_key_id:
        info.valid = False
        info.error = (f"key_id не совпадает: "
                      f"ожидался {expected_key_id}, в файле {info.key_id}")
        return info

    # Проверяем, что checksum содержимого совпадает
    try:
        _, cur_checksum = canonical_string(plugin_dir)
    except Exception as e:
        info.valid = False
        info.error = f"Ошибка чтения содержимого: {e}"
        return info

    if cur_checksum != info.signed_files_checksum:
        info.valid = False
        info.error = (f"Содержимое плагина изменилось после подписи "
                      f"(checksum {info.signed_files_checksum[:8]} → "
                      f"{cur_checksum[:8]})")
        return info

    # Криптографическая проверка
    if not _HAS_CRYPTO:
        raise SignatureError("Требуется cryptography для верификации")

    try:
        pub = serialization.load_pem_public_key(public_pem.encode('utf-8'))
        if not isinstance(pub, Ed25519PublicKey):
            raise SignatureError("Публичный ключ должен быть ed25519")
        canonical, _ = canonical_string(plugin_dir)
        signature = base64.b64decode(info.signature)
        pub.verify(signature, canonical.encode('utf-8'))
        info.valid = True
        return info
    except Exception as e:
        info.valid = False
        info.error = f"Подпись недействительна: {e}"
        return info


# ─────────── Доверенные ключи ───────────

class TrustStore:
    """
    Хранит доверенные публичные ключи.
    Источники:
        - config.yml → plugins.pubkeys: {key_id: pem}
        - файл plugins.pubkeys в корне: JSON {key_id: pem}
    """
    def __init__(self, root_dir: Path, config=None):
        self.root = Path(root_dir)
        self.config = config
        self.keys: dict[str, str] = {}
        self._load()

    def _load(self):
        # 1) из config.yml
        if self.config is not None:
            cfg_keys = self.config.get('plugins.pubkeys') or {}
            if isinstance(cfg_keys, dict):
                self.keys.update({k: str(v) for k, v in cfg_keys.items()})

        # 2) из plugins.pubkeys
        p = self.root / 'plugins.pubkeys'
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding='utf-8'))
                if isinstance(data, dict):
                    self.keys.update({k: str(v) for k, v in data.items()})
            except Exception:
                pass

    def verify(self, plugin_dir: Path) -> SignatureInfo:
        """
        Проверяет подпись против любого доверенного ключа.
        """
        info = load_signature(plugin_dir)
        if info is None:
            raise SignatureError("plugin.sig не найден")

        if not self.keys:
            info.valid = False
            info.trusted = False
            info.error = ("Нет доверенных ключей. Добавьте в config.yml → "
                          "plugins.pubkeys или в файл plugins.pubkeys")
            return info

        pem = self.keys.get(info.key_id)
        if not pem:
            info.valid = False
            info.trusted = False
            info.error = (f"Ключ '{info.key_id}' не в списке доверенных. "
                          f"Доверенные: {', '.join(self.keys.keys())}")
            return info

        result = verify_plugin(plugin_dir, pem, expected_key_id=info.key_id)
        result.trusted = result.valid
        return result


# ─────────── CLI-обёртки ───────────

def cmd_sign(plugin_dir: Path, private_key_path: Path, key_id: str
             ) -> SignatureInfo:
    private_pem = private_key_path.read_text(encoding='utf-8')
    return sign_plugin(plugin_dir, private_pem, key_id)
