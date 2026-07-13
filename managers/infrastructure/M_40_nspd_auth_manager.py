# -*- coding: utf-8 -*-
"""
M_40_NspdAuthManager - Менеджер авторизации НСПД через Госуслуги

Обеспечивает:
- Авторизацию пользователя на nspd.gov.ru через браузер
- Перехват session cookies после входа через Госуслуги (ЕСИА)
- Инъекцию cookies в requests.Session для API запросов
- Индикацию статуса авторизации через сигналы

Два метода авторизации:
- Edge CDP (основной на Windows): запуск системного Edge + CDP для cookies
- QWebEngineView (fallback): встроенный браузер Qt (работает только с Qt6+)

Cookies хранятся только в памяти (сбрасываются при перезапуске QGIS).

Зависимости:
- Msm_40_1_AuthBrowserDialog - QDialog со встроенным браузером (Qt6 fallback)
- Msm_40_2_CookieStore - Потокобезопасное хранилище cookies
- Msm_40_3_EdgeAuthDialog - Авторизация через Edge CDP (Windows primary)

СЕМАНТИКА AUTH-ОТВЕТОВ НСПД (не классическая RFC 7235):
- 401 Unauthorized (`{"code":401}`) = «cookies есть, но истёкшие/невалидные»
  (протухли за время простоя).
- 403 Forbidden (`{"code":400104,"failed to relation intersect ids"}`) = «ресурс
  закрытый, нужен ESIA-токен» (анонимный запрос к закрытой группе).
  ВАЖНО: в loader (Fsm_1_2_1_egrn_loader) 403 трактуется как IP-блок — это
  КОРРЕКТНО только там (всегда session с cookies → 403 = реальный IP-блок), но
  НЕВЕРНО для anonymous-разведки (там 403 = «нужен токен»). Не путать контексты.
- Закрытые группы EGRN_WFS (требуют ESIA): МИНСТРОЙ (Красные линии, отступы от КЛ),
  ФГИС ТП (функциональные зоны), Санохрана, СКДФ (дороги/категории/класс/покрытие),
  Минэк (ООПТ). ЕГРН-основа (ЗУ/КК/Здания/Сооружения/ОНС) и АТД — публичны.

ЖИВОСТЬ COOKIES: ESIA-cookies живут ~30-60 мин server-side; `is_authenticated()`
проверяет ТОЛЬКО НАЛИЧИЕ cookies, НЕ их живость на сервере (M_40 этого не замечает).
Все cookies session-level (`expires=None`), критичный — `authAccessToken`. Клиент не
может pre-empt истечение.

ПАТТЕРН ОБРАБОТКИ — симметричный reactive retry (НЕ live-probe, НЕ pre-emptive):
- Loader (production): session с cookies → 401 → `M_40.invalidate()` +
  `session.cookies.clear()` → retry анонимно (дегрейд auth→anon).
- Test (Fsm_4_2_T_nspd): anonymous-first → 401 ИЛИ 403 → retry с session
  (подъём anon→auth, не знает наперёд требует ли endpoint auth).
АНТИ-ПАТТЕРНЫ (проверены, отвергнуты): live-probe в is_authenticated (race + дорого);
pre-emptive refresh by expiry (НСПД не отдаёт expires_in); auto-relogin Edge при 401
(intrusive — пользователь сам запускает M_40.login()).
ТЕСТ без ожидания 1.5ч: подменить authAccessToken на мусор в session → сервер 401.
"""

import platform
from typing import Dict, Optional, Any

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtWidgets import QDialog

from Daman_QGIS.utils import log_info, log_warning, log_error

from .submodules.Msm_40_1_auth_browser_dialog import (
    Msm_40_1_AuthBrowserDialog, is_webengine_available
)
from .submodules.Msm_40_2_cookie_store import Msm_40_2_CookieStore
from .submodules.Msm_40_3_edge_auth import (
    Msm_40_3_EdgeAuthDialog, is_edge_available
)


__all__ = ['NspdAuthManager']


class NspdAuthManager(QObject):
    """Менеджер авторизации НСПД.

    Singleton через ManagerRegistry. Предоставляет cookie-based
    авторизацию для запросов к API НСПД.

    На Windows с Edge -> Edge CDP (основной метод).
    Без Edge -> QWebEngineView (fallback для Qt6).

    Signals:
        auth_changed(bool): Статус авторизации изменился
            True = авторизован, False = не авторизован
    """

    auth_changed = pyqtSignal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._cookie_store = Msm_40_2_CookieStore()
        self._webengine_available = is_webengine_available()
        self._edge_available = is_edge_available()

        # На Windows с Edge -> Edge CDP (Qt5 QWebEngine не поддерживает SPA nspd.gov.ru)
        self._use_edge = (
            platform.system() == 'Windows' and self._edge_available
        )

        if not self._webengine_available and not self._edge_available:
            log_warning("M_40: Ни QWebEngine, ни Edge не доступны -- авторизация НСПД отключена")
        else:
            methods = []
            if self._edge_available:
                methods.append("Edge CDP")
            if self._webengine_available:
                methods.append("QWebEngine")
            primary = "Edge CDP" if self._use_edge else "QWebEngine"
            log_info(f"M_40: NspdAuthManager инициализирован "
                     f"(методы: {', '.join(methods)}, основной: {primary})")

    # =========================================================================
    # Публичные методы
    # =========================================================================

    def is_available(self) -> bool:
        """Проверка доступности функционала авторизации.

        Returns:
            True если Edge или QWebEngine доступен
        """
        return self._webengine_available or self._edge_available

    def is_authenticated(self) -> bool:
        """Проверка текущего статуса авторизации.

        Returns:
            True если есть сохраненные cookies
        """
        return self._cookie_store.is_valid()

    def get_cookies(self) -> Dict[str, str]:
        """Получить cookies авторизации.

        Returns:
            Словарь {name: value} cookies (копия, потокобезопасно)
        """
        return self._cookie_store.get_cookies()

    def login(self, parent: Optional[Any] = None) -> bool:
        """Открыть диалог авторизации НСПД.

        На Windows: запускает Edge с nspd.gov.ru, cookies через CDP.
        Без Edge: встроенный QWebEngineView (Qt6 fallback).

        Args:
            parent: Родительский виджет для диалога

        Returns:
            True если авторизация успешна
        """
        if not self.is_available():
            log_error("M_40: Авторизация недоступна (ни Edge, ни QWebEngine)")
            return False

        try:
            if self._use_edge:
                dialog = Msm_40_3_EdgeAuthDialog(parent)
            else:
                dialog = Msm_40_1_AuthBrowserDialog(parent)

            result = dialog.exec()

            if result == QDialog.Accepted:
                cookies = dialog.get_collected_cookies()
                self._cookie_store.set_cookies(cookies)
                self.auth_changed.emit(True)
                method = "Edge CDP" if self._use_edge else "QWebEngine"
                log_info(f"M_40: Авторизация НСПД через {method} "
                         f"({len(cookies)} cookies)")
                return True
            else:
                log_info("M_40: Авторизация отменена пользователем")
                return False

        except Exception as e:
            log_error(f"M_40: Ошибка авторизации: {e}")
            return False

    def logout(self) -> None:
        """Выход -- очистка cookies сессии."""
        self._cookie_store.clear()
        self.auth_changed.emit(False)
        log_info("M_40: Сессия НСПД очищена")

    def invalidate(self, reason: str = "") -> None:
        """Сброс cookies при detection истечения сессии на стороне сервера.

        В отличие от logout(), не позиционируется как явное действие
        пользователя -- вызывается reactive-handler'ами loader'ов при
        получении HTTP 401 от endpoint'а НСПД. Семантически
        фиксирует "server says token expired", а не "user logged out".

        Args:
            reason: Текстовая причина инвалидации (для логов/трейсинга)
        """
        if not self._cookie_store.is_valid():
            return
        self._cookie_store.clear()
        self.auth_changed.emit(False)
        log_warning(f"M_40: Cookies инвалидированы (reason={reason or 'server_401'})")

    def inject_cookies(self, session: Any) -> None:
        """Инъекция cookies в requests.Session.

        Добавляет все перехваченные cookies в объект session.
        Безопасно вызывать даже если не авторизован (ничего не произойдёт).

        Args:
            session: requests.Session объект
        """
        if not self._cookie_store.is_valid():
            return

        cookies = self._cookie_store.get_cookies()
        for name, value in cookies.items():
            session.cookies.set(name, value, domain='nspd.gov.ru')

        log_info(f"M_40: Инъецировано {len(cookies)} cookies в session")

    def cleanup(self) -> None:
        """Очистка ресурсов при выгрузке плагина."""
        self._cookie_store.clear()
        log_info("M_40: Cleanup выполнен")
