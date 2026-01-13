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

# Имя плагина для логирования и сообщений
# Используется: 50 файлов, ~65 использований
PLUGIN_NAME = 'Daman_QGIS'

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
# Используется: 1 файл (tools/F_1_data/submodules/Fsm_1_5_2_excel_export.py)
PRECISION_DECIMALS_WGS84 = 6  # 6 знаков для градусов (~0.11 м на экваторе)

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
# Используется: 2 файла, ~7 использований (критично - имя БД проекта)
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

# Имена слоёв для F_2_1 (Выборка ЗУ и ОКС)
# Используется: F_2_1_land_selection.py
LAYER_BOUNDARIES_EXACT = "L_1_1_1_Границы_работ"
LAYER_BOUNDARIES_10M = "L_1_1_2_Границы_работ_10_м"
LAYER_BOUNDARIES_MINUS2CM = "L_1_1_4_Границы_работ_-2_см"
LAYER_WFS_ZU = "L_1_2_1_WFS_ЗУ"
LAYER_WFS_KK = "L_1_2_2_WFS_КК"  # WFS кадастровые кварталы
LAYER_WFS_OKS = "L_1_2_4_WFS_ОКС"
LAYER_WFS_NP = "Le_1_2_3_5_АТД_НП_poly"  # WFS полигоны населённых пунктов
# TODO: Добавить WFS слои для ТерЗоны и Вода когда будет найден API
# LAYER_WFS_TERZONY = "???"  # WFS API не найден
# LAYER_WFS_VODA = "???"     # WFS API не найден
LAYER_MANUAL_ZU = "L_1_3_1_ЗУ"
LAYER_SELECTION_ZU = "Le_2_1_1_1_Выборка_ЗУ"
LAYER_SELECTION_ZU_10M = "Le_2_1_1_2_Выборка_ЗУ_10_м"
LAYER_SELECTION_OKS = "L_2_1_2_Выборка_ОКС"
LAYER_SELECTION_KK = "L_2_1_3_Выборка_КК"

# Имена слоёв для F_3_1 (Нарезка ЗПР)
# Исходные слои ЗПР
LAYER_ZPR_OKS = "L_2_4_1_ЗПР_ОКС"
LAYER_ZPR_PO = "L_2_4_2_ЗПР_ПО"
LAYER_ZPR_VO = "L_2_4_3_ЗПР_ВО"

# Слои границ нарезки (overlay)
LAYER_SELECTION_NP = "L_2_1_4_Выборка_НП"
LAYER_SELECTION_TERZONY = "L_2_1_6_Выборка_ТерЗоны"
LAYER_ATD_MO = "Le_1_2_3_12_АТД_МО_poly"
LAYER_EGRN_LES = "L_2_1_5_1_ЕГРН_Лесничество"
LAYER_SELECTION_VODA = "L_2_1_8_Выборка_Вода"

# Выходные слои нарезки - Раздел (внутри ЗУ)
LAYER_CUTTING_OKS_RAZDEL = "Le_3_1_1_1_Раздел_ЗПР_ОКС"
LAYER_CUTTING_PO_RAZDEL = "Le_3_1_2_1_Раздел_ЗПР_ПО"
LAYER_CUTTING_VO_RAZDEL = "Le_3_1_3_1_Раздел_ЗПР_ВО"

# Выходные слои нарезки - НГС (вне ЗУ)
LAYER_CUTTING_OKS_NGS = "Le_3_1_1_2_НГС_ЗПР_ОКС"
LAYER_CUTTING_PO_NGS = "Le_3_1_2_2_НГС_ЗПР_ПО"
LAYER_CUTTING_VO_NGS = "Le_3_1_3_2_НГС_ЗПР_ВО"

# Выходные слои нарезки - Без_Меж (заглушка)
LAYER_CUTTING_OKS_BEZ_MEZH = "Le_3_1_1_3_Без_Меж_ЗПР_ОКС"
LAYER_CUTTING_PO_BEZ_MEZH = "Le_3_1_2_3_Без_Меж_ЗПР_ПО"
LAYER_CUTTING_VO_BEZ_MEZH = "Le_3_1_3_3_Без_Меж_ЗПР_ВО"

# Выходные слои нарезки - ПС (заглушка)
LAYER_CUTTING_OKS_PS = "Le_3_1_1_4_ПС_ЗПР_ОКС"
LAYER_CUTTING_PO_PS = "Le_3_1_2_4_ПС_ЗПР_ПО"
LAYER_CUTTING_VO_PS = "Le_3_1_3_4_ПС_ЗПР_ВО"

# Слой изъятия (F_3_5)
LAYER_IZYATIE_ZU = "L_3_3_1_Изъятие_ЗУ"

# Точечные слои нарезки - Раздел
LAYER_CUTTING_POINTS_OKS_RAZDEL = "Le_3_5_1_1_Т_Раздел_ЗПР_ОКС"
LAYER_CUTTING_POINTS_PO_RAZDEL = "Le_3_5_2_1_Т_Раздел_ЗПР_ПО"
LAYER_CUTTING_POINTS_VO_RAZDEL = "Le_3_5_3_1_Т_Раздел_ЗПР_ВО"

# Точечные слои нарезки - НГС
LAYER_CUTTING_POINTS_OKS_NGS = "Le_3_5_1_2_Т_НГС_ЗПР_ОКС"
LAYER_CUTTING_POINTS_PO_NGS = "Le_3_5_2_2_Т_НГС_ЗПР_ПО"
LAYER_CUTTING_POINTS_VO_NGS = "Le_3_5_3_2_Т_НГС_ЗПР_ВО"

# Точечные слои нарезки - Без_Меж
LAYER_CUTTING_POINTS_OKS_BEZ_MEZH = "Le_3_5_1_3_Т_Без_Меж_ЗПР_ОКС"
LAYER_CUTTING_POINTS_PO_BEZ_MEZH = "Le_3_5_2_3_Т_Без_Меж_ЗПР_ПО"
LAYER_CUTTING_POINTS_VO_BEZ_MEZH = "Le_3_5_3_3_Т_Без_Меж_ЗПР_ВО"

# Точечные слои нарезки - ПС
LAYER_CUTTING_POINTS_OKS_PS = "Le_3_5_1_4_Т_ПС_ЗПР_ОКС"
LAYER_CUTTING_POINTS_PO_PS = "Le_3_5_2_4_Т_ПС_ЗПР_ПО"
LAYER_CUTTING_POINTS_VO_PS = "Le_3_5_3_4_Т_ПС_ЗПР_ВО"

# ============================================================================
# СЛОИ ЭТАПНОСТИ (F_3_4) - только для ОКС (площадной объект)
# ============================================================================

# Этап 1 - Первоначальный раздел (полигоны)
LAYER_STAGING_1_RAZDEL = "Le_3_7_1_1_Раздел_1_этап"
LAYER_STAGING_1_NGS = "Le_3_7_1_2_НГС_1_этап"
LAYER_STAGING_1_BEZ_MEZH = "Le_3_7_1_3_Без_Меж_1_этап"
LAYER_STAGING_1_PS = "Le_3_7_1_4_ПС_1_этап"

# Этап 2 - Объединение (полигоны)
LAYER_STAGING_2_RAZDEL = "Le_3_7_2_1_Раздел_2_этап"
LAYER_STAGING_2_NGS = "Le_3_7_2_2_НГС_2_этап"
LAYER_STAGING_2_BEZ_MEZH = "Le_3_7_2_3_Без_Меж_2_этап"
LAYER_STAGING_2_PS = "Le_3_7_2_4_ПС_2_этап"

# Итог - финальные контуры (полигоны)
LAYER_STAGING_FINAL_RAZDEL = "Le_3_7_3_1_Раздел_Итог"
LAYER_STAGING_FINAL_NGS = "Le_3_7_3_2_НГС_Итог"
LAYER_STAGING_FINAL_BEZ_MEZH = "Le_3_7_3_3_Без_Меж_Итог"
LAYER_STAGING_FINAL_PS = "Le_3_7_3_4_ПС_Итог"

# Этап 1 - Первоначальный раздел (точки)
LAYER_STAGING_POINTS_1_RAZDEL = "Le_3_8_1_1_Т_Раздел_1_этап"
LAYER_STAGING_POINTS_1_NGS = "Le_3_8_1_2_Т_НГС_1_этап"
LAYER_STAGING_POINTS_1_BEZ_MEZH = "Le_3_8_1_3_Т_Без_Меж_1_этап"
LAYER_STAGING_POINTS_1_PS = "Le_3_8_1_4_Т_ПС_1_этап"

# Этап 2 - Объединение (точки)
LAYER_STAGING_POINTS_2_RAZDEL = "Le_3_8_2_1_Т_Раздел_2_этап"
LAYER_STAGING_POINTS_2_NGS = "Le_3_8_2_2_Т_НГС_2_этап"
LAYER_STAGING_POINTS_2_BEZ_MEZH = "Le_3_8_2_3_Т_Без_Меж_2_этап"
LAYER_STAGING_POINTS_2_PS = "Le_3_8_2_4_Т_ПС_2_этап"

# Итог - финальные контуры (точки)
LAYER_STAGING_POINTS_FINAL_RAZDEL = "Le_3_8_3_1_Т_Раздел_Итог"
LAYER_STAGING_POINTS_FINAL_NGS = "Le_3_8_3_2_Т_НГС_Итог"
LAYER_STAGING_POINTS_FINAL_BEZ_MEZH = "Le_3_8_3_3_Т_Без_Меж_Итог"
LAYER_STAGING_POINTS_FINAL_PS = "Le_3_8_3_4_Т_ПС_Итог"

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
# КОНСТАНТЫ СТИЛЕЙ
# ============================================================================

# ANSI штриховки - базовое расстояние между линиями (в мм)
# Используется: 1 файл (core/styles/converters/autocad_to_qgis.py), ~7 использований
ANSI_HATCH_SPACING = 5.0

# ============================================================================
# КОНСТАНТЫ DXF ЭКСПОРТА
# ============================================================================

# Высота текста атрибутов блока в зависимости от масштаба чертежа (мм на чертеже)
# Используется: Fsm_dxf_1_block_exporter.py
# Масштаб -> Высота текста в единицах чертежа (метрах для МСК)
# Формула: scale / 500 (fallback для нестандартных масштабов)
DXF_BLOCK_ATTR_TEXT_HEIGHT = {
    500: 1.0,    # 1:500 -> 1м = 2мм на чертеже
    1000: 2.0,   # 1:1000 -> 2м = 2мм на чертеже
    2000: 4.0,   # 1:2000 -> 4м = 2мм на чертеже
}

# Цвет BYLAYER для DXF (наследование цвета от слоя)
# Используется: Fsm_dxf_4_hatch_manager.py
DXF_COLOR_BYLAYER = 256

# ============================================================================
# КОНСТАНТЫ ПРОВАЙДЕРОВ И ДРАЙВЕРОВ
# ============================================================================

# QGIS провайдеры
# PROVIDER_OGR: 2 файла, ~9 использований
# PROVIDER_WMS: 1 файл (F_1_2_load_wms.py), ~3 использования
PROVIDER_OGR = "ogr"
PROVIDER_WMS = "wms"

# Драйверы для экспорта
# DRIVER_GPKG: 2 файла, ~7 использований
DRIVER_GPKG = "GPKG"

# ============================================================================
# КОНСТАНТЫ WMS СЛОЁВ
# ============================================================================

# Google Satellite
# Используется: 1 файл (F_1_2_load_wms.py)
LAYER_GOOGLE_SATELLITE = "L_1_3_1_Google_Satellite"
WMS_GOOGLE_SATELLITE = 'type=xyz&url=https://mt1.google.com/vt/lyrs%3Ds%26x%3D%7Bx%7D%26y%3D%7By%7D%26z%3D%7Bz%7D&zmax=22&zmin=0'

# NSPD (Национальная система пространственных данных)
# Используется: 1 файл (F_1_2_load_wms.py)
LAYER_NSPD_BASE = "L_1_3_2_Справочный_слой"
NSPD_TILE_URL = 'https://nspd.gov.ru/api/aeggis/v2/235/wmts/%7Bz%7D/%7Bx%7D/%7By%7D.png'

# Общая геометрия для типов объектов коды и абревиатуры
# Используется: Fsm_1_1_4 (импорт выписок), для разделения по типам геометрии
# Соответствует backup: Line=1, Polygon=2, NoGeometry=3
GEOMETRY = {
    'MultiPoint': ('0', 'point'),      # Точки (редко в ЕГРН выписках)
    'MultiLineString': ('1', 'line'),  # Линии (единые землепользования)
    'MultiPolygon': ('2', 'poly'),     # Полигоны (ЗУ, ОКС)
    'NoGeometry': ('3', 'not')         # Без геометрии
}

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

# ============================================================================
# КОНСТАНТЫ СПРАВОЧНЫХ ДАННЫХ (Data Reference)
# ============================================================================

# Путь к справочным данным (JSON файлы)
# ВАЖНО: Данные хранятся в ОТДЕЛЬНОМ репозитории Daman_QGIS_data_reference
# GitHub: https://github.com/HappyLoony/Daman_QGIS_data_reference
#
# Логика определения пути:
# 1. DEV режим: папка Daman_QGIS_data_reference рядом с плагином
# 2. PROD режим: data/reference/ внутри плагина (копируется при deploy)
def _get_data_reference_path():
    """Определить путь к справочным данным (DEV или PROD)"""
    plugin_dir = os.path.dirname(os.path.abspath(__file__))

    # DEV: проверяем внешний репозиторий рядом с плагином
    dev_path = os.path.join(os.path.dirname(plugin_dir), "Daman_QGIS_data_reference")
    if os.path.exists(dev_path) and os.path.isdir(dev_path):
        return dev_path

    # PROD: используем data/reference/ внутри плагина
    prod_path = os.path.join(plugin_dir, "data", "reference")
    return prod_path

DATA_REFERENCE_PATH = _get_data_reference_path()

# URL для загрузки данных через HTTP (временное решение - симуляция API)
DATA_REFERENCE_BASE_URL = "https://raw.githubusercontent.com/HappyLoony/Daman_QGIS_data_reference/main"

# Режим чтения данных: "local" | "remote" | "auto"
# local - только локальные файлы
# remote - только HTTP (GitHub Raw)
# auto - remote с fallback на local
DATA_REFERENCE_MODE = "local"  # Пока используем локальный режим

# ============================================================================
# КОНСТАНТЫ API И ЛИЦЕНЗИРОВАНИЯ (M_29, M_30)
# ============================================================================

# URL API сервера (заменить на реальный при деплое)
# Используется: M_29_LicenseManager, M_30_NetworkManager
API_BASE_URL = "https://api.daman-qgis.ru"  # TODO: Заменить на реальный
API_TIMEOUT = DEFAULT_REQUEST_TIMEOUT  # Использует общий таймаут

# Настройки кэша
CACHE_MAX_AGE_HOURS = 24  # Максимальный возраст кэша без проверки версии

# Настройки JWT токенов
ACCESS_TOKEN_LIFETIME_MINUTES = 15

# Формат API ключа (для отображения пользователю)
API_KEY_FORMAT = "DAMAN-XXXX-XXXX-XXXX"

# ============================================================================
# КОНСТАНТЫ ОБНОВЛЕНИЙ (M_31)
# ============================================================================

# URL для проверки обновлений (raw GitHub)
UPDATE_BETA_URL = "https://raw.githubusercontent.com/HappyLoony/Daman_QGIS/main/beta/plugins.xml"
UPDATE_STABLE_URL = "https://raw.githubusercontent.com/HappyLoony/Daman_QGIS/main/stable/plugins.xml"

# Страница релизов для скачивания
UPDATE_GITHUB_RELEASES_URL = "https://github.com/HappyLoony/Daman_QGIS/releases"

# Таймаут проверки обновлений (секунды)
UPDATE_CHECK_TIMEOUT = 10

# Интервал между автоматическими проверками (дни)
UPDATE_CHECK_INTERVAL_DAYS = 1