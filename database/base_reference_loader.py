# -*- coding: utf-8 -*-
"""
Базовый класс для загрузки справочных данных из JSON через Daman API.

Требует интернет-соединение. Кэширование только в памяти на время сессии.

Предоставляет общую функциональность для всех менеджеров справочных данных:
- Загрузка JSON через API (daman.tools)
- Кэширование в памяти на время сессии
- Построение индексов для быстрого поиска

API URL: constants.API_BASE_URL
Формат запроса: /data/{filename} или ?action=data&file={filename}
"""

import json
from typing import Dict, List, Any, Optional
from Daman_QGIS.utils import log_warning, log_error


class BaseReferenceLoader:
    """Базовый класс для загрузки справочных данных через Daman API.

    Кэш общий для всех экземпляров (на уровне класса).
    Данные загружаются один раз за сессию.
    """

    # Общий кэш для всех экземпляров (загрузка один раз за сессию)
    _shared_cache: Dict[str, Any] = {}
    _shared_index_cache: Dict[str, Dict] = {}
    # Был ли хотя бы один успешный 200 от /api/plugin/data в текущей сессии.
    # Используется для классификации 404 как transient (truncation в VPN-канале)
    # vs permanent (файла действительно нет) в _load_from_remote.
    _seen_remote_success: bool = False

    def __init__(self):
        """Инициализация базового загрузчика.

        Данные загружаются через Daman API, локальные пути не используются.
        """
        pass

    def _load_json(self, filename: str) -> Any:
        """
        Загружает JSON файл через Daman API с кэшированием в памяти.

        Требует интернет-соединение. Кэш хранится только на время сессии.

        Args:
            filename: Имя JSON файла

        Returns:
            Данные из файла или None при ошибке
        """
        # Проверяем расширение файла
        if not filename.endswith('.json'):
            log_warning(f"Попытка загрузить не-JSON файл: {filename}")
            return None

        # Проверяем общий кэш (один раз за сессию)
        if filename in BaseReferenceLoader._shared_cache:
            return BaseReferenceLoader._shared_cache[filename]

        # Загрузка через Daman API (требует интернет)
        data = self._load_from_remote(filename)

        if data is not None:
            BaseReferenceLoader._shared_cache[filename] = data

        return data

    # Retry-стратегия для transient transport-уровневых ошибок.
    # Root cause: VPN-канал (AmneziaVPN multi-exit, mobile, плохой Wi-Fi) теряет
    # пакеты на больших ответах /api/plugin/data — VPS отвечает 200 OK с полным
    # gzip body, но клиент видит timeout / 404 / пустое тело при 200.
    # Сервер не отдаёт Content-Length для gzip-streamed ответов Next.js,
    # поэтому клиент не может валидировать целостность и молча принимает
    # обрезанные данные. Retry с backoff закрывает разрыв.
    _MAX_REMOTE_ATTEMPTS = 3
    _REMOTE_BACKOFF_SECONDS = (1.0, 3.0)  # перед попытками 2 и 3

    def _load_from_remote(self, filename: str) -> Optional[Any]:
        """
        Загрузить JSON через Daman API с JWT авторизацией и retry на transient.

        Auth/refresh/circuit-breaker логика — в Msm_29_6_AuthedRequestManager
        (single source of truth), здесь только transport-retry для GET справочников
        и парсинг ответа.

        Retry (до 3 попыток, backoff 1s/3s) на transient-ошибках:
          - requests.exceptions.Timeout
          - requests.exceptions.ConnectionError
          - status 200 с пустым/обрезанным body (json.JSONDecodeError)
          - status 404 — только если в текущей сессии уже был успешный 200
            (явно transient — TCP truncation от VPN-прокси, не реальное отсутствие)
          - status 5xx (transient серверная ошибка)

        НЕ ретрается (немедленный return None):
          - AuthFailureError, CircuitBreakerError, VersionMismatchError
            (Msm_29_6 уже сам обработал)
          - status 403 (permanent: ACCOUNT_PENDING_DELETION, INTEGRITY_MISMATCH, ...)
          - status 404 при отсутствии prior success (реально нет файла)
          - прочие requests.exceptions.RequestException (DNS, SSL, ...)

        Args:
            filename: Имя JSON файла (с или без .json расширения)

        Returns:
            Данные из файла или None при permanent ошибке / исчерпанных попытках
        """
        from Daman_QGIS.constants import get_api_url
        from Daman_QGIS.managers.infrastructure.submodules.Msm_29_6_authed_request import (
            AuthedRequestManager,
            AuthFailureError,
            CircuitBreakerError,
            VersionMismatchError,
        )

        try:
            import requests
        except ImportError:
            log_warning("BaseReferenceLoader: requests не установлен, remote загрузка недоступна")
            return None

        import time

        # Убираем .json для API запроса (API добавит сам)
        file_param = filename.replace('.json', '')
        url = get_api_url("data", file=file_param)

        last_transient_reason: Optional[str] = None

        for attempt in range(1, self._MAX_REMOTE_ATTEMPTS + 1):
            if attempt > 1:
                delay = self._REMOTE_BACKOFF_SECONDS[attempt - 2]
                log_warning(
                    f"BaseReferenceLoader: Retry {attempt}/{self._MAX_REMOTE_ATTEMPTS} "
                    f"для {filename} после {last_transient_reason} (через {delay}s)"
                )
                time.sleep(delay)

            try:
                response = AuthedRequestManager.get_instance().request(
                    "GET",
                    url,
                    # Один endpoint_key на все Base_*.json — общая квота на auth-уровне.
                    endpoint_key="/api/plugin/data",
                )
            except CircuitBreakerError as e:
                # Тихо — не спамить запросами и не пугать юзера повторно.
                log_warning(f"BaseReferenceLoader: {filename} skipped: {e}")
                return None
            except AuthFailureError as e:
                # UI-сообщение «Требуется повторная активация» уже показано
                # из AuthedRequestManager (через registered callback).
                log_error(f"BaseReferenceLoader: Auth failure для {filename}: {e}")
                return None
            except VersionMismatchError as e:
                # M_42 hot update detected — токены инвалидированы, форсим re-validate.
                log_warning(f"BaseReferenceLoader: {filename} version mismatch: {e}")
                self._handle_jwt_version_mismatch()
                return None
            except requests.exceptions.Timeout:
                last_transient_reason = "timeout"
                continue
            except requests.exceptions.ConnectionError as e:
                last_transient_reason = f"connection error ({e})"
                continue
            except requests.exceptions.RequestException as e:
                # DNS/SSL/прочие — permanent, retry не поможет.
                log_warning(f"BaseReferenceLoader: Ошибка сети при загрузке {filename}: {e}")
                return None

            if response is None:
                # AuthedRequestManager уже залогировал причину.
                return None

            status = response.status_code

            if status == 200:
                try:
                    response_json = response.json()
                except json.JSONDecodeError as e:
                    # Пустое/обрезанное тело при 200 — классический симптом
                    # truncation gzip-stream без Content-Length. Transient.
                    last_transient_reason = f"empty body / parse error ({e})"
                    continue
                # Сервер оборачивает данные в {'data': ..., 'copyright': ...}
                data = (
                    response_json.get('data', response_json)
                    if isinstance(response_json, dict)
                    else response_json
                )
                BaseReferenceLoader._seen_remote_success = True
                return data

            if status == 403:
                # 403 не-AUTH_FAILED (ACCOUNT_PENDING_DELETION, INTEGRITY_MISMATCH,
                # HARDWARE_MISMATCH) — permanent, refresh не помог бы.
                try:
                    error_body = response.json()
                    error_code = error_body.get('error_code', error_body.get('error', 'unknown'))
                except Exception:
                    error_code = response.text[:100] if response.text else 'empty'
                log_warning(
                    f"BaseReferenceLoader: Доступ запрещён к {filename} "
                    f"(reason: {error_code})"
                )
                return None

            if status == 404:
                if BaseReferenceLoader._seen_remote_success:
                    # Файл уже отдавался успешно ранее в этой сессии — текущий 404
                    # суспект transient (VPN-truncation / nginx misroute).
                    last_transient_reason = "404 (suspect transient, prior success in session)"
                    continue
                log_warning(f"BaseReferenceLoader: Файл {filename} не найден на сервере")
                return None

            if 500 <= status < 600:
                last_transient_reason = f"HTTP {status}"
                continue

            log_warning(f"BaseReferenceLoader: HTTP {status} для {filename}")
            return None

        log_warning(
            f"BaseReferenceLoader: {filename} не загружен после "
            f"{self._MAX_REMOTE_ATTEMPTS} попыток (последняя причина: {last_transient_reason})"
        )
        return None

    @staticmethod
    def _handle_jwt_version_mismatch() -> None:
        """JWT integrity claims устарели после M_42 hot-update.

        Форсим M_29.force_revalidate() — verify() с обнулённым кэшем сессии,
        чтобы /validate выдал свежий JWT с актуальными integrity claims
        для текущей PLUGIN_VERSION. Best-effort — если M_29 недоступен,
        возвращаемся (next request попадёт в _check_jwt_version с уже
        очищенными токенами и пойдёт по обычному auth-failure пути).
        """
        try:
            from Daman_QGIS.managers._registry import registry
            license_mgr = registry.get('M_29')
            if license_mgr is None:
                return
            license_mgr.force_revalidate()
        except Exception as e:
            log_warning(f"BaseReferenceLoader: Force re-validate failed: {e}")

    def _build_index(self, data: List[Dict], key_field: str) -> Dict:
        """
        Построить индекс для быстрого поиска по ключу

        Args:
            data: Список словарей для индексации
            key_field: Имя поля для использования как ключ

        Returns:
            Словарь {значение_ключа: элемент}
        """
        index = {}
        for item in data:
            if key_field in item and item[key_field] is not None:
                index[item[key_field]] = item
        return index

    def _get_by_key(self, data_getter, index_key: str, field_name: str, value: Any) -> Optional[Dict]:
        """
        Универсальный метод поиска по ключу с кэшированием индекса

        Args:
            data_getter: Callable для получения полного списка данных
            index_key: Ключ для хранения индекса в кэше
            field_name: Имя поля для индексации
            value: Значение для поиска

        Returns:
            Найденный элемент или None
        """
        # Проверяем общий индексный кэш
        if index_key not in BaseReferenceLoader._shared_index_cache:
            data = data_getter()
            BaseReferenceLoader._shared_index_cache[index_key] = self._build_index(data, field_name)

        return BaseReferenceLoader._shared_index_cache[index_key].get(value)

    @classmethod
    def clear_cache(cls):
        """Очистить весь общий кэш (данные и индексы)"""
        cls._shared_cache.clear()
        cls._shared_index_cache.clear()

    @classmethod
    def reload(cls, filename: Optional[str] = None):
        """
        Перезагрузить данные из файла

        Args:
            filename: Имя файла для перезагрузки. Если None, очищается весь кэш
        """
        if filename:
            # Удаляем конкретный файл из кэша
            if filename in cls._shared_cache:
                del cls._shared_cache[filename]

            # Очищаем связанные индексы (они будут пересозданы при следующем обращении)
            cls._shared_index_cache.clear()
        else:
            # Очищаем весь кэш
            cls.clear_cache()
