# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_semver - Тесты для M_42._parse_semver / _is_newer.

Проверяет channel-aware SemVer compare после рефактора 2026-05-09:
наша конвенция channel precedence dev (0) < beta (1) < bare (2),
что отклоняется от строгой SemVer 2.0.0 §11.4.2 alphabetical order.

Запуск из QGIS Python console:
    >>> exec(open(r"<path>/Fsm_4_2_T_semver.py").read())
    >>> run_all()
"""

from Daman_QGIS.utils import log_info, log_error
from Daman_QGIS.managers.infrastructure.M_42_auto_update_manager import (
    AutoUpdateManager,
)


_M = AutoUpdateManager()


def test_parse_basic() -> None:
    """Базовый парсинг X.Y.Z и X.Y.Z-tag[.N]."""
    cases = {
        "0.9.961":            (0, 9, 961, 2, 0),
        "0.9.961-beta.1":     (0, 9, 961, 1, 1),
        "0.9.961-beta.42":    (0, 9, 961, 1, 42),
        "0.9.961-beta":       (0, 9, 961, 1, 0),  # counter optional (edge — наш promote_to_beta всегда .1)
        "0.9.961-dev":        (0, 9, 961, 0, 0),
        "0.9.961-dev.1":      (0, 9, 961, 0, 1),
        "0.9.961-dev.99":     (0, 9, 961, 0, 99),
        "12.34.567":          (12, 34, 567, 2, 0),
    }
    for version, expected in cases.items():
        result = _M._parse_semver(version)
        if result != expected:
            raise AssertionError(
                f"_parse_semver({version!r}) = {result}, expected {expected}"
            )
    log_info("Fsm_4_2_T_semver: parse_basic OK")


def test_parse_invalid() -> None:
    """Невалидные форматы должны бросать ValueError."""
    invalid = [
        "",
        "0.9",
        "0.9.961.1",       # 4 числа
        "0.9.961-rc.1",    # rc не поддерживается (наш channel detection — только dev/beta/bare)
        "0.9.961-alpha",   # alpha не поддерживается
        "0.9.961+meta",    # build metadata
        "v0.9.961",        # лидирующий v
        "0.9.961-dev.x",   # нечисловой counter
    ]
    for version in invalid:
        try:
            _M._parse_semver(version)
        except ValueError:
            continue
        raise AssertionError(
            f"_parse_semver({version!r}) должно было бросить ValueError"
        )
    log_info("Fsm_4_2_T_semver: parse_invalid OK")


def test_is_newer_main_version() -> None:
    """Major/minor/patch сравниваются численно."""
    assert _M._is_newer("0.9.962", "0.9.961") is True
    assert _M._is_newer("0.10.0", "0.9.999") is True
    assert _M._is_newer("1.0.0", "0.9.999") is True
    assert _M._is_newer("0.9.961", "0.9.962") is False
    assert _M._is_newer("0.9.961", "0.9.961") is False
    log_info("Fsm_4_2_T_semver: main_version OK")


def test_is_newer_channel_precedence() -> None:
    """Та же main version: dev < beta < bare."""
    # bare > beta > dev
    assert _M._is_newer("0.9.961", "0.9.961-beta.1") is True
    assert _M._is_newer("0.9.961", "0.9.961-dev") is True
    assert _M._is_newer("0.9.961-beta.1", "0.9.961-dev") is True
    assert _M._is_newer("0.9.961-beta.1", "0.9.961-dev.99") is True

    # И обратно — не newer
    assert _M._is_newer("0.9.961-beta.1", "0.9.961") is False
    assert _M._is_newer("0.9.961-dev", "0.9.961") is False
    assert _M._is_newer("0.9.961-dev", "0.9.961-beta.1") is False
    assert _M._is_newer("0.9.961-dev.99", "0.9.961-beta.1") is False
    log_info("Fsm_4_2_T_semver: channel_precedence OK")


def test_is_newer_counter_within_channel() -> None:
    """В одном канале counter сравнивается численно."""
    assert _M._is_newer("0.9.961-dev.1", "0.9.961-dev") is True
    assert _M._is_newer("0.9.961-dev.2", "0.9.961-dev.1") is True
    assert _M._is_newer("0.9.961-dev.10", "0.9.961-dev.9") is True  # NOT lex
    assert _M._is_newer("0.9.961-beta.2", "0.9.961-beta.1") is True

    assert _M._is_newer("0.9.961-dev", "0.9.961-dev.1") is False
    assert _M._is_newer("0.9.961-dev.1", "0.9.961-dev.1") is False
    log_info("Fsm_4_2_T_semver: counter_within_channel OK")


def test_is_newer_real_rollout_scenario() -> None:
    """Реальный сценарий 2026-05-09 incident:
    QGIS log warning'ался при remote=0.9.960-beta.1 vs local=0.9.961-dev.1.
    Local dev (новый patch) > remote beta (старый patch) — update НЕ нужен.
    """
    # Старый bug: '961-dev' int() FAIL → warning + return False (correct по случайности)
    # Новая логика: правильный compare без warning
    assert _M._is_newer("0.9.960-beta.1", "0.9.961-dev.1") is False
    assert _M._is_newer("0.9.961-dev.1", "0.9.960-beta.1") is True
    log_info("Fsm_4_2_T_semver: real_rollout_scenario OK")


def test_is_newer_invalid_returns_false() -> None:
    """Парс fail → return False (skip update — safe default), не raise.

    Покрывает все типы invalid input с которыми может прийти код:
    - Невалидный SemVer (rc/alpha/garbage)
    - None (если plugins.xml не вернул version_el.text)
    - Пустая строка
    - Не-string типы (int, list — defensive)
    """
    assert _M._is_newer("0.9.961-rc.1", "0.9.961") is False
    assert _M._is_newer("0.9.961", "garbage") is False
    assert _M._is_newer(None, "1.0.0") is False  # type: ignore[arg-type]
    assert _M._is_newer("1.0.0", None) is False  # type: ignore[arg-type]
    assert _M._is_newer("", "1.0.0") is False
    assert _M._is_newer(123, "1.0.0") is False  # type: ignore[arg-type]
    log_info("Fsm_4_2_T_semver: invalid_returns_false OK")


def run_all() -> None:
    test_parse_basic()
    test_parse_invalid()
    test_is_newer_main_version()
    test_is_newer_channel_precedence()
    test_is_newer_counter_within_channel()
    test_is_newer_real_rollout_scenario()
    test_is_newer_invalid_returns_false()
    log_info("Fsm_4_2_T_semver: ALL PASS")
