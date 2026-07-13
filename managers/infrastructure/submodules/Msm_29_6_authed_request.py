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
    AUTHED_REQUEST_RECOVERY_WAIT_SECONDS,
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
        # Callback при auth failure. Возвращает True если сессия восстановлена
        # (silent re-verify через HMAC validate). См. M_29._show_auth_failure_dialog.
        self._on_auth_failure_ui: Optional[Callable[[], bool]] = None
        # D2: session-level auth lockout. Обычный bool (GIL-атомарность, прецедент
        # _is_refreshing Msm_29_4:57). Ставится ТОЛЬКО при AuthFailureError.
        # Пока стоит — request() отклоняет вызов локально без сети.
        self._auth_locked: bool = False
        # Снапшот _access_token на момент постановки lockout — для unlock
        # со сравнением (появились НОВЫЕ токены после lockout → снять флаг).
        self._auth_lock_token_snapshot: Optional[str] = None
        # D4: single-flight recovery. Event выставлен (set) когда recovery
        # НЕ идёт; сброшен (clear) на время активного recovery-цикла. Waiter'ы
        # ждут bounded-wait; таймаут → fail-fast без сети.
        self._recovery_event = threading.Event()
        self._recovery_event.set()
        # D4: строгий single-flight. Event даёт bounded-wait+rendezvous, но НЕ
        # mutual exclusion — non-blocking try-acquire выбирает ЕДИНСТВЕННОГО
        # recoverer; проигравшие уходят в bounded-wait вместо параллельного
        # destructive recovery (закрытие residual «истинно-одновременный старт»).
        self._recovery_entry_lock = threading.Lock()
        # D6: событие auth_lockout эмитится один раз на переход unlocked→locked.
        # Флаг предотвращает повторную эмиссию при последующих локальных reject.
        self._auth_lockout_event_emitted: bool = False

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
                # Сброс D2/D4 состояния — иначе после reset_instance
                # (деактивация/reactivation) старый lockout завис бы.
                cls._instance._auth_locked = False
                cls._instance._auth_lock_token_snapshot = None
                cls._instance._auth_lockout_event_emitted = False
                cls._instance._recovery_event.set()
            cls._instance = None

    def set_on_auth_failure_ui(self, callback: Callable[[], bool]) -> None:
        """Зарегистрировать callback восстановления после auth failure.

        Callback вызывается из main_plugin при инициализации M_29.
        Должен быть idempotent — может быть вызван несколько раз за
        сессию, не должен спамить диалогами при каждом 403.

        Контракт возврата:
            True — сессия восстановлена прозрачно (silent HMAC re-validate
                или принятая активация). AuthedRequestManager сделает
                финальный retry исходного запроса с свежим JWT.
            False — recovery не удалась (диалог отклонён, throttled,
                лицензия деактивирована, и т.п.). AuthedRequestManager
                поднимет AuthFailureError, caller вернёт None.
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
            None — транзиент/недоступно, токены целы, повтор при следующем
                обращении. Достижимо: ImportError requests; D1.5 транзиент
                (access истёк, но refresh жив — просроченный токен в сеть не
                ушёл, сессия НЕ запирается). Потребители уже обрабатывают None
                штатно (BaseReferenceLoader кэширует только при не-None;
                M_37 профиль повторится при старте).

        Raises:
            CircuitBreakerError: исчерпан лимит 3 попытки/60с на endpoint.
            AuthFailureError: refresh упал или повтор после refresh = 403;
                либо session-level lockout (D2) отклонил вызов локально;
                либо истёк bounded-wait single-flight recovery (D4).
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

        # ---- Канонический порядок проверок на входе (D2, Hard) ----
        # D2-unlock (снапшот-сравнение) → CB-check → jwt-version-check →
        # D2-fail-fast → D4 (bounded-wait) → D1-guard (headers-once + D1.5).

        # D2-unlock: если появились НОВЫЕ токены после lockout — снять флаг.
        self._maybe_unlock_auth(ep_key)

        # CB-check ДО D1-guard: guard-fetch может дёрнуть сетевой _auto_refresh
        # (Msm_29_4:209-211), при открытом CB это лишняя работа.
        self._check_circuit_breaker(ep_key)

        # version-check ДО D2-fail-fast: иначе при lockout+hot-update гаснет
        # единственный авто-канал force_revalidate (M_29:574-587, Hard-12).
        self._check_jwt_version()

        # D2-fail-fast: lockout стоит — отклоняем локально, без сети,
        # БЕЗ _record_attempt (серверного отказа не было).
        if self._auth_locked:
            raise AuthFailureError(
                f"Auth locked (session-level) — rejecting {ep_key} locally"
            )

        # D4: если идёт recovery-цикл (Event сброшен) — bounded-wait. После
        # пробуждения перечитываем токены и ПОВТОРЯЕМ D2-unlock/fail-fast.
        if not self._recovery_event.is_set():
            woke = self._recovery_event.wait(
                timeout=AUTHED_REQUEST_RECOVERY_WAIT_SECONDS
            )
            if not woke:
                # Таймаут: исход recovery неизвестен. Fail-fast локальным
                # AuthFailureError без сети, БЕЗ D2-флага и БЕЗ _record_attempt.
                log_warning(
                    f"{self.MODULE_ID}: recovery wait timeout "
                    f"({AUTHED_REQUEST_RECOVERY_WAIT_SECONDS}s) on {ep_key} — "
                    f"fail-fast without lockout"
                )
                raise AuthFailureError(
                    f"Recovery in progress timed out on {ep_key}"
                )
            # Проснулись после чужого recovery: токены могли смениться.
            self._maybe_unlock_auth(ep_key)
            if self._auth_locked:
                raise AuthFailureError(
                    f"Auth locked after recovery wait — rejecting {ep_key}"
                )

        # ---- D1-guard (headers-once + D1.5) ----
        # Снимаем headers-снимок ОДИН раз (закрытие TOCTOU между guard-проверкой
        # и первым запросом). guard_result: None = продолжить с этими headers,
        # 'transient' = вернуть None (токены целы), 'recover' = уйти в recovery.
        headers_snapshot, guard_result = self._auth_guard()

        if guard_result == 'transient':
            # D1.5 транзиент: refresh жив, просроченный токен в сеть не ушёл,
            # сессия НЕ запирается. Возврат None (существующий контракт:
            # loader пишет кэш только при не-None; профиль повторится при старте).
            return None

        if guard_result == 'recover':
            # Нет токенов ИЛИ refresh мёртв → destructive recovery-путь.
            # D4 строгий single-flight: non-blocking try-acquire выбирает
            # единственного recoverer; проигравший идёт в bounded-wait.
            if self._recovery_entry_lock.acquire(blocking=False):
                # Мы — единственный recoverer. Лок освободит _guard_recovery
                # в finally (рядом с Event.set(), после lockout+снапшота).
                return self._guard_recovery(
                    requests, method, url, timeout_value, ep_key, **request_kwargs
                )
            # Проиграли гонку — waiter: bounded-wait, затем D2-повтор.
            return self._wait_for_recovery_as_loser(ep_key)

        # Первая попытка. NB: _record_attempt здесь НЕ вызываем — circuit breaker
        # должен срабатывать только на AUTH-FAILURES, а не на нормальные запросы.
        # Иначе плагин при cold start (3+ обращений к /api/plugin/data за справочники)
        # ложно открывает CB и блокирует всю загрузку. Регрессия 0.9.894 → fixed.
        response = self._raw_request(
            requests, method, url, timeout_value,
            headers_override=headers_snapshot, **request_kwargs
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

        # ---- Реактивный recovery-цикл (D4 single-flight) ----
        # D4 строгий single-flight: non-blocking try-acquire выбирает
        # единственного recoverer. Проигравший гонку — НЕ входит в реактивный
        # цикл (иначе параллельный destructive recovery), уходит в bounded-wait.
        if not self._recovery_entry_lock.acquire(blocking=False):
            return self._wait_for_recovery_as_loser(ep_key)

        # Помечаем recovery-in-progress. Release-ordering (Hard): при провале
        # D2-флаг+снапшот ставятся ДО Event.set() (внутри try перед raise);
        # finally выставляет Event последним, лок освобождается тем же потоком,
        # что захватил. Проснувшиеся waiter'ы увидят уже проставленный lockout,
        # а не уйдут в N параллельных recovery.
        self._recovery_event.clear()
        try:
            # Backoff перед refresh (2s).
            self._sleep_backoff(attempt_index=0)

            # Refresh JWT через TokenManager.
            if not self._do_refresh():
                log_error(
                    f"{self.MODULE_ID}: Refresh failed after {response.status_code} "
                    f"on {ep_key} — invalidating session"
                )
                if self._notify_auth_failure_ui():
                    # Callback восстановил сессию через HMAC re-validate
                    # (типичный кейс — JWT_SECRET ротирован сервером, refresh
                    # подписан старым ключом). Делаем финальный retry со свежим JWT.
                    final_response = self._retry_after_recovery(
                        requests, method, url, timeout_value, ep_key, **request_kwargs
                    )
                    if final_response is not None:
                        return final_response
                self._set_auth_lockout(ep_key)
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
                if self._notify_auth_failure_ui():
                    final_response = self._retry_after_recovery(
                        requests, method, url, timeout_value, ep_key, **request_kwargs
                    )
                    if final_response is not None:
                        return final_response
                self._set_auth_lockout(ep_key)
                raise AuthFailureError(
                    f"Retry after refresh failed: {retry_response.status_code} on {ep_key}"
                )

            return retry_response
        finally:
            # Успех: токены установлены до этой точки by construction.
            # Провал: lockout+снапшот уже проставлены перед raise.
            # Порядок (Hard): Event.set() (rendezvous) → release лока. Лок
            # освобождает тот же поток, что захватил (реактивный fork выше).
            self._recovery_event.set()
            self._recovery_entry_lock.release()

    def _retry_after_recovery(
        self,
        requests_module: Any,
        method: str,
        url: str,
        timeout: float,
        ep_key: str,
        **request_kwargs: Any,
    ) -> Optional[Any]:
        """Финальный retry после успешного recovery callback'а.

        Вызывается только если _notify_auth_failure_ui вернул True
        (сессия восстановлена через HMAC re-validate). Делает один
        запрос с новым JWT. При success возвращает response, при
        auth failure возвращает None (caller raise AuthFailureError).
        """
        log_warning(
            f"{self.MODULE_ID}: Session recovered via callback, "
            f"final retry on {ep_key}"
        )
        try:
            final_response = self._raw_request(
                requests_module, method, url, timeout, **request_kwargs
            )
        except Exception as e:
            log_warning(f"{self.MODULE_ID}: Final retry raised: {e}")
            return None
        if self._is_auth_failure(final_response):
            self._record_attempt(ep_key)
            log_error(
                f"{self.MODULE_ID}: Final retry still failed after recovery: "
                f"{final_response.status_code} {self._extract_error_code(final_response)} "
                f"on {ep_key}"
            )
            return None
        return final_response

    # ------------------------------------------------------------------
    # D1 no-token guard + D1.5 refresh-liveness дискриминатор
    # ------------------------------------------------------------------

    def _auth_guard(self) -> "tuple[Dict[str, str], Optional[str]]":
        """D1-guard: снять headers-снимок ОДИН раз и применить D1.5.

        Returns:
            (headers_snapshot, guard_result):
                headers_snapshot — снимок заголовков (для headers-once первой
                    попытки; пуст если токенов нет).
                guard_result:
                    None — заголовки непусты и access НЕ истёк → выполнять
                        первую попытку с этим снимком.
                    'transient' (D1.5) — access истёк, но refresh ЖИВ → в сеть
                        просроченный токен не слать, вернуть None из request()
                        (токены целы, сессия НЕ запирается).
                    'recover' — токенов нет ИЛИ (access истёк И refresh МЁРТВ)
                        → destructive guard-recovery (D1.1/D1.2), возможен
                        D2-lockout.
        """
        # NB: _get_auth_headers() не строго read-only — при access у порога
        # истечения и живом refresh Msm_29_4.get_auth_headers() синхронно
        # вызывает _auto_refresh (side-effect: обновляет _access_token). D1.5
        # это поглощает: свежий токен → guard_result=None (первая попытка со
        # свежим); транзиент отбрасывает снимок до сети. Fail-closed цел.
        headers_snapshot = self._get_auth_headers()

        # Пусто (токенов нет) — контракт Msm_29_4 get_auth_headers()→{} (D1.3).
        # Голый запрос в сеть НЕ слать → recovery-путь.
        if not headers_snapshot:
            return headers_snapshot, 'recover'

        # D1.5: снимок непуст, но access фактически истёк?
        access_expired, refresh_alive = self._read_token_liveness()
        if not access_expired:
            # Горячий путь: access ещё валиден — обычная первая попытка.
            return headers_snapshot, None

        # Access истёк. Просроченный токен в сеть НЕ отправлять.
        # Дискриминатор по живучести refresh-токена (ядро RISK-1):
        if refresh_alive:
            # refresh ЖИВ → транзиент (race-окно _is_refreshing ЛИБО
            # не-фатальный inline-refresh-провал). НЕ destructive recovery,
            # НЕ D2-флаг, НЕ _record_attempt. Возврат None из request().
            log_warning(
                f"{self.MODULE_ID}: access expired but refresh alive — "
                f"transient, session preserved (retry on next access)"
            )
            return headers_snapshot, 'transient'

        # refresh МЁРТВ (пуст/истёк) → подлинный auth-отказ → recovery + lockout.
        return headers_snapshot, 'recover'

    @staticmethod
    def _read_token_liveness() -> "tuple[bool, bool]":
        """Прочитать живучесть токенов из приватных полей TokenManager.

        ЧИТАЕТ (не пишет) приватные поля Msm_29_4 — прецедент чтения
        приватного поля Msm_29_6:499 (_access_token) + те же поля, что
        читает has_valid_tokens (Msm_29_4:173-179). Hard-6: Msm_29_4 не правится.

        Returns:
            (access_expired, refresh_alive):
                access_expired — True если access-токена нет ИЛИ истёк.
                refresh_alive — True если refresh-токен непуст И не истёк.
        """
        try:
            from Daman_QGIS.managers.infrastructure.submodules.Msm_29_4_token_manager import (
                TokenManager,
            )
            tm = TokenManager.get_instance()
            now = time.time()
            access_expired = (
                not tm._access_token or now >= tm._access_expires_at
            )
            refresh_alive = bool(
                tm._refresh_token and now < tm._refresh_expires_at
            )
            return access_expired, refresh_alive
        except Exception as e:
            # Не смогли прочитать — консервативно: считаем access истёкшим,
            # refresh мёртвым (→ recovery-путь, fail-closed).
            log_warning(f"Msm_29_6: token liveness read failed: {e}")
            return True, False

    def _guard_recovery(
        self,
        requests_module: Any,
        method: str,
        url: str,
        timeout: float,
        ep_key: str,
        **request_kwargs: Any,
    ) -> Optional[Any]:
        """D1 guard-recovery: нет токенов ИЛИ refresh мёртв (D1.1/D1.2).

        Сетевой запрос НЕ выполнялся (голый/просроченный токен в сеть не ушёл).
        Существующий recovery-путь: _do_refresh() → при провале
        _notify_auth_failure_ui() → запрос ТОЛЬКО после успешного
        восстановления (заголовки перечитаны, непусты). Не восстановились →
        D2-lockout + AuthFailureError.

        D1.1: _record_attempt пишется ТОЛЬКО при провале восстановления,
            непосредственно перед raise (не при входе — анти-0.9.894).
        D1.2: пост-recovery запрос = строго ОДИН _raw_request через
            _retry_after_recovery (не полный pipeline → нет рекурсии recovery).
        D4 single-flight: вызывается ТОЛЬКО победителем гонки за
            _recovery_entry_lock (захвачен в request() перед вызовом). Цикл
            обёрнут Event.clear()/set(); lockout+снапшот ставятся ДО Event.set()
            (release-ordering); лок освобождается в finally тем же потоком.
        """
        self._recovery_event.clear()
        try:
            # Backoff перед refresh (2s) — как в реактивном пути.
            self._sleep_backoff(attempt_index=0)

            if self._do_refresh():
                # Refresh восстановил токены — финальный ОДИН retry (D1.2).
                final_response = self._retry_after_recovery(
                    requests_module, method, url, timeout, ep_key, **request_kwargs
                )
                if final_response is not None:
                    return final_response
                # Финальный retry сам провалился по auth → lockout.
                self._record_attempt(ep_key)
                self._set_auth_lockout(ep_key)
                raise AuthFailureError(
                    f"Guard recovery: retry after refresh failed on {ep_key}"
                )

            # Refresh не удался — пробуем silent HMAC re-validate (callback).
            if self._notify_auth_failure_ui():
                final_response = self._retry_after_recovery(
                    requests_module, method, url, timeout, ep_key, **request_kwargs
                )
                if final_response is not None:
                    return final_response

            # Восстановление не удалось (D1.1: _record_attempt только здесь).
            self._record_attempt(ep_key)
            log_error(
                f"{self.MODULE_ID}: Guard recovery failed on {ep_key} "
                f"(no tokens / dead refresh) — locking session"
            )
            self._set_auth_lockout(ep_key)
            raise AuthFailureError(
                f"Guard recovery failed on {ep_key}"
            )
        finally:
            # Порядок (Hard): Event.set() (rendezvous) → release лока. Лок
            # освобождает тот же поток, что захватил (guard-recovery fork).
            self._recovery_event.set()
            self._recovery_entry_lock.release()

    def _wait_for_recovery_as_loser(self, ep_key: str) -> Optional[Any]:
        """D4: путь проигравшего гонку за _recovery_entry_lock.

        Мы НЕ вошли в destructive recovery-цикл (его ведёт победитель гонки).
        Ждём bounded-wait на _recovery_event (rendezvous), затем перечитываем
        состояние lockout. Release-ordering гарантирует: победитель проставил
        lockout+снапшот ДО Event.set() → после пробуждения мы видим уже
        актуальный _auth_locked.

        Исходы (единообразно с существующей D4-веткой request() :268-288):
            - таймаут → AuthFailureError (исход recovery неизвестен, БЕЗ D2/CB);
            - recovery залочил сессию → AuthFailureError (подлинный auth-отказ);
            - recovery успешен (токены свежи) → None-транзиент: повтор при
              следующем обращении (loader кэш не пишет; профиль повторится).
        """
        woke = self._recovery_event.wait(
            timeout=AUTHED_REQUEST_RECOVERY_WAIT_SECONDS
        )
        if not woke:
            log_warning(
                f"{self.MODULE_ID}: recovery wait timeout "
                f"({AUTHED_REQUEST_RECOVERY_WAIT_SECONDS}s) on {ep_key} "
                f"(lost single-flight race) — fail-fast without lockout"
            )
            raise AuthFailureError(
                f"Recovery in progress timed out on {ep_key}"
            )
        # Проснулись после чужого recovery: токены могли смениться.
        self._maybe_unlock_auth(ep_key)
        if self._auth_locked:
            raise AuthFailureError(
                f"Auth locked after recovery wait — rejecting {ep_key}"
            )
        # Recovery завершился успехом: токены свежи. Возврат None-транзиент —
        # повтор при следующем обращении (существующий контракт).
        return None

    # ------------------------------------------------------------------
    # D2 session-level auth lockout
    # ------------------------------------------------------------------

    def _maybe_unlock_auth(self, ep_key: str) -> None:
        """D2-unlock со снапшот-сравнением.

        Снятие lockout: если TokenManager.has_valid_tokens() И текущий
        _access_token ОТЛИЧАЕТСЯ от снапшота (появились НОВЫЕ токены после
        lockout) → флаг снимается. Закрывает дыру «lockout при серверно-
        валидных токенах → мгновенный unlock → повторные циклы»; self-heal
        сохраняется (свежие токены != снапшота → unlock проходит).
        """
        if not self._auth_locked:
            return
        try:
            from Daman_QGIS.managers.infrastructure.submodules.Msm_29_4_token_manager import (
                TokenManager,
            )
            tm = TokenManager.get_instance()
            if tm.has_valid_tokens() and tm._access_token != self._auth_lock_token_snapshot:
                self._auth_locked = False
                self._auth_lock_token_snapshot = None
                self._auth_lockout_event_emitted = False
                log_warning(
                    f"{self.MODULE_ID}: auth unlocked (new tokens after lockout) "
                    f"on {ep_key}"
                )
        except Exception as e:
            log_warning(f"{self.MODULE_ID}: auth unlock check failed: {e}")

    def _set_auth_lockout(self, ep_key: str) -> None:
        """Поставить D2-lockout: флаг + снапшот _access_token + D6-эмит once.

        Снапшот запоминается для unlock-сравнения (D2). D6-событие auth_lockout
        эмитится ОДИН раз на переход unlocked→locked (best-effort).
        """
        already_locked = self._auth_locked
        try:
            from Daman_QGIS.managers.infrastructure.submodules.Msm_29_4_token_manager import (
                TokenManager,
            )
            self._auth_lock_token_snapshot = TokenManager.get_instance()._access_token
        except Exception:
            self._auth_lock_token_snapshot = None
        self._auth_locked = True
        log_warning(f"{self.MODULE_ID}: session auth lockout set on {ep_key}")

        # D6: эмит auth_lockout один раз на переход unlocked→locked.
        if not already_locked and not self._auth_lockout_event_emitted:
            self._auth_lockout_event_emitted = True
            self._emit_auth_lockout_event(ep_key)

    def _emit_auth_lockout_event(self, ep_key: str) -> None:
        """D6: best-effort telemetry-эмит auth_lockout (без PII, не блокирует raise)."""
        try:
            from Daman_QGIS.managers._registry import registry
            telemetry = registry.get('M_32')
            if telemetry is not None:
                telemetry.track_event(
                    'auth_lockout',
                    {'reason': 'auth_failure', 'endpoint_key': ep_key},
                )
        except Exception as e:
            log_warning(f"{self.MODULE_ID}: auth_lockout telemetry emit failed: {e}")

    # ------------------------------------------------------------------
    # Внутренняя реализация
    # ------------------------------------------------------------------

    def _raw_request(
        self,
        requests_module: Any,
        method: str,
        url: str,
        timeout: float,
        headers_override: Optional[Dict[str, str]] = None,
        **request_kwargs: Any,
    ) -> Any:
        """Один HTTP запрос с JWT headers.

        headers_override:
            None (default) — ПЕРЕЧИТАТЬ auth-заголовки из TokenManager
                (штатное поведение для retry-путей после успешного refresh:
                D1.4 headers-once касается ТОЛЬКО первой попытки).
            dict — использовать этот снимок заголовков как есть (D1-guard
                headers-once: закрытие TOCTOU между guard-проверкой и первым
                запросом; снимок уже прошёл D1.5-дискриминатор).
        """
        headers = dict(request_kwargs.pop('headers', None) or {})
        if headers_override is not None:
            headers.update(headers_override)
        else:
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

    def _notify_auth_failure_ui(self) -> bool:
        """Вызвать зарегистрированный callback и вернуть статус recovery.

        Не raises — UI ошибки не должны мешать exception propagation
        в caller. Если callback сам выбросил исключение — глотаем,
        возвращаем False.

        Returns:
            True если callback восстановил сессию (silent re-verify
                или принятая активация). False иначе.
        """
        callback = self._on_auth_failure_ui
        if callback is None:
            return False
        try:
            result = callback()
            return bool(result)
        except Exception as e:
            log_warning(f"{self.MODULE_ID}: auth_failure_ui callback raised: {e}")
            return False
