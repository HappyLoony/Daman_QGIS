# -*- coding: utf-8 -*-
"""
Детерминированный SHA-256 хеш дерева файлов плагина для integrity-check.

Standalone модуль БЕЗ зависимостей от qgis.* — импортируется как из
плагина (внутри QGIS), так и из scripts/main.py (CLI вне QGIS, для
upload_channel_hash). Server-side вычисляет хеш по тому же алгоритму
для cross-environment determinism.

ОГРАНИЧЕНИЯ ИМПОРТОВ (КРИТИЧЕСКИ ВАЖНО — DOCUMENT-1 review 2026-05-09):
- НЕ добавлять qgis-зависимости — сломает CLI usage из scripts/main.py.
- НЕ добавлять third-party зависимости (requests, lxml и т.п.) —
  scripts/main.py временно вставляет QGIS_PLUGIN_DIR.parent в sys.path
  для импорта; третий-party imports могут зацепить sibling-плагины.
- РАЗРЕШЕНО ТОЛЬКО stdlib (hashlib, os, pathlib, typing).

Для logging skipped files — использовать hook `_on_skip` (см. ниже),
который плагин monkey-patch'ит в main_plugin.initGui (`_ih._on_skip = ...`).
"""

import hashlib
import os
from pathlib import Path
from typing import Callable, List


def compute_plugin_hash(plugin_dir: str) -> str:
    """Детерминированный SHA-256 хеш дерева файлов плагина.

    Включает все файлы кроме __pycache__/, .git/, *.pyc.
    Пути нормализованы в POSIX-формат; дерево сортируется
    лексикографически; финальный хеш = SHA-256 от sorted
    "{path}:{file_sha256}\\n" lines (UTF-8).

    Сервер вычисляет хеш по тому же алгоритму на этапе сборки релиза.
    Результат детерминирован при идентичном содержимом файлов и одинаковой
    структуре каталогов.

    Args:
        plugin_dir: абсолютный путь к корню плагина (где лежит main_plugin.py)

    Returns:
        64-символьный lowercase hex SHA-256.
    """
    EXCLUDE_DIRS = {"__pycache__", ".git"}
    EXCLUDE_SUFFIX = (".pyc",)

    plugin_path = Path(plugin_dir)
    items: List[str] = []
    for root, dirs, files in os.walk(plugin_path):
        # In-place prune для скорости (не спускаемся в исключённые)
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for filename in files:
            if filename.endswith(EXCLUDE_SUFFIX):
                continue
            filepath = Path(root) / filename
            try:
                rel = filepath.relative_to(plugin_path).as_posix()
                with open(filepath, "rb") as f:
                    file_hash = hashlib.sha256(f.read()).hexdigest()
                items.append(f"{rel}:{file_hash}")
            except (OSError, IOError) as e:
                # Не можем прочитать файл (lock, AV scan, deny-read ACL).
                # Сохраняем lenient semantics (skip — продолжаем строить
                # hash из остальных файлов), но эмитим signal для debug
                # + dashboard alerting на mass-skip events.
                # FIX-4 (review 2026-05-09): hook вместо silent pass.
                try:
                    rel_for_log = filepath.relative_to(plugin_path).as_posix()
                except (ValueError, OSError):
                    rel_for_log = str(filepath)
                _on_skip(rel_for_log, e)

    items.sort()
    blob = "\n".join(items).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _default_on_skip(rel_path: str, error: Exception) -> None:
    """No-op default. Сохраняет stdlib-only constraint модуля."""
    pass


# Hook для логирования/телеметрии skipped файлов. Плагин monkey-patch'ит
# в main_plugin.initGui: `from Daman_QGIS import integrity_hash as _ih;
# _ih._on_skip = my_logger`. Default no-op — module остаётся stdlib-only
# для CLI usage из scripts/.
_on_skip: Callable[[str, Exception], None] = _default_on_skip


# FIX-5 (review 2026-05-09): module-level cache. Plugin tree не меняется
# в течение QGIS-сессии (любые M_42._install требуют QGIS restart, который
# обнуляет cache естественно — новый process = свежий import). Это даёт:
# - Saves ~200ms × N heartbeats/day (full SHA-256 file-tree dump каждый раз)
# - Eliminates silent overwrite user edits в `documentation/`/`data/`:
#   при mid-session edit hash не меняется (cache hold) → heartbeat не
#   тригернёт mark_update_pending → следующий validate вернёт reality.
_cached_hash: "str | None" = None
_cached_dir: "str | None" = None


def get_cached_or_compute(plugin_dir: str) -> str:
    """Return cached hash или compute + cache при miss/dir change.

    Каждый caller (main_plugin._heartbeat_check, Msm_29_3._build_signed_payload)
    должен использовать эту функцию вместо compute_plugin_hash напрямую,
    чтобы получить пользу cache. compute_plugin_hash остаётся public для
    scripts/main.py CLI usage где cache не нужен (скрипт = single shot).
    """
    global _cached_hash, _cached_dir
    if _cached_hash is not None and _cached_dir == plugin_dir:
        return _cached_hash
    _cached_hash = compute_plugin_hash(plugin_dir)
    _cached_dir = plugin_dir
    return _cached_hash


def invalidate_cache() -> None:
    """Сбросить cache. Вызывается M_42._install после успешного swap
    (хотя обычно за этим следует QGIS restart — но safety-net на случай
    in-session reload через Plugin Manager Reloader)."""
    global _cached_hash, _cached_dir
    _cached_hash = None
    _cached_dir = None
