"""
Msm_41_4: SpeedProfiles - Профили скоростей для сетевого анализа.

Управление встроенными и пользовательскими профилями скоростей.
Маппинг OSM highway_type -> speed_kmh для walk/drive/fire_truck.
Нормативные пресеты по СП 42.13330.2016, 123-ФЗ, ГОСТ Р 22.3.17-2020.

Родительский менеджер: M_41_IsochroneTransportManager
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from Daman_QGIS.utils import log_info, log_warning

__all__ = [
    'Msm_41_4_SpeedProfiles',
    'SpeedProfile',
    'RouteResult',
    'IsochroneResult',
    'BUILTIN_PROFILES',
    'REGULATORY_PRESETS',
]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SpeedProfile:
    """Профиль скоростей для типов дорог."""
    name: str
    speeds: dict[str, float]           # highway_type -> km/h
    default_speed: float               # Скорость по умолчанию (км/ч)
    description: str = ''


@dataclass
class RouteResult:
    """Результат расчета маршрута."""
    geometry: object                   # QgsGeometry (LineString)
    distance_m: float                  # Расстояние (метры)
    duration_s: float                  # Время (секунды)
    profile: str                       # Использованный профиль
    origin: object                     # QgsPointXY
    destination: object                # QgsPointXY
    entry_cost_s: float = 0.0         # Snap origin -> ближайшая вершина графа (сек)
    exit_cost_s: float = 0.0          # Snap ближайшая вершина -> destination (сек)
    success: bool = True
    error_message: str = ''


@dataclass
class IsochroneResult:
    """Результат генерации изохроны."""
    geometry: object                   # QgsGeometry (Polygon)
    interval: int                      # Интервал (сек или м)
    unit: str                          # 'time' / 'distance'
    area_sq_m: float                   # Площадь полигона
    profile: str                       # Использованный профиль
    center: object                     # QgsPointXY
    entry_cost_s: float = 0.0         # Snap center -> ближайшая вершина графа (сек)
    method: str = 'dijkstra_tin'       # 'dijkstra_tin' / 'servicearea_buffer'


# ---------------------------------------------------------------------------
# Встроенные профили скоростей
# ---------------------------------------------------------------------------

BUILTIN_PROFILES: dict[str, SpeedProfile] = {
    'walk': SpeedProfile(
        name='walk',
        description='Пешеход (ГОСТ Р 22.3.17-2020: 3-4 км/ч)',
        default_speed=4.0,
        speeds={
            'footway': 4.5, 'pedestrian': 4.5, 'path': 3.5,
            'steps': 2.0, 'cycleway': 4.0, 'living_street': 4.0, 'residential': 4.0,
            'service': 4.0, 'tertiary': 4.0, 'secondary': 4.0,
            'primary': 3.5,
            'trunk': 0,       # запрещено для пешеходов
            'motorway': 0,    # запрещено для пешеходов
            'trunk_link': 0,
            'motorway_link': 0,
        },
    ),
    'drive': SpeedProfile(
        name='drive',
        description='Легковой автомобиль (по типу дороги)',
        default_speed=40.0,
        speeds={
            'motorway': 110, 'trunk': 90, 'primary': 60,
            'secondary': 50, 'tertiary': 40, 'unclassified': 30,
            'residential': 20, 'living_street': 10, 'service': 15,
            'motorway_link': 60, 'trunk_link': 50,
            'primary_link': 40, 'secondary_link': 30,
            'tertiary_link': 30,
            'footway': 0, 'pedestrian': 0, 'path': 0, 'steps': 0,
        },
    ),
    'fire_truck': SpeedProfile(
        name='fire_truck',
        description='Пожарная техника (123-ФЗ: 10 мин город, 20 мин село)',
        default_speed=50.0,
        speeds={
            'motorway': 90, 'trunk': 80, 'primary': 70,
            'secondary': 60, 'tertiary': 50, 'unclassified': 40,
            'residential': 30, 'living_street': 20, 'service': 20,
            'motorway_link': 60, 'trunk_link': 50,
            'primary_link': 50, 'secondary_link': 40,
            'tertiary_link': 40,
            'footway': 0, 'pedestrian': 0, 'path': 0, 'steps': 0,
        },
    ),
}


# ---------------------------------------------------------------------------
# Нормативные пресеты
# ---------------------------------------------------------------------------

REGULATORY_PRESETS: dict[str, dict] = {
    'kindergarten_300m': {
        'profile': 'walk', 'unit': 'distance', 'intervals': [300],
        'description': 'Детский сад (СП 42.13330.2016)',
    },
    'school_500m': {
        'profile': 'walk', 'unit': 'distance', 'intervals': [500],
        'description': 'Школа 500м (СП 42.13330.2016)',
    },
    'school_750m': {
        'profile': 'walk', 'unit': 'distance', 'intervals': [750],
        'description': 'Школа 750м (СП 42.13330.2016)',
    },
    'clinic_1000m': {
        'profile': 'walk', 'unit': 'distance', 'intervals': [1000],
        'description': 'Поликлиника (СП 42.13330.2016)',
    },
    'bus_stop_500m': {
        'profile': 'walk', 'unit': 'distance', 'intervals': [500],
        'description': 'Остановка ОТ (СП 42.13330.2016)',
    },
    'fire_urban_10min': {
        'profile': 'fire_truck', 'unit': 'time', 'intervals': [600],
        'description': 'Пожарная часть, город (123-ФЗ ст.76)',
    },
    'fire_rural_20min': {
        'profile': 'fire_truck', 'unit': 'time', 'intervals': [1200],
        'description': 'Пожарная часть, село (123-ФЗ ст.76)',
    },
    'evacuation_walk': {
        'profile': 'walk', 'unit': 'time', 'intervals': [300, 600, 900, 1800],
        'description': 'Пешая эвакуация (ГОСТ Р 22.3.17-2020)',
    },
}


# ---------------------------------------------------------------------------
# Менеджер профилей
# ---------------------------------------------------------------------------

class Msm_41_4_SpeedProfiles:
    """Управление профилями скоростей для сетевого анализа."""

    def __init__(self) -> None:
        self._custom_profiles: dict[str, SpeedProfile] = {}

    # --- Получение профиля ---

    def get_profile(self, name: str) -> SpeedProfile:
        """Получить профиль по имени.

        Args:
            name: Имя профиля ('walk', 'drive', 'fire_truck' или custom)

        Returns:
            SpeedProfile

        Raises:
            ValueError: Если профиль не найден
        """
        if name in BUILTIN_PROFILES:
            return BUILTIN_PROFILES[name]
        if name in self._custom_profiles:
            return self._custom_profiles[name]
        available = list(BUILTIN_PROFILES.keys()) + list(self._custom_profiles.keys())
        raise ValueError(
            f"Msm_41_4: Профиль '{name}' не найден. "
            f"Доступны: {', '.join(available)}"
        )

    def get_all_profiles(self) -> dict[str, SpeedProfile]:
        """Все доступные профили (встроенные + пользовательские)."""
        result = dict(BUILTIN_PROFILES)
        result.update(self._custom_profiles)
        return result

    # --- Пользовательские профили ---

    def register_custom_profile(self, profile: SpeedProfile) -> None:
        """Зарегистрировать пользовательский профиль.

        Args:
            profile: SpeedProfile с уникальным именем

        Raises:
            ValueError: Если имя совпадает со встроенным профилем
        """
        if profile.name in BUILTIN_PROFILES:
            raise ValueError(
                f"Msm_41_4: Нельзя перезаписать встроенный профиль '{profile.name}'"
            )
        self._custom_profiles[profile.name] = profile
        log_info(f"Msm_41_4: Зарегистрирован профиль '{profile.name}'")

    # --- Определение скорости ---

    def get_speed_for_feature(
        self,
        profile: SpeedProfile,
        highway_type: str,
        maxspeed: Optional[str] = None,
    ) -> float:
        """Определить скорость для ребра сети.

        Приоритет:
        1. maxspeed из атрибутов OSM (если числовое и > 0)
        2. highway_type -> profile.speeds
        3. profile.default_speed

        Args:
            profile: Активный SpeedProfile
            highway_type: Значение OSM highway (например 'primary')
            maxspeed: Значение OSM maxspeed (опционально)

        Returns:
            Скорость в км/ч (0 = запрет проезда)
        """
        # 1. Приоритет: maxspeed из OSM
        if maxspeed is not None:
            maxspeed_str = str(maxspeed).strip()
            if maxspeed_str.isdigit():
                parsed = int(maxspeed_str)
                if parsed > 0:
                    return float(parsed)

        # 2. Маппинг по типу дороги
        highway_clean = str(highway_type).strip().lower() if highway_type else ''
        speed = profile.speeds.get(highway_clean)
        if speed is not None:
            return speed

        # 3. Дефолт профиля
        return profile.default_speed

    def is_edge_forbidden(self, speed: float) -> bool:
        """Проверка: ребро запрещено для данного профиля (speed=0)."""
        return speed <= 0

    # --- Пресеты ---

    def get_preset(self, preset_name: str) -> dict:
        """Получить нормативный пресет.

        Args:
            preset_name: Имя пресета из REGULATORY_PRESETS

        Returns:
            dict с ключами: profile, unit, intervals, description

        Raises:
            ValueError: Если пресет не найден
        """
        if preset_name not in REGULATORY_PRESETS:
            available = ', '.join(REGULATORY_PRESETS.keys())
            raise ValueError(
                f"Msm_41_4: Пресет '{preset_name}' не найден. Доступны: {available}"
            )
        return dict(REGULATORY_PRESETS[preset_name])

    def get_all_presets(self) -> dict[str, dict]:
        """Все нормативные пресеты."""
        return dict(REGULATORY_PRESETS)

    # --- Утилиты ---

    @staticmethod
    def is_walk_profile(profile: SpeedProfile) -> bool:
        """Проверка: пешеходный профиль (oneway игнорируется)."""
        return profile.name == 'walk'
