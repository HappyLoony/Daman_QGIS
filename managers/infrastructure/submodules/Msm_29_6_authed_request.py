# -*- coding: utf-8 -*-
"""
Msm_29_6_AuthedRequestManager - Единая точка для авторизованных запросов к Plugin API.

Назначение:
    Унифицирует retry/refresh/backoff/circuit-breaker для всех `/api/plugin/*`
    запросов, требующих JWT авторизации (BaseReferenceLoader, M_37 profile,
    Msm_29_5 pipelines, любые будущие consumers).

Проблема, которую решает:
    Без unified retry плагин при невалидном/просроченном access JWT мог делать
    burst из десятков 403 AUTH_FAILED запросов за секунды (например, при
    пакетной загрузке reference JSON в BaseReferenceLoader). Это триггерит
    серверный CrowdSec scenario `daman-anomaly` (>50 plugin-API запросов /
    5 мин) и блокирует IP пользователя на firewall на 4 часа.

Поведение:
    - На любой 403/401 от plugin-API:
      1. POST `/api/plugin/refresh` — получить новый access JWT (через TokenManager).
      2. С новым JWT — один повтор исходного запроса.
      3. Если refresh упал ИЛИ повтор тоже 403 → stop, log_error, raise
         `AuthFailureError`. Caller показывает UI «Требуется повторная активация».
    - Circuit breaker: max 3 попытки на endpoint за окно 60 секунд.
      Между попытками — exponential backoff (2с, 5с, 10с).
    - JWT version guard: если access JWT содержит claim `ver`, не совпадающий
      с PLUGIN_VERSION (последствие M_42 hot update без рестарта), токены
      инвалидируются и поднимается `VersionMismatchError`. Caller (обычно
      M_29) форсит `/validate` с актуальной PLUGIN_VERSION для получения
      новых integrity hashes в JWT claims.

Зависимости:
    - Msm_29_4_TokenManager — auth headers, refresh token
    - constants — PLUGIN_VERSION, API_TIMEOUT, AUTHED_REQUEST_*
    - utils — log_info, log_warning, log_error
"""

from __future__ import annotations

import base64
import json
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, Optional

from Daman_QGIS.constants import (
    API_TIMEOUT,
    AUTHED_REQUEST_BACKOFF_SECONDS,
    AUTHED_REQUEST_MAX_ATTEMPTS,
    AUTHED_REQUEST_WINDOW_SECONDS,
    PLUGIN_VERSION,
)
from Daman_QGIS.utils import log_error, log_warning


__all__ = [
    'AuthedRequestManager',
    'AuthedRequestError',
    'AuthFailureError',
    'CircuitBreakerError',
    'VersionMismatchError',
]


class AuthedRequestError(Exception):
    """Базовое исключение для ошибок авторизованного запроса."""


class AuthFailureError(AuthedRequestError):
    """Refresh не удался ИЛИ повтор после refresh тоже 403/401.

    Caller должен показать UI «Требуется повторная активация лицензии»
    и предложить запустить forced-activation dialog.
    """


class CircuitBreakerError(AuthedRequestError):
    """Превышен лимит попыток на endpoint в окне 60 секунд.

    Caller должен прекратить ретраи и сообщить пользователю,
    что справочник временно недоступен (без spam запросов на сервер).
    """


class VersionMismatchError(AuthedRequestError):
    """JWT `ver` claim не совпадает с текущим PLUGIN_VERSION.

    Возникает при hot-update плагина (M_42) без рестарта QGIS:
    cached JWT содержит integrity hashes старой версии. Caller
    (M_29) должен форсить `/validate` с актуальным PLUGIN_VERSION.
    """


class AuthedRequestManager:
    """Singleton helper для авторизованных запросов к Plugin API.

    Single source of truth для retry/refresh/backoff. Все managers,
    которые ходят к /api/plugin/* с JWT, должны использовать этот
    helper, а не дёргать requests напрямую.
    """

    MODULE_ID = "Msm_29_6"

    _instance: Optional['AuthedRequestManager'] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        # Circuit breaker: {endpoint_key: deque[timestamp_seconds]}
        self._attempts: Dict[str, Deque[float]] = {}
        self._attempts_lock = threading.Lock()
        # Защита от рекурсивного refresh при параллельных запросах
        self._refresh_lock = threading.Lock()
        # Callback для UI (показ диалога активации)
        self._on_auth_failure_ui: Optional[Callable[[], None]] = None

    @classmethod
    def get_instance(cls) -> 'AuthedRequestManager':
        """Получить singleton."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Сброс singleton (тесты, деактивация лицензии)."""
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance._attempts.clear()
            cls._instance = None

    def set_on_auth_failure_ui(self, callback: Callable[[], None]) -> None:
        """Зарегистрировать callback показа UI «Требуется повторная активация».

        Вызывается из main_plugin при инициализации M_29. Callback должен
        быть idempotent — может быть вызван несколько раз за сессию,
        не должен спамить диалогами при каждом 403.
        """
        self._on_auth_failure_ui = callback

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def request(
        self,
        method: str,
        url: str,
        *,
        endpoint_key: Optional[str] = None,
        timeout: Optional[float] = None,
        **request_kwargs: Any,
    ) -> Any:
        """Выполнить авторизованный запрос с retry/refresh/backoff.

        Args:
            method: HTTP метод ("GET", "POST", "PUT", ...)
            url: Полный URL (включая query string). Используй constants.get_api_url().
            endpoint_key: Ключ для circuit breaker. По умолчанию — путь
                из URL (без query). Запросы к одному endpoint но с разными
                query params (file=A vs file=B) делят квоту 3 попытки/60с.
            timeout: Таймаут запроса (по умолчанию constants.API_TIMEOUT).
            **request_kwargs: Передаются в requests.request() (json=, data=,
                params=, и т.п.). Headers добавляются автоматически —
                не передавать Authorization вручную.

        Returns:
            requests.Response объект. Caller проверяет status_code и парсит body.

        Raises:
            CircuitBreakerError: исчерпан лимит 3 попытки/60с на endpoint.
            AuthFailureError: refresh упал или повтор после refresh = 403.
            VersionMismatchError: JWT `ver` claim != PLUGIN_VERSION.
            requests.exceptions.RequestException: сетевые ошибки (передаются caller'у).

        Использование:
            ```python
            from Daman_QGIS.managers.infrastructure.submodules.Msm_29_6_authed_request import (
                AuthedRequestManager, AuthFailureError, CircuitBreakerError,
            )

            mgr = AuthedRequestManager.get_instance()
            try:
                response = mgr.request("GET", get_api_url("data", file="Base_X"))
                if response.status_code == 200:
                    data = response.json()
            except CircuitBreakerError:
                # Тихо — не спамить юзера, не повторять
                return None
            except AuthFailureError:
                # UI уже показан помощником, caller возвращает None
                return None
            ```
        """
        try:
            import requests
        except ImportError:
            log_warning(f"{self.MODULE_ID}: requests library not available")
            return None

        ep_key = endpoint_key or self._derive_endpoint_key(url)
        timeout_value = timeout if timeout is not None else API_TIMEOUT

        # Pre-check: если circuit breaker уже открыт от прошлых auth failures,
        # raise сразу не делая запрос. Также проверяем JWT version mismatch.
        self._check_circuit_breaker(ep_key)
        self._check_jwt_version()

        # Первая попытка. NB: _record_attempt здесь НЕ вызываем — circuit breaker
        # должен срабатывать только на AUTH-FAILURES, а не на нормальные запросы.
        # Иначе плагин при cold start (3+ обращений к /api/plugin/data за справочники)
        # ложно открывает CB и блокирует всю загрузку. Регрессия 0.9.894 → fixed.
        response = self._raw_request(
            requests, method, url, timeout_value, **request_kwargs
        )

        # Если успех или ошибка не auth-related — возвращаем сразу,
        # ничего не записывая в счётчик circuit breaker.
        if not self._is_auth_failure(response):
            return response

        # 401/403 AUTH_FAILED — auth failure. Записываем попытку и проверяем квоту.
        self._record_attempt(ep_key)
        # Может оказаться что эта попытка была 3-й в окне → raise немедленно.
        self._check_circuit_breaker(ep_key)

        log_warning(
            f"{self.MODULE_ID}: {method} {ep_key} -> "
            f"{response.status_code} {self._extract_error_code(response)}, "
            f"attempting refresh+retry"
        )

        # Backoff перед refresh (2s).
        self._sleep_backoff(attempt_index=0)

        # Refresh JWT через TokenManager.
        if not self._do_refresh():
            log_error(
                f"{self.MODULE_ID}: Refresh failed after {response.status_code} "
                f"on {ep_key} — invalidating session"
            )
            self._notify_auth_failure_ui()
            raise AuthFailureError(
                f"Refresh failed after {response.status_code} on {ep_key}"
            )

        # Backoff перед повтором (5s).
        self._sleep_backoff(attempt_index=1)

        retry_response = self._raw_request(
            requests, method, url, timeout_value, **request_kwargs
        )

        if self._is_auth_failure(retry_response):
            # Retry тоже provoked auth failure — фиксируем ещё одну попытку.
            self._record_attempt(ep_key)
            log_error(
                f"{self.MODULE_ID}: Retry after refresh still failed: "
                f"{retry_response.status_code} {self._extract_error_code(retry_response)} "
                f"on {ep_key}"
            )
            self._notify_auth_failure_ui()
            raise AuthFailureError(
                f"Retry after refresh failed: {retry_response.status_code} on {ep_key}"
            )

        return retry_response

    # ------------------------------------------------------------------
    # Внутренняя реализация
    # ------------------------------------------------------------------

    def _raw_request(
        self,
        requests_module: Any,
        method: str,
        url: str,
        timeout: float,
        **request_kwargs: Any,
    ) -> Any:
        """Один HTTP запрос с актуальными JWT headers."""
        headers = dict(request_kwargs.pop('headers', None) or {})
        headers.update(self._get_auth_headers())

        return requests_module.request(
            method, url, headers=headers, timeout=timeout, **request_kwargs
        )

    @staticmethod
    def _get_auth_headers() -> Dict[str, str]:
        """JWT headers из TokenManager (пусто если токенов нет)."""
        try:
            from Daman_QGIS.managers.infrastructure.submodules.Msm_29_4_token_manager import (
                TokenManager,
            )
            return TokenManager.get_instance().get_auth_headers()
        except Exception as e:
            log_warning(f"Msm_29_6: Failed to obtain auth headers: {e}")
            return {}

    def _do_refresh(self) -> bool:
        """Refresh JWT через TokenManager.handle_401_response().

        Сериализуется через _refresh_lock — защищает от parallel refresh
        при concurrent requests из разных managers.
        """
        with self._refresh_lock:
            try:
                from Daman_QGIS.managers.infrastructure.submodules.Msm_29_4_token_manager import (
                    TokenManager,
                )
                return TokenManager.get_instance().handle_401_response()
            except Exception as e:
                log_error(f"{self.MODULE_ID}: Refresh raised exception: {e}")
                return False

    @staticmethod
    def _is_auth_failure(response: Any) -> bool:
        """403/401 от plugin API — нужен ли refresh+retry?

        - 401 → всегда auth (token истёк или невалиден) → refresh поможет.
        - 403 + error_code в {AUTH_FAILED, TOKEN_EXPIRED, INVALID_TOKEN}
          → refresh поможет.
        - 403 + ACCOUNT_PENDING_DELETION / INTEGRITY_MISMATCH /
          HARDWARE_MISMATCH → refresh бесполезен, не retry'им.
        - 403 без распарсиваемого error_code (nginx, WAF, edge layer) —
          refresh не поможет (это не AUTH_FAILED от приложения),
          возвращаем как final response.
        """
        if response is None:
            return False
        if response.status_code not in (401, 403):
            return False
        if response.status_code == 401:
            return True
        error_code = AuthedRequestManager._extract_error_code(response)
        return error_code in ('AUTH_FAILED', 'TOKEN_EXPIRED', 'INVALID_TOKEN')

    @staticmethod
    def _extract_error_code(response: Any) -> str:
        """Извлечь error_code из JSON body (best-effort, никогда не raises)."""
        try:
            body = response.json()
            if isinstance(body, dict):
                return str(body.get('error_code', body.get('error', '')))
        except Exception:
            pass
        return ''

    @staticmethod
    def _derive_endpoint_key(url: str) -> str:
        """Извлечь нормализованный путь из URL для circuit breaker."""
        # Отрезать query string и схему, оставить только path.
        path = url.split('?', 1)[0]
        if '://' in path:
            path = path.split('://', 1)[1]
            path = '/' + path.split('/', 1)[1] if '/' in path else '/'
        return path

    # ------------------------------------------------------------------
    # Circuit breaker (max 3 попытки / 60 секунд / endpoint)
    # ------------------------------------------------------------------

    def _check_circuit_breaker(self, endpoint_key: str) -> None:
        """Raise CircuitBreakerError если квота исчерпана."""
        now = time.monotonic()
        cutoff = now - AUTHED_REQUEST_WINDOW_SECONDS
        with self._attempts_lock:
            history = self._attempts.get(endpoint_key)
            if not history:
                return
            # Удаляем устаревшие записи.
            while history and history[0] < cutoff:
                history.popleft()
            if len(history) >= AUTHED_REQUEST_MAX_ATTEMPTS:
                oldest_age = now - history[0]
                cooldown = AUTHED_REQUEST_WINDOW_SECONDS - oldest_age
                log_error(
                    f"{self.MODULE_ID}: Circuit breaker open for {endpoint_key} "
                    f"({len(history)} attempts in {AUTHED_REQUEST_WINDOW_SECONDS}s, "
                    f"cooldown {cooldown:.1f}s)"
                )
                raise CircuitBreakerError(
                    f"Too many auth failures on {endpoint_key} — wait {cooldown:.0f}s"
                )

    def _record_attempt(self, endpoint_key: str) -> None:
        """Зарегистрировать попытку запроса для circuit breaker."""
        now = time.monotonic()
        with self._attempts_lock:
            history = self._attempts.setdefault(endpoint_key, deque())
            history.append(now)
            # Ограничиваем длину очереди (не храним старее окна).
            cutoff = now - AUTHED_REQUEST_WINDOW_SECONDS
            while history and history[0] < cutoff:
                history.popleft()

    @staticmethod
    def _sleep_backoff(attempt_index: int) -> None:
        """Exponential backoff между попытками.

        attempt_index=0 → 2s (перед первым refresh)
        attempt_index=1 → 5s (перед повтором)
        attempt_index=2 → 10s (зарезервировано)

        Note: time.sleep блокирует UI thread. Это допустимо — мы в auth-failure
        path, хочется именно дать серверу секунду перед повтором, а не
        стрелять burst-ом. Альтернатива через QTimer.singleShot потребовала
        бы async-style API, что усложнит migration BaseReferenceLoader.
        """
        if attempt_index < 0 or attempt_index >= len(AUTHED_REQUEST_BACKOFF_SECONDS):
            return
        delay = AUTHED_REQUEST_BACKOFF_SECONDS[attempt_index]
        if delay > 0:
            time.sleep(delay)

    # ------------------------------------------------------------------
    # JWT version guard (M_42 hot update)
    # ------------------------------------------------------------------

    def _check_jwt_version(self) -> None:
        """Проверить что JWT `ver` claim совпадает с PLUGIN_VERSION.

        При hot-update плагина (M_42) без рестарта QGIS токены остаются
        со старыми integrity hashes — любой запрос вернёт 403
        INTEGRITY_MISMATCH (refresh не поможет). Раннее обнаружение:
        смотрим `ver` в JWT payload, если != PLUGIN_VERSION → invalidate
        токены и raise VersionMismatchError. Caller (обычно M_29 через
        force_revalidate) форсит /validate с актуальным plugin_version,
        получает свежие integrity claims.

        Молчаливо игнорирует токен без `ver` claim (старые серверы /
        legacy токены).
        """
        try:
            from Daman_QGIS.managers.infrastructure.submodules.Msm_29_4_token_manager import (
                TokenManager,
            )
            token = TokenManager.get_instance()._access_token
        except Exception:
            return

        if not token:
            return  # нет токена — пусть upstream решит (отдельный код пути).

        claims = self._decode_jwt_payload(token)
        if claims is None:
            return  # malformed token, пусть упадёт на сервере

        token_ver = claims.get('ver')
        if not token_ver:
            return  # сервер не выставил ver — legacy путь, не блокируем

        if str(token_ver) == str(PLUGIN_VERSION):
            return  # versions match

        log_warning(
            f"{self.MODULE_ID}: JWT version mismatch "
            f"(token={token_ver}, plugin={PLUGIN_VERSION}) — "
            f"invalidating tokens, forcing re-validate"
        )
        try:
            TokenManager.get_instance().clear_tokens()
        except Exception as e:
            log_warning(f"{self.MODULE_ID}: clear_tokens raised: {e}")
        raise VersionMismatchError(
            f"JWT version {token_ver} != plugin {PLUGIN_VERSION}"
        )

    @staticmethod
    def _decode_jwt_payload(token: str) -> Optional[Dict[str, Any]]:
        """Декодировать payload JWT (без верификации подписи).

        Подпись на сервере, мы только читаем claims (ver, integrity).
        """
        try:
            parts = token.split('.')
            if len(parts) != 3:
                return None
            payload_b64 = parts[1]
            payload_b64 += '=' * (-len(payload_b64) % 4)  # base64 padding
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            data = json.loads(payload_bytes)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # UI notification (delegated to main_plugin)
    # ------------------------------------------------------------------

    def _notify_auth_failure_ui(self) -> None:
        """Вызвать зарегистрированный callback UI (если есть).

        Не raises — UI ошибки не должны мешать exception propagation
        в caller. Если callback сам выбросил исключение — глотаем.
        """
        callback = self._on_auth_failure_ui
        if callback is None:
            return
        try:
            callback()
        except Exception as e:
            log_warning(f"{self.MODULE_ID}: auth_failure_ui callback raised: {e}")
