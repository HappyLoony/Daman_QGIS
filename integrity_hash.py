# -*- coding: utf-8 -*-
"""
Детерминированный SHA-256 хеш дерева файлов плагина для integrity-check.

Standalone модуль БЕЗ зависимостей от qgis.* — импортируется как из
плагина (внутри QGIS), так и из scripts/main.py (CLI вне QGIS, для
upload_channel_hash). Server-side вычисляет хеш по тому же алгоритму
для cross-environment determinism.

Не добавлять qgis-зависимости в этот файл — это сломает scripts/.
"""

import hashlib
import os
from pathlib import Path
from typing import List


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
            except (OSError, IOError):
                # Не можем прочитать файл — пропускаем (рассинхронизация
                # с server-side возможна, но редка; залоченные .pyc уже
                # исключены выше).
                pass

    items.sort()
    blob = "\n".join(items).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
