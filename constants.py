# -*- coding: utf-8 -*-
"""
Константы плагина Daman_QGIS.
Централизованное хранение всех hardcoded значений.

КРИТЕРИЙ ВКЛЮЧЕНИЯ: Константа используется в >=1 файлах
ПРОВЕРЕНО: Аудит 2025-01-05

Разделы:
- ОСНОВНЫЕ КОНСТАНТЫ ПЛАГИНА (PLUGIN_*, MESSAGE_*)
- КОНСТАНТЫ ГЕОДЕЗИИ (ELLIPSOID_*, TOWGS84_*, RMSE_*)
- КОНСТАНТЫ КООРДИНАТ И ГЕОМЕТРИИ (COORDINATE_*, BUFFER_*)
- КОНСТАНТЫ ПРОЕКТА (PROJECT_*, GPKG_*)
- КОНСТАНТЫ СЛОЕВ (LAYER_*, DEFAULT_LAYER_ORDER)
- КОНСТАНТЫ АТРИБУТОВ (MAX_FIELD_LEN, USE_FIELD_ALIASES)
- КОНСТАНТЫ СТИЛЕЙ (ANSI_*, DXF_*)
- КОНСТАНТЫ ПРОВАЙДЕРОВ (PROVIDER_*, DRIVER_*)
- КОНСТАНТЫ WMS (LAYER_GOOGLE_*, NSPD_*, WMS_*, GEOMETRY)
- КОНСТАНТЫ ИМПОРТА ЕГРН (ROOT_TAG_TO_RECORD_MAP)
- КОНСТАНТЫ СЕТЕВЫХ ЗАПРОСОВ (DEFAULT_REQUEST_TIMEOUT, DEFAULT_MAX_*)
- КОНСТАНТЫ API (API_*, CACHE_*, ACCESS_TOKEN_*)
"""

import os
from configparser import ConfigParser

# ============================================================================
# ОСНОВНЫЕ КОНСТАНТЫ ПЛАГИНА
# ============================================================================

# Профилирование initGui: включить для отладки времени загрузки плагина
TIMING_ENABLED = False

# Имя плагина для логирования и сообщений
# Используется: 50 файлов, ~65 использований
PLUGIN_NAME = 'Daman_QGIS'

# Путь к корневой папке плагина (надёжный способ определения)
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

# Версия плагина (автоматически загружается из metadata.txt)
def _get_plugin_version():
    """Получить версию плагина из metadata.txt"""
    try:
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        metadata_path = os.path.join(plugin_dir, 'metadata.txt')

        if os.path.exists(metadata_path):
            config = ConfigParser()
            config.read(metadata_path, encoding='utf-8')
            return config.get('general', 'version', fallback='0.0.0')
    except Exception:
        pass

    return '0.0.0'

PLUGIN_VERSION = _get_plugin_version()

# ============================================================================
# КОНСТАНТЫ СООБЩЕНИЙ
# ============================================================================

# Длительность отображения сообщений в секундах
# MESSAGE_SUCCESS_DURATION: 15 файлов, ~28 использований
# MESSAGE_INFO_DURATION: 14 файлов, ~32 использования
# MESSAGE_WARNING_DURATION: 6 файлов, ~9 использований
# MESSAGE_SHORT_DURATION: 1 файл, ~1 использование
MESSAGE_SHORT_DURATION = 2      # Короткие уведомления
MESSAGE_SUCCESS_DURATION = 3    # Успешные операции
MESSAGE_INFO_DURATION = 5       # Информационные сообщения
MESSAGE_WARNING_DURATION = 7    # Предупреждения

# ============================================================================
# КОНСТАНТЫ ГЕОДЕЗИИ (ГОСТ 32453-2017)
# ============================================================================

# ----------------------------------------------------------------------------
# Эллипсоид Красовского (СК-42, СК-95, МСК) - ГОСТ 32453-2017, Таблица 1
# ----------------------------------------------------------------------------
ELLIPSOID_KRASS_A = 6378245.0  # Большая полуось (м)
ELLIPSOID_KRASS_F = 1 / 298.3  # Сжатие

# ----------------------------------------------------------------------------
# Эллипсоид ГСК-2011 (ОЗЭ) - ГОСТ 32453-2017, Таблица 1
# ----------------------------------------------------------------------------
ELLIPSOID_GSK2011_A = 6378136.5           # Большая полуось (м)
ELLIPSOID_GSK2011_F = 1 / 298.2564151     # Сжатие (ГОСТ 32453-2017)

# ----------------------------------------------------------------------------
# Эллипсоид ПЗ-90 (ПЗ-90.02, ПЗ-90.11) - ГОСТ 32453-2017, Таблица 1
# ----------------------------------------------------------------------------
ELLIPSOID_PZ90_A = 6378136.0              # Большая полуось (м)
ELLIPSOID_PZ90_F = 1 / 298.257839303      # Сжатие

# ----------------------------------------------------------------------------
# Эллипсоид WGS-84 (глобальная система)
# ----------------------------------------------------------------------------
ELLIPSOID_WGS84_A = 6378137.0             # Большая полуось (м)
ELLIPSOID_WGS84_F = 1 / 298.257223563     # Сжатие

# ----------------------------------------------------------------------------
# PROJ параметры эллипсоидов
# ----------------------------------------------------------------------------
ELLPS_KRASS = '+ellps=krass'     # Красовского (СК-42, МСК)

# ----------------------------------------------------------------------------
# Параметры преобразования towgs84 для PROJ
#
# КРИТИЧЕСКИ ВАЖНО - ДВЕ КОНВЕНЦИИ ЗНАКОВ:
# 1. Coordinate Frame (EPSG:9607) - ГОСТ 32453-2017, MapInfo
# 2. Position Vector (EPSG:9606) - PROJ +towgs84
#
# Разница: знаки углов поворота (rX, rY, rZ) ИНВЕРТИРОВАНЫ!
# ГОСТ дает: ωY=-0.35, ωZ=-0.79 (Coordinate Frame)
# PROJ нужно: rY=+0.35, rZ=+0.79 (Position Vector)
#
# Формат: towgs84 = dX, dY, dZ, rX, rY, rZ, dS
#   dX, dY, dZ - сдвиги центра эллипсоида (м)
#   rX, rY, rZ - углы поворота (угловые секунды) - POSITION VECTOR!
#   dS - масштабный коэффициент (ppm)
#
# Источники:
#   - ГОСТ 32453-2017, Таблица Б.1 (Coordinate Frame)
#   - https://mapinfo.ru/articles/gost
#   - https://github.com/OSGeo/PROJ/issues/1091 (конвенции знаков)
# ----------------------------------------------------------------------------

# СК-42 -> WGS-84 (Position Vector для PROJ)
# ГОСТ: ωY=-0.35, ωZ=-0.79 -> PROJ: rY=+0.35, rZ=+0.79
TOWGS84_SK42 = '23.57,-140.95,-79.8,0,0.35,0.79,-0.22'
TOWGS84_SK42_PROJ = f'+towgs84={TOWGS84_SK42}'

# СК-95 -> WGS-84 (Position Vector для PROJ)
# ГОСТ: ωZ=-0.13 -> PROJ: rZ=+0.13
TOWGS84_SK95 = '24.47,-130.89,-81.56,0,0,0.13,-0.22'
TOWGS84_SK95_PROJ = f'+towgs84={TOWGS84_SK95}'

# ГСК-2011 -> WGS-84 (Position Vector для PROJ)
# ГОСТ: ωX=0.001738, ωY=-0.003559, ωZ=0.004263
# PROJ: rX=-0.001738, rY=+0.003559, rZ=-0.004263
TOWGS84_GSK2011 = '0.013,-0.092,-0.03,-0.001738,0.003559,-0.004263,0.0074'
TOWGS84_GSK2011_PROJ = f'+towgs84={TOWGS84_GSK2011}'

# ПЗ-90.11 -> WGS-84 (Position Vector для PROJ)
# ГОСТ: ωX=0.0023, ωY=-0.00354, ωZ=0.00421
# PROJ: rX=-0.0023, rY=+0.00354, rZ=-0.00421
TOWGS84_PZ9011 = '0.013,-0.106,-0.022,-0.0023,0.00354,-0.00421,0.008'
TOWGS84_PZ9011_PROJ = f'+towgs84={TOWGS84_PZ9011}'

# ----------------------------------------------------------------------------
# Пороги RMSE для валидации CRS (F_0_5)
# ----------------------------------------------------------------------------
# RMSE_THRESHOLD_OK: точность достаточна для работы
# RMSE_THRESHOLD_WARNING: точность низкая, возможны ошибки в данных
# RMSE_THRESHOLD_WRONG_CRS: вероятно выбрана неправильная CRS/зона МСК
RMSE_THRESHOLD_OK = 1.0           # < 1 м - отличный результат
RMSE_THRESHOLD_WARNING = 10.0     # < 10 м - приемлемо, но стоит проверить
RMSE_THRESHOLD_WRONG_CRS = 1000.0 # > 1 км - скорее всего неправильная CRS

# ============================================================================
# КОНСТАНТЫ КООРДИНАТ И ГЕОМЕТРИИ
# ============================================================================

# Точность координат (в метрах)
# Используется: 8 файлов, ~23 использования
COORDINATE_PRECISION = 0.01  # 1 сантиметр

# Количество знаков после запятой для координат
# Используется: 1 файл (core/coordinate_precision.py), ~4 использования
PRECISION_DECIMALS = 2  # 2 знака = 0.01 м

# Количество знаков после запятой для WGS84 (градусы)
# Используется: Fsm_6_3_1_coordinate_list.py, Fsm_6_3_7_gpmt_documents.py
PRECISION_DECIMALS_WGS84 = 8  # 8 знаков для градусов (~0.001 м на экваторе)

# Допуск для сравнения координат (учет погрешности float)
# Используется: 1 файл (core/coordinate_precision.py), ~2 использования
COORDINATE_TOLERANCE = 0.00001  # 0.01 мм

# Допуск замыкания линий (в метрах)
# Используется: 2 файла, ~3 использования
CLOSURE_TOLERANCE = 0.01  # 1 сантиметр

# Минимальная площадь полигона (в кв.м)
# Используется: 2 файла, ~3 использования
MIN_POLYGON_AREA = 0.0001  # 1 кв.см (0.01м × 0.01м)

# Буферные расстояния для геометрических операций
BOUNDARY_INNER_BUFFER_M = -0.02  # -2 см внутренний буфер границ
BUFFER_SEGMENTS = 5               # Количество сегментов для buffer()

# Порог для сравнения RMS/ошибок (в метрах)
RMS_ERROR_THRESHOLD = 0.001  # 1 мм - порог для RMS ошибок

# ============================================================================
# КОНСТАНТЫ ПРОЕКТА
# ============================================================================

# Имя файла GeoPackage
# Используется: M_19_project_structure_manager, тесты
PROJECT_GPKG_NAME = "project.gpkg"

# Имя таблицы метаданных в GeoPackage
# Используется: 1 файл (database/project_db.py), ~11 использований
PROJECT_METADATA_TABLE = "_metadata"

# Префикс для служебных таблиц GPKG
# Используется: 1 файл (database/project_db.py), ~1 использование
GPKG_SYSTEM_TABLE_PREFIX = "gpkg_"

# Имя служебного слоя для инициализации GeoPackage
# Используется: 1 файл (database/project_db.py), ~1 использование
GPKG_INIT_LAYER_NAME = "_metadata"

# Суффикс для файла настроек проекта
# Используется: 1 файл (database/project_db.py), ~2 использования
GPKG_SETTINGS_SUFFIX = "_settings.json"

# ============================================================================
# КОНСТАНТЫ СЛОЁВ
# ============================================================================

# Порядок отображения слоёв
# Используется: 3 файла, ~6 использований
DEFAULT_LAYER_ORDER = 999  # Порядок для слоёв без явного определения

# Имена слоёв для выборки ЗУ и ОКС (Fsm_1_2_13)
# Используется: Fsm_1_2_13_1_land_selection.py
LAYER_BOUNDARIES_EXACT = "L_1_1_1_Границы_работ"
LAYER_BOUNDARIES_10M = "L_1_1_2_Границы_работ_10_м"
LAYER_BOUNDARIES_500M = "L_1_1_3_Границы_работ_500_м"
LAYER_BOUNDARIES_MINUS2CM = "L_1_1_4_Границы_работ_-2_см"

# Слой маски для M_31_MaskManager
# Используется: M_31_mask_manager.py
LAYER_MASK = "L_0_0_0_Mask"
LAYER_WFS_ZU = "L_1_2_1_WFS_ЗУ"
LAYER_WFS_KK = "L_1_2_2_WFS_КК"  # WFS кадастровые кварталы
LAYER_WFS_OKS = "L_1_2_4_WFS_ОКС"
LAYER_WFS_NP = "Le_1_2_3_4_АТД_НП_poly"  # WFS полигоны населённых пунктов
# TODO: Добавить WFS слои для ТерЗоны и Вода когда будет найден API
# LAYER_WFS_TERZONY = "???"  # WFS API не найден
# LAYER_WFS_VODA = "???"     # WFS API не найден
# OSM слои дорожной сети (Le_1_4_*)
LAYER_OSM_ROADS_LINE = "Le_1_4_1_1_OSM_АД_line"  # OSM автодороги (линии)
LAYER_OSM_ROADS_POLY = "Le_1_4_1_2_OSM_АД_poly"  # OSM автодороги (полигоны)
LAYER_OSM_PEDESTRIAN_LINE = "Le_1_4_2_1_OSM_Пешеходная_сеть_line"  # OSM пешеходная сеть

LAYER_MANUAL_ZU = "L_1_3_1_ЗУ"
LAYER_SELECTION_ZU = "Le_1_9_1_1_Выборка_ЗУ"
LAYER_SELECTION_ZU_10M = "Le_1_9_1_2_Выборка_ЗУ_10_м"
LAYER_SELECTION_ZU_500M = "Le_1_9_1_3_Выборка_ЗУ_500_м"
LAYER_SELECTION_OKS = "L_1_9_2_Выборка_ОКС"
LAYER_SELECTION_KK = "L_1_9_3_Выборка_КК"

# Префиксы слоёв выписок ЕГРН (Le_1_6_*)
LAYER_VYPISKA_ZU_PREFIX = "Le_1_6_1"
LAYER_VYPISKA_OKS_PREFIX = "Le_1_6_2"
LAYER_VYPISKA_EZ_PREFIX = "Le_1_6_3"

# Префиксы слоёв нарезки и этапности
LAYER_CUTTING_PREFIX = "Le_2_1_"
LAYER_CUTTING_REK_PREFIX = "Le_2_2_"
CUTTING_PREFIXES = (LAYER_CUTTING_PREFIX, LAYER_CUTTING_REK_PREFIX)
LAYER_STAGING_PREFIX = "Le_2_7_"

# Имена слоёв для F_2_1 (Нарезка ЗПР)
# Площадные ЗПР (L_1_12_*)
LAYER_ZPR_OKS = "L_1_12_1_ЗПР_ОКС"
LAYER_ZPR_PO = "L_1_12_2_ЗПР_ПО"
LAYER_ZPR_VO = "L_1_12_3_ЗПР_ВО"

# Линейные ЗПР (L_1_13_*)
LAYER_ZPR_REK_AD = "L_1_13_1_ЗПР_РЕК_АД"
LAYER_ZPR_SETI_PO = "L_1_13_2_ЗПР_СЕТИ_ПО"
LAYER_ZPR_SETI_VO = "L_1_13_3_ЗПР_СЕТИ_ВО"
LAYER_ZPR_NE = "L_1_13_4_ЗПР_НЭ"

# Префиксы слоёв ЗПР (для startswith-проверок)
ZPR_PREFIX_STANDARD = "L_1_12_"
ZPR_PREFIX_LINEAR = "L_1_13_"
ZPR_PREFIXES = (ZPR_PREFIX_STANDARD, ZPR_PREFIX_LINEAR)

# Все слои ЗПР (единая схема атрибутов)
LAYERS_ZPR_ALL = (
    LAYER_ZPR_OKS, LAYER_ZPR_PO, LAYER_ZPR_VO,
    LAYER_ZPR_REK_AD, LAYER_ZPR_SETI_PO, LAYER_ZPR_SETI_VO, LAYER_ZPR_NE,
)

# Слои ГПМТ (L_1_14_*)
LAYER_GPMT = "L_1_14_1_ГПМТ"
LAYER_GPMT_VNES_IZM = "L_1_14_2_ГПМТ_ВНЕС_ИЗМ"
LAYER_GPMT_POINTS = "L_1_14_3_Т_ГПМТ"
LAYER_GPMT_VNES_IZM_POINTS = "L_1_14_4_Т_ГПМТ_ВНЕС_ИЗМ"

# Слои границ нарезки (overlay)
LAYER_SELECTION_NP = "Le_1_9_4_1_Выборка_АТД_НП"
LAYER_SELECTION_TERZONY = "L_1_9_6_Выборка_ТерЗоны"
LAYER_ATD_MO = "Le_1_2_3_10_АТД_МО_poly"
LAYER_EGRN_LES = "Le_1_8_1_1_ЕГРН_Лесничества"
LAYER_WFS_OOPT = "Le_1_2_5_21_WFS_ЗОУИТ_ОЗ_ООПТ"  # ООПТ для overlay нарезки
LAYER_ZOUIT_PREFIX = "Le_1_2_5_"  # Общий префикс всех ЗОУИТ слоёв
LAYER_SELECTION_ZOUIT = "Le_1_9_5_1_ЕГРН_ЗОУИТ_Перечень"
LAYER_SELECTION_VODA = "L_1_9_7_Выборка_Вода"
LAYER_SELECTION_MO = "Le_1_9_4_2_Выборка_АТД_МО"

# Выходные слои нарезки - Раздел (внутри ЗУ)
LAYER_CUTTING_OKS_RAZDEL = "Le_2_1_1_1_Раздел_ЗПР_ОКС"
LAYER_CUTTING_PO_RAZDEL = "Le_2_1_2_1_Раздел_ЗПР_ПО"
LAYER_CUTTING_VO_RAZDEL = "Le_2_1_3_1_Раздел_ЗПР_ВО"

# Выходные слои нарезки - НГС (вне ЗУ)
LAYER_CUTTING_OKS_NGS = "Le_2_1_1_2_НГС_ЗПР_ОКС"
LAYER_CUTTING_PO_NGS = "Le_2_1_2_2_НГС_ЗПР_ПО"
LAYER_CUTTING_VO_NGS = "Le_2_1_3_2_НГС_ЗПР_ВО"

# Выходные слои нарезки - Без_Меж (заглушка)
LAYER_CUTTING_OKS_BEZ_MEZH = "Le_2_1_1_3_Без_Меж_ЗПР_ОКС"
LAYER_CUTTING_PO_BEZ_MEZH = "Le_2_1_2_3_Без_Меж_ЗПР_ПО"
LAYER_CUTTING_VO_BEZ_MEZH = "Le_2_1_3_3_Без_Меж_ЗПР_ВО"

# Выходные слои нарезки - ПС (заглушка)
LAYER_CUTTING_OKS_PS = "Le_2_1_1_4_ПС_ЗПР_ОКС"
LAYER_CUTTING_PO_PS = "Le_2_1_2_4_ПС_ЗПР_ПО"
LAYER_CUTTING_VO_PS = "Le_2_1_3_4_ПС_ЗПР_ВО"

# Выходные слои нарезки - Изменяемые (сохраняют границы и КН, меняют атрибуты)
LAYER_CUTTING_OKS_IZM = "Le_2_1_1_5_Изм_ЗПР_ОКС"
LAYER_CUTTING_PO_IZM = "Le_2_1_2_5_Изм_ЗПР_ПО"
LAYER_CUTTING_VO_IZM = "Le_2_1_3_5_Изм_ЗПР_ВО"

# Слой изъятия (F_2_5)
LAYER_IZYATIE_ZU = "L_2_3_1_Изъятие_ЗУ"

# Точечные слои нарезки - Раздел
LAYER_CUTTING_POINTS_OKS_RAZDEL = "Le_2_5_1_1_Т_Раздел_ЗПР_ОКС"
LAYER_CUTTING_POINTS_PO_RAZDEL = "Le_2_5_2_1_Т_Раздел_ЗПР_ПО"
LAYER_CUTTING_POINTS_VO_RAZDEL = "Le_2_5_3_1_Т_Раздел_ЗПР_ВО"

# Точечные слои нарезки - НГС
LAYER_CUTTING_POINTS_OKS_NGS = "Le_2_5_1_2_Т_НГС_ЗПР_ОКС"
LAYER_CUTTING_POINTS_PO_NGS = "Le_2_5_2_2_Т_НГС_ЗПР_ПО"
LAYER_CUTTING_POINTS_VO_NGS = "Le_2_5_3_2_Т_НГС_ЗПР_ВО"

# Точечные слои нарезки - Без_Меж
LAYER_CUTTING_POINTS_OKS_BEZ_MEZH = "Le_2_5_1_3_Т_Без_Меж_ЗПР_ОКС"
LAYER_CUTTING_POINTS_PO_BEZ_MEZH = "Le_2_5_2_3_Т_Без_Меж_ЗПР_ПО"
LAYER_CUTTING_POINTS_VO_BEZ_MEZH = "Le_2_5_3_3_Т_Без_Меж_ЗПР_ВО"

# Точечные слои нарезки - ПС
LAYER_CUTTING_POINTS_OKS_PS = "Le_2_5_1_4_Т_ПС_ЗПР_ОКС"
LAYER_CUTTING_POINTS_PO_PS = "Le_2_5_2_4_Т_ПС_ЗПР_ПО"
LAYER_CUTTING_POINTS_VO_PS = "Le_2_5_3_4_Т_ПС_ЗПР_ВО"

# Точечные слои нарезки - Изменяемые
LAYER_CUTTING_POINTS_OKS_IZM = "Le_2_5_1_5_Т_Изм_ЗПР_ОКС"
LAYER_CUTTING_POINTS_PO_IZM = "Le_2_5_2_5_Т_Изм_ЗПР_ПО"
LAYER_CUTTING_POINTS_VO_IZM = "Le_2_5_3_5_Т_Изм_ЗПР_ВО"

# ============================================================================
# СЛОИ ЭТАПНОСТИ (F_2_4) - только для ОКС (площадной объект)
# ============================================================================

# Этап 1 - Первоначальный раздел (полигоны)
LAYER_STAGING_1_RAZDEL = "Le_2_7_1_1_Раздел_1_этап"
LAYER_STAGING_1_NGS = "Le_2_7_1_2_НГС_1_этап"
LAYER_STAGING_1_BEZ_MEZH = "Le_2_7_1_3_Без_Меж_1_этап"
LAYER_STAGING_1_PS = "Le_2_7_1_4_ПС_1_этап"
LAYER_STAGING_1_IZM = "Le_2_7_1_5_Изм_1_этап"

# Этап 2 - Объединение (полигоны)
LAYER_STAGING_2_RAZDEL = "Le_2_7_2_1_Раздел_2_этап"
LAYER_STAGING_2_NGS = "Le_2_7_2_2_НГС_2_этап"
LAYER_STAGING_2_BEZ_MEZH = "Le_2_7_2_3_Без_Меж_2_этап"
LAYER_STAGING_2_PS = "Le_2_7_2_4_ПС_2_этап"
LAYER_STAGING_2_IZM = "Le_2_7_2_5_Изм_2_этап"

# Итог - финальные контуры (полигоны)
LAYER_STAGING_FINAL_RAZDEL = "Le_2_7_3_1_Раздел_Итог"
LAYER_STAGING_FINAL_NGS = "Le_2_7_3_2_НГС_Итог"
LAYER_STAGING_FINAL_BEZ_MEZH = "Le_2_7_3_3_Без_Меж_Итог"
LAYER_STAGING_FINAL_PS = "Le_2_7_3_4_ПС_Итог"
LAYER_STAGING_FINAL_IZM = "Le_2_7_3_5_Изм_Итог"

# Этап 1 - Первоначальный раздел (точки)
LAYER_STAGING_POINTS_1_RAZDEL = "Le_2_8_1_1_Т_Раздел_1_этап"
LAYER_STAGING_POINTS_1_NGS = "Le_2_8_1_2_Т_НГС_1_этап"
LAYER_STAGING_POINTS_1_BEZ_MEZH = "Le_2_8_1_3_Т_Без_Меж_1_этап"
LAYER_STAGING_POINTS_1_PS = "Le_2_8_1_4_Т_ПС_1_этап"
LAYER_STAGING_POINTS_1_IZM = "Le_2_8_1_5_Т_Изм_1_этап"

# Этап 2 - Объединение (точки)
LAYER_STAGING_POINTS_2_RAZDEL = "Le_2_8_2_1_Т_Раздел_2_этап"
LAYER_STAGING_POINTS_2_NGS = "Le_2_8_2_2_Т_НГС_2_этап"
LAYER_STAGING_POINTS_2_BEZ_MEZH = "Le_2_8_2_3_Т_Без_Меж_2_этап"
LAYER_STAGING_POINTS_2_PS = "Le_2_8_2_4_Т_ПС_2_этап"
LAYER_STAGING_POINTS_2_IZM = "Le_2_8_2_5_Т_Изм_2_этап"

# Итог - финальные контуры (точки)
LAYER_STAGING_POINTS_FINAL_RAZDEL = "Le_2_8_3_1_Т_Раздел_Итог"
LAYER_STAGING_POINTS_FINAL_NGS = "Le_2_8_3_2_Т_НГС_Итог"
LAYER_STAGING_POINTS_FINAL_BEZ_MEZH = "Le_2_8_3_3_Т_Без_Меж_Итог"
LAYER_STAGING_POINTS_FINAL_PS = "Le_2_8_3_4_Т_ПС_Итог"
LAYER_STAGING_POINTS_FINAL_IZM = "Le_2_8_3_5_Т_Изм_Итог"

# ============================================================================
# СЛОИ ГРУППЫ 3 (ЛЕС)
# ============================================================================

# Слой лесных выделов (входной, импортируется через F_1_1)
LAYER_FOREST_VYDELY = "Le_3_1_1_1_Лес_Ред_Выделы"

# Входные слои нарезки - РЕК (Le_2_2_*, без Изм)
# РЕК_АД
LAYER_CUTTING_REK_AD_RAZDEL = "Le_2_2_1_1_Раздел_ЗПР_РЕК_АД"
LAYER_CUTTING_REK_AD_NGS = "Le_2_2_1_2_НГС_ЗПР_РЕК_АД"
LAYER_CUTTING_REK_AD_BEZ_MEZH = "Le_2_2_1_3_Без_Меж_ЗПР_РЕК_АД"
LAYER_CUTTING_REK_AD_PS = "Le_2_2_1_4_ПС_ЗПР_РЕК_АД"
# СЕТИ_ПО
LAYER_CUTTING_SETI_PO_RAZDEL = "Le_2_2_2_1_Раздел_ЗПР_СЕТИ_ПО"
LAYER_CUTTING_SETI_PO_NGS = "Le_2_2_2_2_НГС_ЗПР_СЕТИ_ПО"
LAYER_CUTTING_SETI_PO_BEZ_MEZH = "Le_2_2_2_3_Без_Меж_ЗПР_СЕТИ_ПО"
LAYER_CUTTING_SETI_PO_PS = "Le_2_2_2_4_ПС_ЗПР_СЕТИ_ПО"
# СЕТИ_ВО
LAYER_CUTTING_SETI_VO_RAZDEL = "Le_2_2_3_1_Раздел_ЗПР_СЕТИ_ВО"
LAYER_CUTTING_SETI_VO_NGS = "Le_2_2_3_2_НГС_ЗПР_СЕТИ_ВО"
LAYER_CUTTING_SETI_VO_BEZ_MEZH = "Le_2_2_3_3_Без_Меж_ЗПР_СЕТИ_ВО"
LAYER_CUTTING_SETI_VO_PS = "Le_2_2_3_4_ПС_ЗПР_СЕТИ_ВО"
# НЭ
LAYER_CUTTING_NE_RAZDEL = "Le_2_2_4_1_Раздел_ЗПР_НЭ"
LAYER_CUTTING_NE_NGS = "Le_2_2_4_2_НГС_ЗПР_НЭ"
LAYER_CUTTING_NE_BEZ_MEZH = "Le_2_2_4_3_Без_Меж_ЗПР_НЭ"
LAYER_CUTTING_NE_PS = "Le_2_2_4_4_ПС_ЗПР_НЭ"

# Выходные слои лесной нарезки - стандартные ЗПР (Le_3_1_* -> Le_3_2_*)
# ОКС
LAYER_FOREST_STD_OKS_RAZDEL = "Le_3_2_1_1_Раздел_ЗПР_ОКС"
LAYER_FOREST_STD_OKS_NGS = "Le_3_2_1_2_НГС_ЗПР_ОКС"
LAYER_FOREST_STD_OKS_BEZ_MEZH = "Le_3_2_1_3_Без_меж_ЗПР_ОКС"
LAYER_FOREST_STD_OKS_PS = "Le_3_2_1_4_ПС_ЗПР_ОКС"
# ПО
LAYER_FOREST_STD_PO_RAZDEL = "Le_3_2_2_1_Раздел_ЗПР_ПО"
LAYER_FOREST_STD_PO_NGS = "Le_3_2_2_2_НГС_ЗПР_ПО"
LAYER_FOREST_STD_PO_BEZ_MEZH = "Le_3_2_2_3_Без_меж_ЗПР_ПО"
LAYER_FOREST_STD_PO_PS = "Le_3_2_2_4_ПС_ЗПР_ПО"
# ВО
LAYER_FOREST_STD_VO_RAZDEL = "Le_3_2_3_1_Раздел_ЗПР_ВО"
LAYER_FOREST_STD_VO_NGS = "Le_3_2_3_2_НГС_ЗПР_ВО"
LAYER_FOREST_STD_VO_BEZ_MEZH = "Le_3_2_3_3_Без_меж_ЗПР_ВО"
LAYER_FOREST_STD_VO_PS = "Le_3_2_3_4_ПС_ЗПР_ВО"

# Выходные слои лесной нарезки - РЕК ЗПР (Le_3_2_* -> Le_3_3_*)
# РЕК_АД
LAYER_FOREST_REK_AD_RAZDEL = "Le_3_3_1_1_Раздел_ЗПР_РЕК_АД"
LAYER_FOREST_REK_AD_NGS = "Le_3_3_1_2_НГС_ЗПР_РЕК_АД"
LAYER_FOREST_REK_AD_BEZ_MEZH = "Le_3_3_1_3_Без_меж_ЗПР_РЕК_АД"
LAYER_FOREST_REK_AD_PS = "Le_3_3_1_4_ПС_ЗПР_РЕК_АД"
# СЕТИ_ПО
LAYER_FOREST_SETI_PO_RAZDEL = "Le_3_3_2_1_Раздел_ЗПР_СЕТИ_ПО"
LAYER_FOREST_SETI_PO_NGS = "Le_3_3_2_2_НГС_ЗПР_СЕТИ_ПО"
LAYER_FOREST_SETI_PO_BEZ_MEZH = "Le_3_3_2_3_Без_меж_ЗПР_СЕТИ_ПО"
LAYER_FOREST_SETI_PO_PS = "Le_3_3_2_4_ПС_ЗПР_СЕТИ_ПО"
# СЕТИ_ВО
LAYER_FOREST_SETI_VO_RAZDEL = "Le_3_3_3_1_Раздел_ЗПР_СЕТИ_ВО"
LAYER_FOREST_SETI_VO_NGS = "Le_3_3_3_2_НГС_ЗПР_СЕТИ_ВО"
LAYER_FOREST_SETI_VO_BEZ_MEZH = "Le_3_3_3_3_Без_меж_ЗПР_СЕТИ_ВО"
LAYER_FOREST_SETI_VO_PS = "Le_3_3_3_4_ПС_ЗПР_СЕТИ_ВО"
# НЭ
LAYER_FOREST_NE_RAZDEL = "Le_3_3_4_1_Раздел_ЗПР_НЭ"
LAYER_FOREST_NE_NGS = "Le_3_3_4_2_НГС_ЗПР_НЭ"
LAYER_FOREST_NE_BEZ_MEZH = "Le_3_3_4_3_Без_меж_ЗПР_НЭ"
LAYER_FOREST_NE_PS = "Le_3_3_4_4_ПС_ЗПР_НЭ"

# ============================================================================
# КОНСТАНТЫ АТРИБУТОВ
# ============================================================================

# Максимальная длина текстовых полей (GeoPackage/SQLite)
# SQLite не ограничивает TEXT - это метаданные для QGIS UI
# При экспорте в Shapefile/DXF (лимит 254-256) данные обрезаются автоматически
MAX_FIELD_LEN = 65535

# ============================================================================
# КОНСТАНТЫ ОБРАБОТКИ ДАННЫХ
# ============================================================================

# Использование QGIS Field Aliases (алиасы полей)
# Используется: 1 файл (tools/F_1_data/submodules/Fsm_1_1_4_vypiska_importer/Fsm_1_1_4_4_layer_creator.py)
USE_FIELD_ALIASES = False  # Установка алиасов из full_name (Base_field_mapping_EGRN.json)

# ============================================================================
# КОНСТАНТЫ ВИД_РАБОТ (Приказ Росреестра от 24.05.2021 N П/0217)
# ============================================================================

# Виды кадастровых работ для слоёв нарезки
# Используется: F_2_1 (нарезка, включая автоматическое определение Изменяемых), F_3_2 (Без_Меж)
WORK_TYPE_BEZ_MEZH = "Существующий (сохраняемый) земельный участок"

# Детализация причин ИЗМ (атрибутивные изменения без изменения геометрии)
WORK_TYPE_IZM_VRI = "Изменение вида разрешенного использования"
WORK_TYPE_IZM_KAT = "Изменение категории"
WORK_TYPE_IZM_KAT_VRI = "Изменение категории и вида разрешенного использования"
WORK_TYPE_IZM_REESTR = "Исправление реестровой ошибки"
# Fallback (если причина не определена)
WORK_TYPE_IZM = "Изменение характеристик земельного участка"


def compose_work_type_izm(
    vri_changed: bool = False,
    category_changed: bool = False,
    area_mismatch: bool = False
) -> str:
    """Составить значение Вид_Работ для ИЗМ из флагов причин.

    Формат: "Причина1. Причина2." - каждая причина заканчивается точкой.
    Реестровая ошибка (площадь) - модификатор, добавляется после основной причины.
    """
    parts = []
    if category_changed and vri_changed:
        parts.append(WORK_TYPE_IZM_KAT_VRI)
    elif category_changed:
        parts.append(WORK_TYPE_IZM_KAT)
    elif vri_changed:
        parts.append(WORK_TYPE_IZM_VRI)

    if area_mismatch:
        parts.append(WORK_TYPE_IZM_REESTR)

    if not parts:
        return WORK_TYPE_IZM  # fallback

    return ". ".join(parts) + "."

# ============================================================================
# КОНСТАНТЫ СТИЛЕЙ
# ============================================================================

# ANSI штриховки - базовое расстояние между линиями (в мм)
# Используется: 1 файл (core/styles/converters/autocad_to_qgis.py), ~7 использований
ANSI_HATCH_SPACING = 5.0

# ============================================================================
# КОНСТАНТЫ DXF ЭКСПОРТА
# ============================================================================

# Высота текста атрибутов блока в зависимости от масштаба чертежа
# Источник: Project_Metadata.json (2_10_1_DXF_SCALE_TO_TEXT_HEIGHT)
# Используется: Fsm_dxf_1_block_exporter.py (fallback если метаданные недоступны)
# Масштаб -> Высота текста в единицах чертежа (метрах для МСК)
# Формула: scale * 3 / 1000 (fallback для нестандартных масштабов)
DXF_BLOCK_ATTR_TEXT_HEIGHT = {
    500: 1.5,    # 1:500 -> 1.5м
    1000: 3.0,   # 1:1000 -> 3м
    2000: 6.0,   # 1:2000 -> 6м
}

# Цвет BYLAYER для DXF (наследование цвета от слоя)
# Используется: Fsm_dxf_4_hatch_manager.py
DXF_COLOR_BYLAYER = 256

# ============================================================================
# КОНСТАНТЫ ЭКСПОРТА PDF
# ============================================================================

# Разрешение PDF экспорта согласно требованиям Росреестра
# Основание: Приказ Росреестра от 19.04.2022 N П/0148
# (с изменениями от 22.10.2024 N П/0326/24)
# Требование: PDF должен иметь разрешение не менее 300 dpi
# Используется: M_34_layout_manager, F_1_4, Fsm_1_4_5, Fsm_1_4_10
EXPORT_DPI_ROSREESTR = 300

# ============================================================================
# КОНСТАНТЫ ПРОВАЙДЕРОВ И ДРАЙВЕРОВ
# ============================================================================

# QGIS провайдеры
# PROVIDER_OGR: 2 файла, ~9 использований
# PROVIDER_WMS: 1 файл (F_1_2_load_web.py), ~3 использования
PROVIDER_OGR = "ogr"
PROVIDER_WMS = "wms"

# Драйверы для экспорта
# DRIVER_GPKG: 2 файла, ~7 использований
DRIVER_GPKG = "GPKG"

# ============================================================================
# КОНСТАНТЫ WMS СЛОЁВ
# ============================================================================

# Google Satellite
# Используется: 1 файл (F_1_2_load_web.py)
LAYER_GOOGLE_SATELLITE = "L_1_3_1_Google_Satellite"
WMS_GOOGLE_SATELLITE = 'type=xyz&url=https://mt1.google.com/vt/lyrs%3Ds%26x%3D%7Bx%7D%26y%3D%7By%7D%26z%3D%7Bz%7D&zmax=22&zmin=0'

# NSPD (Национальная система пространственных данных)
# Используется: 1 файл (F_1_2_load_web.py)
LAYER_NSPD_BASE = "L_1_3_2_Справочный_слой"
NSPD_TILE_URL = 'https://nspd.gov.ru/api/aeggis/v2/235/wmts/%7Bz%7D/%7Bx%7D/%7By%7D.png'
NSPD_SEARCH_URL = 'https://nspd.gov.ru/api/geoportal/v2/search/geoportal'

# НСПД авторизация (M_40)
# Используется: M_40_nspd_auth_manager.py, Msm_40_1_auth_browser_dialog.py
NSPD_AUTH_URL = 'https://nspd.gov.ru'
NSPD_AUTH_COOKIE_DOMAINS = [
    'nspd.gov.ru', '.nspd.gov.ru',
    'esia.gosuslugi.ru', '.gosuslugi.ru'
]

# НСПД WMTS Network (preprocessor для обхода WAF блокировки QGIS User-Agent)
# НСПД блокирует User-Agent содержащий "QGIS" через WAF.
# QgsNetworkAccessManager принудительно перезаписывает UA - обход через setRequestPreprocessor.
# Используется: main_plugin.py (_register_nspd_preprocessor)
NSPD_BROWSER_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/131.0.0.0 Safari/537.36'
)
NSPD_WMTS_REFERER = 'https://nspd.gov.ru/map'

# QGIS Network Access Manager — конфигурация дискового кэша тайлов
# Используется: main_plugin.py (_setup_nam_cache)
#
# ПРОБЛЕМА: QGIS 3.40 не прокидывает cache/size-bytes из QgsSettings в
# QNetworkDiskCache.setMaximumCacheSize() при инициализации NAM. В результате
# render-треды (которые грузят XYZ/WMS тайлы) остаются с Qt-дефолтом 50 МБ
# и при достижении лимита активно эвиктят старые тайлы → повторные запросы
# к nspd.gov.ru → лавина retry-логов и медленная загрузка.
#
# РЕШЕНИЕ: при старте плагина
#   (1) записываем cache/size-bytes и cache/directory в QgsSettings — будут
#       прочитаны NAM render-тредов после рестарта QGIS.
#   (2) применяем runtime на main-thread NAM — действует немедленно.
NAM_CACHE_MAX_BYTES = 1_073_741_824  # 1 ГБ — для basemap НСПД (L_1_3_2 + L_1_3_3)
NAM_CACHE_SUBDIR = 'network_tiles'   # относительно <profile>/cache/

# Expiration (TTL) кэша WMTS-тайлов — QgsSettings ключ 'qgis/defaultTileExpiry' (часы).
# По умолчанию QGIS = 24 часа. НСПД отдаёт Cache-Control: max-age=604706 (~7 дней).
# Клиентский лимит 720 часов (30 дней) позволяет серверу самому урезать через Cache-Control.
# Источник рекомендации: neteler.org/blog/gaining-wms-speed-enabling-qgis-cache-directory/
WMTS_DEFAULT_TILE_EXPIRY_HOURS = 720

# zmin для НСПД XYZ слоёв — обрезка холостых запросов на малых зумах.
# На z<zmin QGIS вообще не выпускает запросы → исчезает burst 404 при случайном отзуме.
# Используется: Fsm_1_2_6_raster_loader.py (add_nspd_base_layer / add_cos_layer)
#   L_1_3_2 «Справочный»: кадастровые слои осмысленны от z=10 (масштаб улицы и крупнее)
#   L_1_3_3 «ЦОС»:       общегеографический фон осмыслен от z=6 (район/город)
NSPD_L_1_3_2_ZMIN = 10
NSPD_L_1_3_3_ZMIN = 6

# Фильтр WMS retry-логов — блокирует перехват фокуса таба MessageLog
# Используется: main_plugin.py (_setup_wms_retry_filter)
#
# ПРОБЛЕМА: QGIS ядро логирует retry XYZ тайлов как Qgis.Info в тэг 'WMS'
# с форматом "повтор запроса {N} тайлов {M} (попытка {K})".
# QgsMessageLogViewer на каждое сообщение перескакивает currentIndex() таба
# на тэг сообщения, пользователь теряет контекст активного таба.
#
# РЕШЕНИЕ: ловим messageReceived, и через QTimer.singleShot(0) возвращаем
# индекс таба на пользовательский. Счётчик пишется в свой тэг раз в N секунд.
# Паттерны всех WMS-сообщений ядра QGIS, которые триггерят перехват таба MessageLog:
#   Info:    "повтор запроса N тайлов M (попытка K)"
#   Warning: "Превышено максимальное число запросов тайлов. ... завершилось ошибкой"
#   + английские эквиваленты для локализаций QGIS.
# Compile с re.IGNORECASE в месте использования.
WMS_RETRY_LOG_PATTERN = (
    r'\bпопытка\b'
    r'|\bretry\b'
    r'|Превышено\s+максимальное\s+число\s+запросов'
    r'|Max\s+tile\s+requests?\s+reached'
    r'|завершил\w*\s+ошибк'
)
WMS_RETRY_AGGREGATE_INTERVAL_MS = 5000             # интервал агрегированного лога

# Edge CDP авторизация (Msm_40_3)
# Используется: Msm_40_3_edge_auth.py
EDGE_CDP_STARTUP_TIMEOUT = 10  # секунд ожидания CDP endpoint после запуска Edge

# ============================================================================
# КОНСТАНТЫ ИМПОРТА ВЫПИСОК ЕГРН
# ============================================================================

# Маппинг корневых тегов XML выписок на типы записей
# Используется: Fsm_1_1_4_vypiska_importer, Fsm_1_1_xml_detector
# Поддерживает как extract_about_property_*, так и extract_base_params_*
ROOT_TAG_TO_RECORD_MAP = {
    # Земельные участки
    'extract_about_property_land': 'land_record',
    'extract_base_params_land': 'land_record',
    # ОКС (здания)
    'extract_about_property_build': 'build_record',
    'extract_base_params_build': 'build_record',
    # Сооружения
    'extract_about_property_construction': 'construction_record',
    'extract_base_params_construction': 'construction_record',
    # ОНС (объекты незавершенного строительства)
    'extract_about_property_under_construction': 'object_under_construction_record',
    'extract_base_params_under_construction': 'object_under_construction_record',
    # Машиноместа
    'extract_about_property_car_parking_space': 'car_parking_space_record',
    'extract_base_params_car_parking_space': 'car_parking_space_record',
    # Помещения
    'extract_about_property_room': 'premises_record',
    'extract_base_params_room': 'premises_record',
    # Имущественные комплексы (предприятия как имущественный комплекс)
    'extract_about_property_property_complex': 'enterprise_as_property_complex_record',
    'extract_base_params_property_complex': 'enterprise_as_property_complex_record',
    # ЕНОК (единый недвижимый комплекс)
    'extract_about_property_unified_real_estate_complex': 'unified_real_estate_complex_record',
    'extract_base_params_unified_real_estate_complex': 'unified_real_estate_complex_record',
    # Зоны и территории (не используется в детекторе, только для совместимости)
    'extract_about_zone': 'zones_and_territories_record'
}

# ============================================================================
# КОНСТАНТЫ СЕТЕВЫХ ЗАПРОСОВ И CONCURRENCY
# ============================================================================

# Таймауты запросов (в секундах)
DEFAULT_REQUEST_TIMEOUT = 30          # Стандартный таймаут для HTTP запросов
REQUEST_TIMEOUT_TUPLE = (10, 30)      # (connect, read) таймаут для requests
TILE_DOWNLOAD_TIMEOUT = 60            # Таймаут загрузки тайлов (ФГИС ЛК и др.)

# Параметры параллельной обработки
DEFAULT_MAX_WORKERS = 5               # ThreadPoolExecutor по умолчанию
DEFAULT_MAX_RETRIES = 3               # Количество повторных попыток при ошибках

# Задержка между повторными попытками (в секундах)
DEFAULT_RETRY_DELAY = 1.0             # Используется в request handlers

# Ограничение частоты запросов (запросов в секунду)
DEFAULT_RATE_LIMIT = 10               # Защита от 429 ошибок и блокировки IP

# Пул Overpass API серверов для динамического выбора по латентности.
# Пингуются параллельно POST запросом к /interpreter перед каждой загрузкой OSM.
# Недоступные серверы (403, timeout, блокировка РКН) автоматически исключаются.
# Kumi Systems = редирект на Private.coffee (дубликат, не включён).
# Региональные серверы (osm.ch, atownsend.org.uk, maprva.org) не включены.
OVERPASS_SERVERS = [
    {"name": "Overpass DE",    "url": "https://overpass-api.de/api/"},
    {"name": "Overpass RU",    "url": "https://overpass.openstreetmap.ru/api/"},
    {"name": "VK Maps",        "url": "https://maps.mail.ru/osm/tools/overpass/api/"},
    {"name": "Overpass FR",    "url": "https://overpass.openstreetmap.fr/api/"},
    {"name": "Private.coffee", "url": "https://overpass.private.coffee/api/"},
]
OVERPASS_PING_TIMEOUT = (2, 3)        # (connect, read) секунды для пинга серверов

# Задержки для file system операций (в секундах)
FILE_RELEASE_DELAY = 0.5              # Ожидание освобождения файла после операций
THREAD_POLL_INTERVAL = 0.01           # Интервал опроса для thread safety checks

# Параметры телеметрии (M_32)
# CRITICAL - только ошибки и crashes (рекомендуется для production)
# ERROR - ошибки + критические API failures
# SAMPLING - минимальная статистика + все ошибки (1% success events)
# ALL - все события (используется для отладки)
TELEMETRY_LEVEL = 'SAMPLING'          # Уровень телеметрии
TELEMETRY_SAMPLING_RATE = 0.01        # Процент success событий для отправки (1%)

# ============================================================================
# КОНСТАНТЫ API И ЛИЦЕНЗИРОВАНИЯ (M_29, M_30)
# ============================================================================

# URL API сервера
API_BASE_URL = "https://daman.tools/api/plugin"

# Формат URL: True = path-based (/validate), False = query-based (?action=validate)
_USE_PATH_ROUTING = "daman.tools" in API_BASE_URL or "damantools.ru" in API_BASE_URL



def get_api_url(action: str, **params: str) -> str:
    """Построить URL для Plugin API endpoint."""
    if _USE_PATH_ROUTING:
        path = action.replace("_", "-")
        url = f"{API_BASE_URL}/{path}"
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{query}"
    else:
        all_params = {"action": action, **params}
        query = "&".join(f"{k}={v}" for k, v in all_params.items())
        url = f"{API_BASE_URL}?{query}"
    return url

# Таймаут API запросов
API_TIMEOUT = DEFAULT_REQUEST_TIMEOUT  # Использует общий таймаут

# Настройки кэша
CACHE_MAX_AGE_HOURS = 24  # Максимальный возраст кэша без проверки версии

# Настройки JWT токенов
ACCESS_TOKEN_LIFETIME_MINUTES = 15  # Время жизни access token
TOKEN_REFRESH_THRESHOLD_SECONDS = 60  # Обновлять за 60 сек до истечения
TOKEN_MAX_RETRY_COUNT = 3  # Максимум попыток обновления
TOKEN_RETRY_DELAY_SECONDS = 2  # Задержка между попытками

# Heartbeat: периодическая проверка статуса лицензии
HEARTBEAT_INTERVAL_MS = 4 * 60 * 60 * 1000  # 4 часа в миллисекундах

# Формат API ключа (для отображения пользователю)
API_KEY_FORMAT = "DAMAN-XXXX-XXXX-XXXX"

# ============================================================================
# КОНСТАНТЫ ORS API (M_41, Msm_41_7)
# ============================================================================

# OpenRouteService API
ORS_API_URL = "https://api.openrouteservice.org"
ORS_TIMEOUT = 30  # секунд
ORS_SETTINGS_KEY = "daman_qgis/ors_api_key"
ORS_RATE_LIMIT_DELAY = 0.5  # секунд между запросами

# Маппинг профилей M_41 -> ORS API
ORS_PROFILE_MAP: dict[str, str] = {
    'walk': 'foot-walking',
    'drive': 'driving-car',
    'fire_truck': 'driving-car',
}

# КОНСТАНТЫ СЛОЕВ ГОЧС (L_4_X, M_41, F_7_1)
LAYER_GOCHS_GROUP = "ГОЧС"
LAYER_GOCHS_EVACUATION = "L_4_1_ГОЧС_Зоны_эвакуации"
LAYER_GOCHS_SERVICES = "L_4_2_ГОЧС_Службы"
LAYER_GOCHS_ROUTES = "L_4_3_ГОЧС_Маршруты"
LAYER_GOCHS_ACCESSIBILITY = "L_4_4_ГОЧС_Доступность"

# ============================================================================
# КОНСТАНТЫ ПРОФИЛЯ (M_37)
# ============================================================================

# Имена профилей QGIS
DEFAULT_PROFILE_NAME = "default"
DAMAN_PROFILE_NAME = "Daman_QGIS"

# API endpoints для скачивания/проверки референсного профиля
PROFILE_API_ENDPOINT = get_api_url("profile")
PROFILE_INFO_ENDPOINT = get_api_url("profile", info="1")

# Паттерны для исключения при копировании плагина между профилями
PROFILE_COPY_IGNORE = ['__pycache__', '*.pyc', '.git', '.gitignore']

# ============================================================================
# КОНСТАНТЫ АВТООБНОВЛЕНИЯ (M_42)
# ============================================================================

# URL plugins.xml (Public репозиторий, raw.githubusercontent)
# {channel} заменяется на 'stable' или 'beta'
UPDATE_PLUGINS_XML_URL = (
    "https://raw.githubusercontent.com/HappyLoony/"
    "Daman_QGIS/main/{channel}/plugins.xml"
)

# Таймаут проверки версии (секунды, UI thread при запуске)
UPDATE_VERSION_CHECK_TIMEOUT = 5

# Таймаут скачивания ZIP (секунды)
UPDATE_DOWNLOAD_TIMEOUT = 60

# Канал обновления по умолчанию
UPDATE_DEFAULT_CHANNEL = "stable"

# ============================================================================
# КОНСТАНТЫ РЕГИОНАЛЬНЫХ ЗОН CRS (МСК)
# ============================================================================

# Регионы с фиксированной зоной (в XML зона указана, в документах НЕ отображается)
# Для этих регионов поле "код зоны" заблокировано в GUI
# Источник: XML схемы Росреестра, справочники МСК
FIXED_ZONE_REGIONS: set[str] = {
    # Зона 1 в XML
    '05', '06', '07', '09', '13', '15', '19', '20', '21',
    '33', '39', '40', '48', '51', '68', '71', '77', '78',
    # Зона 2 в XML
    '18',
    # Зона 3 в XML
    '80',
    # Зона 4 в XML
    '88', '91',
    # Зона 5 в XML
    '83',
}

# Маппинг региона -> фиксированная зона (для XML/внутреннего использования)
# Эти значения НЕ отображаются в документах, но нужны для корректной работы
FIXED_ZONE_MAP: dict[str, str] = {
    # Зона 1
    '05': '1', '06': '1', '07': '1', '09': '1', '13': '1',
    '15': '1', '19': '1', '20': '1', '21': '1', '33': '1',
    '39': '1', '40': '1', '48': '1', '51': '1', '68': '1',
    '71': '1', '77': '1', '78': '1',
    # Зона 2
    '18': '2',
    # Зона 3
    '80': '3',
    # Зона 4
    '88': '4', '91': '4',
    # Зона 5
    '83': '5',
}

# Особые регионы с кастомным названием СК в документах
# Для этих регионов вместо "МСК-XX" используется специальное название
SPECIAL_REGION_NAMES: dict[str, str] = {
    '77': 'МГГТ',       # Москва - Московская городская геодезическая триангуляция
    '78': 'МСК-1964',   # Санкт-Петербург - система координат 1964 года
}

# ============================================================================
# КОНСТАНТЫ ФОРМАТОВ ЛИСТА (F_1_4 Графика)
# ============================================================================

# Форматы листов ISO 216 (размеры в мм: ширина, высота в книжной ориентации)
# Используется: Fsm_1_4_5_layout_manager.py
PAGE_SIZES = {
    "A4": (210, 297),
    "A3": (297, 420),
    "A2": (420, 594),
    "A1": (594, 841)
}

# Маппинг ориентаций листов (русское название -> английский код для шаблонов)
# Используется: Fsm_1_4_5_layout_manager.py
PAGE_ORIENTATIONS = {
    "Альбомная": "landscape",
    "Книжная": "portrait"
}

# Значения по умолчанию для формата листа
DEFAULT_PAGE_FORMAT = "A4"
DEFAULT_PAGE_ORIENTATION = "Альбомная"

# Шрифт по виду документации
DOC_TYPE_FONTS = {
    "ДПТ": "GOST 2.304",
    "Мастер-план": "Avenir Next W1G",
}

