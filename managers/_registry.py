# -*- coding: utf-8 -*-
"""
Централизованный реестр синглтон-менеджеров.

Паттерн: Registry + Lazy Singleton
Именование: по ID менеджера (M_X), например 'M_17', 'M_29'

Преимущества:
- Единая точка доступа ко всем менеджерам
- Ленивая инициализация (создаётся при первом обращении)
- Простой reset для тестов
- Консистентность с именами файлов (M_17_async_task_manager.py -> 'M_17')
- Масштабируется до 100+ менеджеров без изменений

Источники:
- https://dev.to/dentedlogic/stop-writing-giant-if-else-chains-master-the-python-registry-pattern-ldm
- https://www.geeksforgeeks.org/system-design/registry-pattern/
"""
from typing import Dict, Any, Callable, TypeVar, Optional, List

T = TypeVar('T')


class ManagerRegistry:
    """
    Централизованный реестр для singleton-менеджеров.

    Именование: по ID менеджера (M_X)

    Использование:
        # Регистрация (автоматически в __init__.py домена)
        registry.register('M_17', AsyncTaskManager)
        registry.register('M_29', LicenseManager)

        # Получение экземпляра
        async_mgr = registry.get('M_17')
        license_mgr = registry.get('M_29')

        # Альтернатива с алиасом (для частых менеджеров)
        registry.alias('async', 'M_17')
        async_mgr = registry.get('async')

        # Reset для тестов
        registry.reset('M_17')       # Один менеджер
        registry.reset()             # Все менеджеры

        # Информация
        registry.list_registered()   # ['M_1', 'M_2', ...]
        registry.list_by_domain()    # {'infrastructure': ['M_17', ...], ...}
    """

    _instances: Dict[str, Any] = {}
    _factories: Dict[str, Callable[[], Any]] = {}
    _domains: Dict[str, str] = {}  # M_X -> domain
    _aliases: Dict[str, str] = {}  # alias -> M_X

    @classmethod
    def register(
        cls,
        manager_id: str,
        factory: Callable[[], T],
        domain: str = 'unknown',
        lazy: bool = True
    ) -> None:
        """
        Регистрация менеджера.

        Args:
            manager_id: ID менеджера (M_X формат, например 'M_17')
            factory: Callable, возвращающий экземпляр (обычно класс)
            domain: Домен менеджера для группировки
            lazy: True = создать при первом get(), False = создать сейчас
        """
        # Избегаем циклического импорта - импортируем только при необходимости
        if manager_id in cls._factories:
            try:
                from utils import log_warning
                log_warning(f"ManagerRegistry: перезапись '{manager_id}'")
            except ImportError:
                pass

        cls._factories[manager_id] = factory
        cls._domains[manager_id] = domain

        if not lazy:
            cls._instances[manager_id] = factory()
            try:
                from utils import log_info
                log_info(f"ManagerRegistry: создан '{manager_id}' (eager)")
            except ImportError:
                pass

    @classmethod
    def alias(cls, alias: str, manager_id: str) -> None:
        """
        Создание алиаса для менеджера (для частых обращений).

        Args:
            alias: Короткое имя ('async', 'license')
            manager_id: ID менеджера ('M_17', 'M_29')
        """
        if manager_id not in cls._factories:
            raise KeyError(f"ManagerRegistry: '{manager_id}' не зарегистрирован")
        cls._aliases[alias] = manager_id

    @classmethod
    def get(cls, name: str) -> Any:
        """
        Получение экземпляра менеджера.

        Args:
            name: ID менеджера (M_X) или алиас

        Returns:
            Экземпляр менеджера

        Raises:
            KeyError: Если менеджер не зарегистрирован
        """
        # Разрешаем алиас
        manager_id = cls._aliases.get(name, name)

        if manager_id not in cls._instances:
            if manager_id not in cls._factories:
                raise KeyError(
                    f"ManagerRegistry: '{name}' не зарегистрирован. "
                    f"Доступные: {sorted(cls._factories.keys())}"
                )
            # FIX: Менеджеры требуют iface - получаем из qgis.utils
            try:
                from qgis.utils import iface
                cls._instances[manager_id] = cls._factories[manager_id](iface)
            except TypeError:
                # Менеджер не требует iface (например, справочники)
                cls._instances[manager_id] = cls._factories[manager_id]()
            try:
                from utils import log_info
                log_info(f"ManagerRegistry: создан '{manager_id}' (lazy)")
            except ImportError:
                pass

        return cls._instances[manager_id]

    @classmethod
    def reset(cls, name: Optional[str] = None) -> None:
        """
        Сброс менеджера(-ов) для тестирования.

        Args:
            name: ID/алиас менеджера или None для сброса всех
        """
        if name:
            manager_id = cls._aliases.get(name, name)
            if manager_id in cls._instances:
                del cls._instances[manager_id]
                try:
                    from utils import log_info
                    log_info(f"ManagerRegistry: сброшен '{manager_id}'")
                except ImportError:
                    pass
        else:
            cls._instances.clear()
            try:
                from utils import log_info
                log_info("ManagerRegistry: сброшены все менеджеры")
            except ImportError:
                pass

    @classmethod
    def is_registered(cls, name: str) -> bool:
        """Проверка регистрации."""
        manager_id = cls._aliases.get(name, name)
        return manager_id in cls._factories

    @classmethod
    def is_initialized(cls, name: str) -> bool:
        """Проверка инициализации."""
        manager_id = cls._aliases.get(name, name)
        return manager_id in cls._instances

    @classmethod
    def list_registered(cls) -> List[str]:
        """Список зарегистрированных менеджеров (отсортирован по номеру)."""
        def sort_key(x: str) -> int:
            if '_' in x:
                try:
                    return int(x.split('_')[1])
                except (ValueError, IndexError):
                    return 0
            return 0
        return sorted(cls._factories.keys(), key=sort_key)

    @classmethod
    def list_initialized(cls) -> List[str]:
        """Список инициализированных менеджеров."""
        return sorted(cls._instances.keys())

    @classmethod
    def list_by_domain(cls) -> Dict[str, List[str]]:
        """Группировка менеджеров по доменам."""
        result: Dict[str, List[str]] = {}
        for manager_id, domain in cls._domains.items():
            if domain not in result:
                result[domain] = []
            result[domain].append(manager_id)
        return {k: sorted(v) for k, v in sorted(result.items())}

    @classmethod
    def get_domain(cls, name: str) -> Optional[str]:
        """Получить домен менеджера."""
        manager_id = cls._aliases.get(name, name)
        return cls._domains.get(manager_id)


# Глобальный экземпляр
registry = ManagerRegistry()


# ============================================================
# M_4 ReferenceManagers — фабрика, не синглтон (вне registry)
# ============================================================

# M_4 — особый случай: NamedTuple с 18 суб-менеджерами, кэшируется вручную
_reference_managers_cache = None

def get_reference_managers():
    """[LEGACY] Фабрика справочных менеджеров (M_4).

    M_4 — особый случай: не синглтон-менеджер, а фабрика,
    создающая ReferenceManagers NamedTuple с 18 суб-менеджерами.
    Кэшируется вручную, не через registry.
    """
    global _reference_managers_cache
    if _reference_managers_cache is None:
        from Daman_QGIS.managers.reference.M_4_reference_manager import create_reference_managers
        _reference_managers_cache = create_reference_managers()
    return _reference_managers_cache

def reset_reference_managers():
    """Сброс кэша M_4 ReferenceManagers."""
    global _reference_managers_cache
    _reference_managers_cache = None

