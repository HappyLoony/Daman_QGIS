# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_compute_hash - Тесты для integrity_hash.compute_plugin_hash().

Проверяет:
- Детерминированность (одинаковый каталог -> одинаковый хеш)
- Исключение *.pyc файлов
- Исключение каталога __pycache__
- Детекцию изменений файла
- (FIX-4) _on_skip hook вызывается при OSError на read-файла
- (FIX-5) module-level cache: get_cached_or_compute hit/miss/invalidate

Запуск из QGIS Python console:
    >>> exec(open(r"<path>/Fsm_4_2_T_compute_hash.py").read())
    >>> run_all()
"""

import os
import sys
import tempfile
from pathlib import Path

from Daman_QGIS.utils import log_info, log_error
from Daman_QGIS import integrity_hash as _ih
from Daman_QGIS.integrity_hash import (
    compute_plugin_hash,
    get_cached_or_compute,
    invalidate_cache,
)


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


def test_on_skip_hook_called_on_oserror() -> None:
    """FIX-4: при OSError на read файла вызывается _on_skip с rel_path + error."""
    skipped: list = []

    def _capture(rel_path: str, error: Exception) -> None:
        skipped.append((rel_path, type(error).__name__))

    original = _ih._on_skip
    _ih._on_skip = _capture
    try:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "good.py").write_text("# ok", encoding="utf-8")
            bad = Path(tmp) / "bad.py"
            bad.write_text("# unreadable", encoding="utf-8")
            # Windows: chmod 0 не делает файл нечитаемым (deprecated). Используем
            # icacls для deny-read. POSIX: chmod 0 работает.
            if sys.platform == "win32":
                import subprocess
                subprocess.run(
                    ["icacls", str(bad), "/deny", "Everyone:R"],
                    capture_output=True, check=False,
                )
                try:
                    h = compute_plugin_hash(tmp)
                    assert len(h) == 64
                    assert any("bad.py" in rel for rel, _ in skipped), (
                        f"_on_skip не вызвался для bad.py: skipped={skipped}"
                    )
                    assert all(
                        err in ("PermissionError", "OSError", "IOError")
                        for _, err in skipped
                    )
                finally:
                    # cleanup ACL чтобы tempdir можно было удалить
                    subprocess.run(
                        ["icacls", str(bad), "/remove:d", "Everyone"],
                        capture_output=True, check=False,
                    )
            else:
                os.chmod(bad, 0)
                try:
                    h = compute_plugin_hash(tmp)
                    assert len(h) == 64
                    assert any("bad.py" in rel for rel, _ in skipped), (
                        f"_on_skip не вызвался для bad.py: skipped={skipped}"
                    )
                finally:
                    os.chmod(bad, 0o644)
        log_info(f"Fsm_4_2_T_compute_hash: _on_skip hook OK ({len(skipped)} skip)")
    finally:
        _ih._on_skip = original


def test_default_on_skip_no_raise() -> None:
    """FIX-4: default _on_skip — no-op, не бросает."""
    # Гарантируем default
    _ih._on_skip = _ih._default_on_skip
    # Просто вызовем напрямую — должен молча вернуться
    _ih._on_skip("foo.py", OSError("synthetic"))
    log_info("Fsm_4_2_T_compute_hash: default _on_skip no-op OK")


def test_cache_hit_returns_same_value() -> None:
    """FIX-5: get_cached_or_compute второй вызов с тем же dir = cache hit."""
    invalidate_cache()
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "main.py").write_text("# v1", encoding="utf-8")
        h1 = get_cached_or_compute(tmp)
        # Меняем файл — но cache должен хранить старое значение
        (Path(tmp) / "main.py").write_text("# v2_changed", encoding="utf-8")
        h2 = get_cached_or_compute(tmp)
        assert h1 == h2, (
            f"Fsm_4_2_T_compute_hash: cache miss при том же dir: {h1} != {h2}"
        )
    invalidate_cache()
    log_info("Fsm_4_2_T_compute_hash: cache hit OK")


def test_invalidate_cache_recompute() -> None:
    """FIX-5: invalidate_cache → следующий вызов recompute."""
    invalidate_cache()
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "main.py").write_text("# v1", encoding="utf-8")
        h1 = get_cached_or_compute(tmp)
        (Path(tmp) / "main.py").write_text("# v2_changed", encoding="utf-8")
        invalidate_cache()
        h2 = get_cached_or_compute(tmp)
        assert h1 != h2, (
            f"Fsm_4_2_T_compute_hash: invalidate не сработал: {h1} == {h2}"
        )
    invalidate_cache()
    log_info("Fsm_4_2_T_compute_hash: invalidate_cache recompute OK")


def test_cache_miss_on_dir_change() -> None:
    """FIX-5: разные dir → recompute, не reuse чужого cache."""
    invalidate_cache()
    with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
        (Path(tmp1) / "a.py").write_text("# tmp1", encoding="utf-8")
        (Path(tmp2) / "b.py").write_text("# tmp2", encoding="utf-8")
        h1 = get_cached_or_compute(tmp1)
        h2 = get_cached_or_compute(tmp2)
        assert h1 != h2, (
            f"Fsm_4_2_T_compute_hash: cache не сменился при смене dir"
        )
    invalidate_cache()
    log_info("Fsm_4_2_T_compute_hash: cache miss on dir change OK")


def run_all() -> None:
    """Запуск всех тестов compute_plugin_hash."""
    try:
        test_determinism()
        test_pycache_file_excluded()
        test_pycache_dir_excluded()
        test_change_detection()
        test_on_skip_hook_called_on_oserror()
        test_default_on_skip_no_raise()
        test_cache_hit_returns_same_value()
        test_invalidate_cache_recompute()
        test_cache_miss_on_dir_change()
        log_info("Fsm_4_2_T_compute_hash: ALL PASS")
    except AssertionError as e:
        log_error(f"Fsm_4_2_T_compute_hash: FAIL - {e}")
        raise
    except Exception as e:
        log_error(f"Fsm_4_2_T_compute_hash: ERROR - {e}")
        raise
