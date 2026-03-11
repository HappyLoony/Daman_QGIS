# -*- coding: utf-8 -*-
"""
Msm_40_1_AuthBrowserDialog - Диалог авторизации НСПД через встроенный браузер

Открывает QWebEngineView с сайтом nspd.gov.ru, пользователь авторизуется
через Госуслуги (ЕСИА), плагин перехватывает session cookies.

Cookies хранятся только в памяти (NoPersistentCookies).
Каждый запуск диалога начинается с чистых cookies.

Зависимости:
- QWebEngineWidgets (входит в стандартную поставку QGIS)
- constants.py: NSPD_AUTH_URL, NSPD_AUTH_COOKIE_DOMAINS
"""

from typing import Dict, Optional

from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QMessageBox
)

from Daman_QGIS.core.base_responsive_dialog import BaseResponsiveDialog
from Daman_QGIS.constants import NSPD_AUTH_URL, NSPD_AUTH_COOKIE_DOMAINS
from Daman_QGIS.utils import log_info, log_warning, log_error

# QWebEngine может отсутствовать в некоторых сборках QGIS
_webengine_available = False
_qt_version = 0  # 5 или 6
try:
    from qgis.PyQt.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
    from qgis.PyQt.QtWebEngineCore import QWebEngineProfile
    _webengine_available = True
    _qt_version = 6
except ImportError:
    try:
        # Qt5 fallback: profile в QtWebEngineWidgets
        from qgis.PyQt.QtWebEngineWidgets import (
            QWebEngineView, QWebEnginePage, QWebEngineProfile
        )
        _webengine_available = True
        _qt_version = 5
    except ImportError:
        log_warning("Msm_40_1: QWebEngineWidgets недоступен -- авторизация НСПД отключена")


def is_webengine_available() -> bool:
    """Проверка доступности QWebEngineView."""
    return _webengine_available


class _AuthWebEnginePage(QWebEnginePage if _webengine_available else object):  # type: ignore[misc]
    """Кастомная страница с обработкой SSL и JS-консоли.

    Российские госсайты (nspd.gov.ru, gosuslugi.ru) используют сертификаты
    Минцифры, которые не входят в стандартное хранилище доверенных CA
    в Chromium/Qt. Без принятия этих сертификатов страница остаётся пустой.

    Также перехватывает JS-консоль для диагностики SPA-ошибок.
    """

    def certificateError(self, error: object) -> bool:
        """Обработка ошибок SSL сертификата."""
        try:
            url = error.url().toString() if hasattr(error, 'url') else 'unknown'  # type: ignore[union-attr]
            desc = error.description() if hasattr(error, 'description') else str(error)  # type: ignore[union-attr]
            log_warning(f"Msm_40_1: SSL ошибка для {url}: {desc}")

            if hasattr(error, 'acceptCertificate'):
                error.acceptCertificate()  # type: ignore[union-attr]
                log_info(f"Msm_40_1: SSL сертификат принят (Qt6) для {url}")
                return True

            log_info(f"Msm_40_1: SSL сертификат принят (Qt5) для {url}")
            return True

        except Exception as e:
            log_error(f"Msm_40_1: Ошибка обработки SSL: {e}")
            return True

    def javaScriptConsoleMessage(self, level: int, message: str,
                                  line: int, source: str) -> None:
        """Перехват JS-консоли для диагностики."""
        level_names = {0: 'INFO', 1: 'WARNING', 2: 'ERROR'}
        level_name = level_names.get(level, f'LEVEL{level}')
        short_source = source.split('/')[-1] if source else '?'
        log_msg = f"Msm_40_1 [JS {level_name}] {short_source}:{line}: {message[:200]}"
        if level >= 2:
            log_error(log_msg)
        else:
            log_info(log_msg)


class Msm_40_1_AuthBrowserDialog(BaseResponsiveDialog):
    """Диалог авторизации НСПД через встроенный браузер.

    Открывает https://nspd.gov.ru, пользователь входит через Госуслуги,
    cookies автоматически перехватываются.

    Usage:
        dialog = Msm_40_1_AuthBrowserDialog(parent)
        if dialog.exec() == QDialog.Accepted:
            cookies = dialog.get_collected_cookies()
    """

    WIDTH_RATIO = 0.75
    HEIGHT_RATIO = 0.80
    MIN_WIDTH = 800
    MAX_WIDTH = 1300
    MIN_HEIGHT = 600
    MAX_HEIGHT = 1000

    def __init__(self, parent: Optional[object] = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]

        self._cookies: Dict[str, str] = {}

        self.setWindowTitle("Авторизация НСПД")
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowMaximizeButtonHint  # type: ignore[operator]
        )

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Создание интерфейса."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        if not _webengine_available:
            error_label = QLabel(
                "QWebEngineWidgets недоступен в данной сборке QGIS.\n\n"
                "Авторизация через встроенный браузер невозможна.\n"
                "Обновите QGIS или установите пакет qtwebengine."
            )
            error_label.setAlignment(Qt.AlignCenter)  # type: ignore[arg-type]
            error_label.setStyleSheet("color: red; font-size: 11pt;")
            layout.addWidget(error_label)

            close_btn = QPushButton("Закрыть")
            close_btn.clicked.connect(self.reject)
            layout.addWidget(close_btn)
            return

        # Создаём off-the-record профиль (без имени = incognito)
        # Именованный профиль "nspd_auth" создаёт кэш-директорию,
        # которая может вызывать проблемы при повторных запусках.
        self._profile = QWebEngineProfile(self)
        self._profile.setPersistentCookiesPolicy(
            QWebEngineProfile.NoPersistentCookies
        )

        # User-Agent: реальный Chrome, иначе SPA может не загрузиться
        chrome_ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        self._profile.setHttpUserAgent(chrome_ua)

        log_info(f"Msm_40_1: Профиль создан (Qt{_qt_version}, off-the-record), "
                 f"UA={chrome_ua[:50]}...")

        # Перехват cookies
        cookie_store = self._profile.cookieStore()
        cookie_store.deleteAllCookies()
        cookie_store.cookieAdded.connect(self._on_cookie_added)

        # Браузер с кастомной страницей (обработка SSL + JS-консоль)
        page = _AuthWebEnginePage(self._profile, self)

        # Web settings: явное включение для SPA
        settings = page.settings()
        try:
            from qgis.PyQt.QtWebEngineWidgets import QWebEngineSettings
            settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
            settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
            settings.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, True)
            settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
            settings.setAttribute(QWebEngineSettings.ErrorPageEnabled, True)
            if hasattr(QWebEngineSettings, 'WebGLEnabled'):
                settings.setAttribute(QWebEngineSettings.WebGLEnabled, True)
            if hasattr(QWebEngineSettings, 'AllowRunningInsecureContent'):
                settings.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, True)
            log_info("Msm_40_1: Web settings применены (JS, LocalStorage, WebGL)")
        except Exception as e:
            log_warning(f"Msm_40_1: Не удалось настроить web settings: {e}")

        self._browser = QWebEngineView(self)
        self._browser.setPage(page)

        # Отладочные сигналы
        self._browser.loadStarted.connect(self._on_load_started)
        self._browser.loadFinished.connect(self._on_load_finished)
        self._browser.loadProgress.connect(self._on_load_progress)
        page.urlChanged.connect(self._on_url_changed)

        # Обработка падения рендер-процесса
        if hasattr(page, 'renderProcessTerminated'):
            page.renderProcessTerminated.connect(self._on_render_terminated)

        layout.addWidget(self._browser, stretch=1)

        # Нижняя панель: статус + кнопки
        bottom_layout = QHBoxLayout()

        self._status_label = QLabel("Войдите в НСПД через Госуслуги")
        self._status_label.setStyleSheet("color: #666; font-size: 9pt; padding: 2px;")
        bottom_layout.addWidget(self._status_label, stretch=1)

        self._cookie_count_label = QLabel("Cookies: 0")
        self._cookie_count_label.setStyleSheet("color: gray; font-size: 9pt; padding: 2px;")
        bottom_layout.addWidget(self._cookie_count_label)

        done_btn = QPushButton("Готово")
        done_btn.clicked.connect(self._finish)
        done_btn.setMinimumWidth(100)
        bottom_layout.addWidget(done_btn)

        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setMinimumWidth(100)
        bottom_layout.addWidget(cancel_btn)

        layout.addLayout(bottom_layout)

        # Загружаем сайт НСПД
        self._browser.load(QUrl(NSPD_AUTH_URL))
        log_info(f"Msm_40_1: Загрузка {NSPD_AUTH_URL}")

    # =========================================================================
    # Отладочные обработчики сигналов
    # =========================================================================

    def _on_load_started(self) -> None:
        """Загрузка страницы началась."""
        log_info("Msm_40_1: loadStarted -- загрузка начата")
        self._status_label.setText("Загрузка...")

    def _on_load_finished(self, ok: bool) -> None:
        """Загрузка страницы завершена."""
        url = self._browser.url().toString()
        if ok:
            log_info(f"Msm_40_1: loadFinished OK -- {url}")
            if not self._cookies:
                self._status_label.setText("Войдите в НСПД через Госуслуги")
            # Инспекция DOM для диагностики пустой страницы
            self._browser.page().runJavaScript(
                "document.documentElement.outerHTML.length + '|' + document.title + '|' + document.body.children.length",
                self._on_dom_inspected
            )
        else:
            log_error(f"Msm_40_1: loadFinished FAILED -- {url}")
            self._status_label.setText("Ошибка загрузки страницы")
            self._status_label.setStyleSheet(
                "color: red; font-size: 9pt; padding: 2px; font-weight: bold;"
            )

    def _on_dom_inspected(self, result: object) -> None:
        """Результат инспекции DOM."""
        log_info(f"Msm_40_1: DOM инспекция: {result}")

    def _on_load_progress(self, progress: int) -> None:
        """Прогресс загрузки."""
        if progress % 25 == 0:  # Логируем каждые 25%
            log_info(f"Msm_40_1: loadProgress {progress}%")

    def _on_url_changed(self, url: object) -> None:
        """URL страницы изменился (навигация/редирект)."""
        url_str = url.toString() if hasattr(url, 'toString') else str(url)  # type: ignore[union-attr]
        log_info(f"Msm_40_1: urlChanged -> {url_str}")

    def _on_render_terminated(self, status: int, exit_code: int) -> None:
        """Рендер-процесс завершился аварийно."""
        status_names = {0: 'NormalTermination', 1: 'AbnormalTermination', 2: 'CrashedTermination', 3: 'KilledTermination'}
        status_name = status_names.get(status, f'Unknown({status})')
        log_error(f"Msm_40_1: Рендер-процесс завершён: {status_name}, exit_code={exit_code}")
        self._status_label.setText(f"Браузер упал: {status_name}")
        self._status_label.setStyleSheet(
            "color: red; font-size: 9pt; padding: 2px; font-weight: bold;"
        )

    # =========================================================================
    # Cookie handling
    # =========================================================================

    def _on_cookie_added(self, cookie: object) -> None:
        """Обработка нового cookie от QWebEngine.

        Фильтрует cookies по домену -- сохраняет только
        связанные с nspd.gov.ru и gosuslugi.ru.
        """
        try:
            domain = bytes(cookie.domain()).decode('utf-8', errors='replace')  # type: ignore[union-attr]

            # Фильтр по домену
            if not any(d in domain for d in NSPD_AUTH_COOKIE_DOMAINS):
                return

            name = bytes(cookie.name()).decode('utf-8', errors='replace')  # type: ignore[union-attr]
            value = bytes(cookie.value()).decode('utf-8', errors='replace')  # type: ignore[union-attr]

            self._cookies[name] = value

            # Обновляем счётчик
            self._cookie_count_label.setText(f"Cookies: {len(self._cookies)}")

            # Обновляем статус при наличии cookies
            if len(self._cookies) >= 3:
                self._status_label.setText("Cookies перехвачены. Нажмите 'Готово' когда войдёте.")
                self._status_label.setStyleSheet(
                    "color: green; font-size: 9pt; padding: 2px; font-weight: bold;"
                )

        except Exception as e:
            log_warning(f"Msm_40_1: Ошибка обработки cookie: {e}")

    def _finish(self) -> None:
        """Завершение авторизации."""
        if self._cookies:
            log_info(f"Msm_40_1: Авторизация завершена, перехвачено {len(self._cookies)} cookies")
            self.accept()
        else:
            QMessageBox.warning(
                self,
                "Авторизация НСПД",
                "Cookies не обнаружены.\n\n"
                "Убедитесь что вы нажали 'Войти' на сайте НСПД\n"
                "и прошли авторизацию через Госуслуги."
            )

    def get_collected_cookies(self) -> Dict[str, str]:
        """Получить собранные cookies.

        Returns:
            Словарь {name: value} перехваченных cookies
        """
        return dict(self._cookies)
