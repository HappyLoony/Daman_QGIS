# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_compute_hash - Тесты для utils.compute_plugin_hash().

Проверяет:
- Детерминированность (одинаковый каталог -> одинаковый хеш)
- Исключение *.pyc файлов
- Исключение каталога __pycache__
- Детекцию изменений файла

Запуск из QGIS Python console:
    >>> exec(open(r"<path>/Fsm_4_2_T_compute_hash.py").read())
    >>> run_all()
"""

import os
import tempfile
from pathlib import Path

from Daman_QGIS.utils import log_info, log_error
from Daman_QGIS.integrity_hash import compute_plugin_hash


def test_determinism() -> None:
    """Тот же plugin_dir -> тот же хеш при повторных вызовах."""
    # Поднимаемся 4 уровня вверх:
    # Fsm_4_2_T_comprehensive_runner -> submodules -> F_4_plagin -> tools -> plugin root
    plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )))
    h1 = compute_plugin_hash(plugin_dir)
    h2 = compute_plugin_hash(plugin_dir)
    assert h1 == h2, f"Fsm_4_2_T_compute_hash: non-deterministic: {h1} != {h2}"
    assert len(h1) == 64, f"Fsm_4_2_T_compute_hash: wrong length: {len(h1)}"
    log_info(f"Fsm_4_2_T_compute_hash: determinism OK ({h1[:16]}...)")


def test_pycache_file_excluded() -> None:
    """Изменение *.pyc файла не должно менять хеш."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "main.py").write_text("# test", encoding="utf-8")
        h1 = compute_plugin_hash(tmp)

        (Path(tmp) / "main.pyc").write_text("bytecode", encoding="utf-8")
        h2 = compute_plugin_hash(tmp)

        assert h1 == h2, (
            f"Fsm_4_2_T_compute_hash: .pyc affected hash: {h1} -> {h2}"
        )
        log_info("Fsm_4_2_T_compute_hash: pycache file exclusion OK")


def test_pycache_dir_excluded() -> None:
    """Содержимое каталога __pycache__ не должно менять хеш."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "main.py").write_text("# test", encoding="utf-8")
        h1 = compute_plugin_hash(tmp)

        cache_dir = Path(tmp) / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "main.cpython-312.pyc").write_text(
            "bytecode", encoding="utf-8"
        )
        h2 = compute_plugin_hash(tmp)

        assert h1 == h2, (
            f"Fsm_4_2_T_compute_hash: __pycache__ affected hash: {h1} -> {h2}"
        )
        log_info("Fsm_4_2_T_compute_hash: __pycache__ dir exclusion OK")


def test_change_detection() -> None:
    """Изменение содержимого файла должно менять хеш."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "main.py").write_text("# v1", encoding="utf-8")
        h1 = compute_plugin_hash(tmp)
        (Path(tmp) / "main.py").write_text("# v2", encoding="utf-8")
        h2 = compute_plugin_hash(tmp)
        assert h1 != h2, "Fsm_4_2_T_compute_hash: hash unchanged after edit"
        log_info("Fsm_4_2_T_compute_hash: change detection OK")


def run_all() -> None:
    """Запуск всех тестов compute_plugin_hash."""
    try:
        test_determinism()
        test_pycache_file_excluded()
        test_pycache_dir_excluded()
        test_change_detection()
        log_info("Fsm_4_2_T_compute_hash: ALL PASS")
    except AssertionError as e:
        log_error(f"Fsm_4_2_T_compute_hash: FAIL - {e}")
        raise
    except Exception as e:
        log_error(f"Fsm_4_2_T_compute_hash: ERROR - {e}")
        raise
