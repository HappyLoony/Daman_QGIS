# -*- coding: utf-8 -*-
"""
Импортер для файлов DXF (AutoCAD Drawing Exchange Format).
Использует ezdxf для чтения данных (включая блоки INSERT).

Преимущества ezdxf над OGR провайдером:
- Корректное чтение вложенных блоков (INSERT entities)
- Автоматическое применение трансформаций (scale, rotation, insert point)
- Поддержка всех типов полилиний (LWPOLYLINE, POLYLINE, LINE)
- Корректная работа с кодировками (cp1251 для кириллицы)
"""

import os
import re
from types import ModuleType
from typing import Optional, List, Dict, Any, Tuple
from qgis.core import (
    QgsVectorLayer, QgsMessageLog, Qgis,
    QgsCoordinateReferenceSystem, QgsWkbTypes,
    QgsGeometry, QgsFeature, QgsFields, QgsField,
    QgsProject, QgsPoint, QgsPointXY
)
from qgis.PyQt.QtCore import QMetaType
import processing

from ..core.base_importer import BaseImporter
from Daman_QGIS.database.schemas import ImportSettings
from Daman_QGIS.constants import PLUGIN_NAME, MIN_POLYGON_AREA, COORDINATE_PRECISION
from Daman_QGIS.managers.M_6_coordinate_precision import CoordinatePrecisionManager
from Daman_QGIS.utils import log_info, log_warning, log_error
from .Fsm_1_1_2_polygon_builder import PolygonBuilder

class DxfImporter(BaseImporter):
    """
    Импортер DXF файлов через ezdxf.

    Поддерживает:
    - Прямые полилинии в modelspace (LWPOLYLINE, POLYLINE, LINE)
    - Полилинии внутри блоков (INSERT entities) через virtual_entities()
    - Вложенные блоки (рекурсивное извлечение)
    - Автоматическое построение полигонов с внутренними контурами (holes)
    """

    def __init__(self, iface=None):
        """Инициализация импортера"""
        super().__init__(iface)
        self.settings: Optional[ImportSettings] = None
        self._ezdxf: Optional[ModuleType] = None

    def _ensure_ezdxf(self) -> bool:
        """
        Проверка и импорт библиотеки ezdxf

        Returns:
            True если ezdxf доступен
        """
        if self._ezdxf is not None:
            return True

        try:
            import ezdxf
            self._ezdxf = ezdxf
            return True
        except ImportError as e:
            log_error(f"Fsm_1_1_1: ezdxf не установлен: {e}")
            return False

    def _detect_dxf_encoding(self, file_path: str) -> Optional[str]:
        """
        Определение кодировки DXF файла из заголовка $CODEPAGE.

        DXF файлы созданные в русских версиях AutoCAD обычно имеют $CODEPAGE=ANSI_1251.
        ezdxf не выбрасывает исключение при неправильной кодировке - он просто читает
        файл с кракозябрами. Поэтому определяем кодировку ДО чтения файла.

        Args:
            file_path: Путь к DXF файлу

        Returns:
            Имя кодировки Python (cp1251, utf-8 и т.д.) или None для авто-определения
        """
        # Маппинг $CODEPAGE -> Python encoding
        codepage_map = {
            'ANSI_1251': 'cp1251',      # Русский (кириллица)
            'ANSI_1252': 'cp1252',      # Западноевропейский
            'ANSI_1250': 'cp1250',      # Центральноевропейский
            'ANSI_1253': 'cp1253',      # Греческий
            'ANSI_1254': 'cp1254',      # Турецкий
            'ANSI_1255': 'cp1255',      # Иврит
            'ANSI_1256': 'cp1256',      # Арабский
            'ANSI_1257': 'cp1257',      # Балтийский
            'ANSI_936': 'gbk',          # Китайский (упрощённый)
            'ANSI_950': 'big5',         # Китайский (традиционный)
            'ANSI_932': 'cp932',        # Японский
            'ANSI_949': 'cp949',        # Корейский
            'UTF-8': 'utf-8',
            'UTF8': 'utf-8',
        }

        try:
            # Читаем начало файла для поиска $CODEPAGE
            # DXF - текстовый формат, $CODEPAGE в секции HEADER
            with open(file_path, 'rb') as f:
                # Читаем первые 8KB - достаточно для заголовка
                header_bytes = f.read(8192)

            # Пробуем декодировать как ASCII для поиска $CODEPAGE
            try:
                header_text = header_bytes.decode('ascii', errors='ignore')
            except Exception:
                header_text = header_bytes.decode('latin-1', errors='ignore')

            # Ищем $CODEPAGE в заголовке
            # Формат DXF: группа 9 + "\n$CODEPAGE\n" + группа 3 + "\nЗНАЧЕНИЕ\n"
            codepage_match = re.search(r'\$CODEPAGE\s*\n\s*3\s*\n\s*(\S+)', header_text, re.IGNORECASE)

            if codepage_match:
                codepage = codepage_match.group(1).upper()
                log_info(f"Fsm_1_1_1: Обнаружена $CODEPAGE: {codepage}")

                encoding = codepage_map.get(codepage)
                if encoding:
                    return encoding
                else:
                    log_warning(f"Fsm_1_1_1: Неизвестная $CODEPAGE: {codepage}, используем cp1251")
                    return 'cp1251'
            else:
                # $CODEPAGE не найден - для русских систем предполагаем cp1251
                log_info("Fsm_1_1_1: $CODEPAGE не найден, используем cp1251 по умолчанию")
                return 'cp1251'

        except Exception as e:
            log_warning(f"Fsm_1_1_1: Ошибка определения кодировки: {e}, используем cp1251")
            return 'cp1251'

    def _is_binary_dxf(self, file_path: str) -> bool:
        """
        Определение формата DXF файла: бинарный или текстовый.

        Бинарный DXF начинается с сигнатуры "AutoCAD Binary DXF".
        Текстовый DXF начинается с "0" (группа) и "SECTION" или с комментариев.

        Args:
            file_path: Путь к DXF файлу

        Returns:
            True если файл в бинарном формате
        """
        try:
            with open(file_path, 'rb') as f:
                # Читаем первые 22 байта - длина сигнатуры "AutoCAD Binary DXF\r\n\x1a\x00"
                header = f.read(22)

            # Проверяем сигнатуру бинарного DXF
            if header.startswith(b'AutoCAD Binary DXF'):
                return True

            return False

        except Exception as e:
            log_warning(f"Fsm_1_1_1: Ошибка определения формата DXF: {e}")
            return False

    def _fix_binary_dxf_encoding(self, text: str) -> str:
        """
        Исправление кодировки текста из бинарного DXF файла.

        Проблема: ezdxf читает бинарные DXF файлы и декодирует текст как CP1252 (Latin-1),
        но русские DXF файлы содержат текст в CP1251 (кириллица).

        Решение: перекодируем строку обратно в байты (как CP1252) и затем
        декодируем правильно (как CP1251).

        Источник: https://github.com/mozman/ezdxf/issues/106
        Документация: https://ezdxf.readthedocs.io/en/stable/dxfinternals/fileencoding.html

        Args:
            text: Строка с неправильной кодировкой

        Returns:
            Исправленная строка с кириллицей
        """
        if not text:
            return text

        try:
            # Проверяем, содержит ли текст характерные кракозябры CP1252->CP1251
            # Например: 'Ï' (0xCF в CP1252) должно быть 'П' (0xCF в CP1251)
            # Если текст уже корректный ASCII/Unicode - не трогаем
            if text.isascii():
                return text

            # Пробуем перекодировать: str -> bytes(latin-1) -> str(cp1251)
            # latin-1 используется потому что это 1:1 маппинг байт->символ
            fixed_text = text.encode('latin-1', errors='replace').decode('cp1251', errors='replace')

            return fixed_text

        except (UnicodeEncodeError, UnicodeDecodeError) as e:
            log_warning(f"Fsm_1_1_1: Ошибка перекодировки текста '{text[:20]}...': {e}")
            return text

    def log_message(self, message: str, level: Qgis.MessageLevel = Qgis.Info):
        """Логирование сообщений"""
        if level == Qgis.Info:
            log_info(message)
        elif level == Qgis.Warning:
            log_warning(message)
        elif level == Qgis.Critical:
            log_error(message)
        else:
            log_info(message)

    def supports_format(self, file_extension: str) -> bool:
        """Проверка поддержки формата"""
        return file_extension.lower() in self.get_supported_formats()

    def get_supported_formats(self) -> List[str]:
        """
        Получение списка поддерживаемых форматов
        
        Returns:
            Список расширений
        """
        return ['.dxf']
    
    def can_import(self, file_path: str) -> bool:
        """
        Проверка возможности импорта файла
        
        Args:
            file_path: Путь к файлу
            
        Returns:
            True если можно импортировать
        """
        if not os.path.exists(file_path):
            return False
        
        # Проверяем расширение
        ext = os.path.splitext(file_path)[1].lower()
        return ext in self.get_supported_formats()
    
    def import_file(self, file_path: str, **custom_params) -> Dict[str, Any]:
        """
        Импорт DXF файла (переопределяет абстрактный метод базового класса)

        Args:
            file_path: Путь к DXF файлу
            **custom_params: Дополнительные параметры (может содержать 'settings', 'layer_name')

        Returns:
            Словарь с результатами импорта
        """
        # Создаем или обновляем settings с именем целевого слоя
        settings = custom_params.get('settings')
        if not settings:
            settings = ImportSettings(
                source_format='DXF',
                target_layer_name=custom_params.get('layer_name', os.path.basename(file_path))
            )
        elif custom_params.get('layer_name'):
            # Обновляем имя слоя если передано через custom_params
            settings.target_layer_name = custom_params.get('layer_name')

        main_layer = self._import_file_internal(file_path, settings)

        if main_layer:
            # Возвращаем ВСЕ созданные слои (основной + буферные)
            return {
                'success': True,
                'layers': self.created_layers if hasattr(self, 'created_layers') else [main_layer],
                'message': f'Успешно импортирован файл {os.path.basename(file_path)} ({len(self.created_layers) if hasattr(self, "created_layers") else 1} слоёв)',
                'errors': []
            }
        else:
            return {
                'success': False,
                'layers': [],
                'message': f'Не удалось импортировать файл {os.path.basename(file_path)}',
                'errors': ['Import failed']
            }
    def _import_file_internal(self,
                   file_path: str,
                   settings: Optional[ImportSettings] = None) -> Optional[QgsVectorLayer]:
        """
        Внутренний метод импорта DXF файла через ezdxf

        Алгоритм:
        1. Открываем DXF через ezdxf
        2. Извлекаем все полилинии (включая из блоков INSERT)
        3. Строим полигоны с внутренними контурами через PolygonBuilder
        4. Создаём QGIS слой и сохраняем в GPKG

        Args:
            file_path: Путь к DXF файлу
            settings: Настройки импорта

        Returns:
            Импортированный слой или None
        """
        # Проверяем ezdxf
        if not self._ensure_ezdxf():
            self.log_message("Библиотека ezdxf не установлена. Установите через F_5_1.", Qgis.Critical)
            return None

        # Инициализируем список созданных слоёв
        self.created_layers = []

        self.settings = settings or ImportSettings(
            source_format='DXF',
            target_layer_name=os.path.basename(file_path)
        )

        # Логируем начало импорта
        self.log_message(f"Начало импорта через ezdxf: {os.path.basename(file_path)}")

        # Определяем целевое имя слоя и ожидаемый тип геометрии из Base_layers.json
        target_layer_name = self.settings.target_layer_name if self.settings else os.path.splitext(os.path.basename(file_path))[0]
        expected_geom_type = self._get_expected_geometry_type(target_layer_name)

        try:
            # Открываем DXF через ezdxf
            # ВАЖНО: определяем кодировку ДО чтения файла,
            # т.к. ezdxf не выбрасывает исключение при неправильной кодировке
            assert self._ezdxf is not None

            # Определяем кодировку из заголовка DXF ($CODEPAGE)
            encoding = self._detect_dxf_encoding(file_path)
            self.log_message(f"Определена кодировка DXF: {encoding or 'auto'}")

            try:
                # Проверяем формат файла: бинарный или текстовый DXF
                is_binary = self._is_binary_dxf(file_path)

                if is_binary:
                    # Бинарный DXF - читаем напрямую через ezdxf
                    # Для бинарных файлов кодировка не применяется
                    self.log_message(f"Обнаружен бинарный DXF, читаем напрямую")
                    doc = self._ezdxf.readfile(file_path)
                else:
                    # Текстовый DXF - читаем с правильной кодировкой
                    # ВАЖНО: ezdxf игнорирует параметр encoding в readfile()
                    # Решение: читаем файл вручную с нужной кодировкой через read()
                    with open(file_path, 'rt', encoding=encoding, errors='replace') as f:
                        file_content = f.read()

                    # Парсим строку через ezdxf.read()
                    from io import StringIO
                    doc = self._ezdxf.read(StringIO(file_content))

                codepage = doc.header.get('$CODEPAGE', 'не указана')
                doc_encoding = getattr(doc, 'encoding', 'unknown')
                format_type = 'бинарный' if is_binary else 'текстовый'
                self.log_message(f"DXF открыт успешно ({format_type}), $CODEPAGE: {codepage}, "
                                f"кодировка: {encoding if not is_binary else 'N/A'}")
            except Exception as e:
                self.log_message(f"Ошибка чтения DXF: {e}", Qgis.Critical)
                return None

            if not doc:
                self.log_message("Не удалось открыть DXF файл", Qgis.Critical)
                return None

            msp = doc.modelspace()

            # Определяем тип слоя
            is_polygon_layer = expected_geom_type in ['Polygon', 'MultiPolygon', None]
            is_boundaries_layer = '1_1_1' in target_layer_name or 'граница' in target_layer_name.lower()

            if is_polygon_layer:
                if is_boundaries_layer:
                    # Границы работ: все полилинии в один список, применяем containment глобально
                    polylines = self._extract_all_polylines(msp, doc)
                    if not polylines:
                        self.log_message("В DXF файле не найдено полилиний", Qgis.Warning)
                        return None
                    self.log_message(f"Извлечено {len(polylines)} полилиний (режим границ работ)")
                    result_layer = self._build_polygon_layer(
                        polylines,
                        target_layer_name,
                        is_boundaries_layer=True
                    )
                else:
                    # ЗПР/ОКС: каждый INSERT блок = отдельный полигон
                    # Containment применяется ВНУТРИ каждого блока
                    block_groups = self._extract_polylines_grouped_by_block(msp, doc, is_binary)
                    if not block_groups:
                        self.log_message("В DXF файле не найдено полилиний в блоках", Qgis.Warning)
                        return None
                    self.log_message(f"Извлечено {len(block_groups)} групп (INSERT блоков)")
                    result_layer = self._build_polygon_layer_from_blocks(
                        block_groups,
                        target_layer_name
                    )
            else:
                # Линейный слой - плоский список
                polylines = self._extract_all_polylines(msp, doc)
                if not polylines:
                    self.log_message("В DXF файле не найдено полилиний", Qgis.Warning)
                    return None
                result_layer = self._build_line_layer(polylines, target_layer_name)

            if not result_layer:
                self.log_message("Ошибка: не удалось создать слой", Qgis.Critical)
                return None

            self.result_layer = result_layer

            # Устанавливаем CRS из проекта
            project_crs = self.get_project_crs()
            if project_crs and project_crs.isValid():
                result_layer.setCrs(project_crs)
                self.log_message(f"Установлена СК: {project_crs.authid()}")

            # Сохраняем в GPKG (если memory layer)
            if result_layer.dataProvider().name() == 'memory':
                from ..core import LayerProcessor
                processor = LayerProcessor(self.project_manager, self.layer_manager)
                saved_layer = processor.save_to_gpkg(result_layer, target_layer_name)
                if saved_layer:
                    result_layer = saved_layer
                    self.result_layer = result_layer
                    self.log_message(f"Слой '{target_layer_name}' сохранён в GPKG")

            # Добавляем слой в проект
            if result_layer.id() in QgsProject.instance().mapLayers():
                QgsProject.instance().removeMapLayer(result_layer.id())

            if self.layer_manager:
                self.layer_manager.add_layer(result_layer, make_readonly=False, auto_number=False, check_precision=False)
                self.log_message(f"Слой '{result_layer.name()}' добавлен через LayerManager")
            else:
                QgsProject.instance().addMapLayer(result_layer)
                self.log_message(f"Слой '{result_layer.name()}' добавлен в проект")

            # Добавляем основной слой в список созданных
            self.created_layers.append(result_layer)

            # Создаём буферные слои для L_1_1_1_Границы_работ
            if result_layer.name() == 'L_1_1_1_Границы_работ':
                self._create_buffer_layers(result_layer)

            return result_layer

        except Exception as e:
            self.log_message(f"Ошибка импорта DXF: {e}", Qgis.Critical)
            log_error(f"Fsm_1_1_1: Ошибка импорта DXF: {e}")
            return None

    def _extract_all_polylines(self, msp: Any, doc: Any) -> List[QgsGeometry]:
        """
        Извлечение всех полилиний из modelspace и блоков INSERT (плоский список).
        Используется для слоёв границ работ (L_1_1_1).

        Args:
            msp: Modelspace объект ezdxf
            doc: Document объект ezdxf

        Returns:
            Список QgsGeometry (LineString)
        """
        polylines = []
        processed_blocks = set()

        # 1. Прямые полилинии в modelspace
        direct_count = 0
        for entity in msp.query('LWPOLYLINE POLYLINE LINE'):
            geom = self._entity_to_geometry(entity)
            if geom and not geom.isEmpty():
                polylines.append(geom)
                direct_count += 1

        self.log_message(f"Прямых полилиний в modelspace: {direct_count}")

        # 2. Полилинии из блоков INSERT (через virtual_entities)
        block_count = 0
        for insert in msp.query('INSERT'):
            block_name = insert.dxf.name

            # Пропускаем системные блоки
            if block_name.startswith('*'):
                continue

            try:
                for virtual_entity in insert.virtual_entities():
                    entity_type = virtual_entity.dxftype()

                    if entity_type in ('LWPOLYLINE', 'POLYLINE', 'LINE'):
                        geom = self._entity_to_geometry(virtual_entity)
                        if geom and not geom.isEmpty():
                            polylines.append(geom)
                            block_count += 1

                    elif entity_type == 'INSERT':
                        nested_geoms = self._extract_from_nested_insert(
                            virtual_entity, doc, processed_blocks
                        )
                        polylines.extend(nested_geoms)
                        block_count += len(nested_geoms)

            except Exception as e:
                self.log_message(f"Ошибка при обработке блока '{block_name}': {e}", Qgis.Warning)

        self.log_message(f"Полилиний из блоков INSERT: {block_count}")

        return polylines

    def _extract_polylines_grouped_by_block(self, msp: Any, doc: Any,
                                            is_binary: bool = False) -> List[Dict[str, Any]]:
        """
        Извлечение полилиний с группировкой по INSERT блокам.
        Каждый INSERT блок = отдельная группа = отдельный полигон.
        Используется для слоёв ЗПР/ОКС где каждый блок это отдельный объект.

        ВАЖНО: Также извлекаются атрибуты блоков (ATTRIB) для сохранения в QGIS слое.
        Блок AutoCAD со своими атрибутами становится полигоном с теми же атрибутами в QGIS.

        Логика вложенности применяется ВНУТРИ каждого блока:
        - Блок 1: внешний контур + его дырки -> 1 полигон с атрибутами блока 1
        - Блок 2: внешний контур + его дырки -> 1 полигон с атрибутами блока 2
        - Даже если блоки пересекаются, они остаются отдельными объектами

        Args:
            msp: Modelspace объект ezdxf
            doc: Document объект ezdxf
            is_binary: True если файл в бинарном формате DXF (требуется перекодировка)

        Returns:
            Список групп, где каждая группа = словарь:
            {
                'polylines': List[QgsGeometry],  # Полилинии блока
                'attributes': Dict[str, str],     # Атрибуты блока (ATTRIB)
                'block_name': str,                # Имя блока
                'dxf_layer': str                  # Слой DXF
            }
        """
        groups = []
        processed_blocks = set()

        # 1. Прямые полилинии в modelspace (одна группа без атрибутов)
        direct_polylines = []
        for entity in msp.query('LWPOLYLINE POLYLINE LINE'):
            geom = self._entity_to_geometry(entity)
            if geom and not geom.isEmpty():
                direct_polylines.append(geom)

        if direct_polylines:
            groups.append({
                'polylines': direct_polylines,
                'attributes': {},  # Прямые полилинии не имеют атрибутов блоков
                'block_name': None,
                'dxf_layer': None
            })
            self.log_message(f"Прямых полилиний в modelspace: {len(direct_polylines)} (1 группа)")

        # 2. Полилинии из блоков INSERT - каждый INSERT = отдельная группа с атрибутами
        for insert in msp.query('INSERT'):
            block_name = insert.dxf.name

            # Пропускаем системные блоки
            if block_name.startswith('*'):
                continue

            try:
                block_polylines = []

                for virtual_entity in insert.virtual_entities():
                    entity_type = virtual_entity.dxftype()

                    if entity_type in ('LWPOLYLINE', 'POLYLINE', 'LINE'):
                        geom = self._entity_to_geometry(virtual_entity)
                        if geom and not geom.isEmpty():
                            block_polylines.append(geom)

                    elif entity_type == 'INSERT':
                        # Рекурсивно извлекаем из вложенных блоков
                        # НО добавляем в ТУ ЖЕ группу (вложенный блок = часть родительского)
                        nested_geoms = self._extract_from_nested_insert(
                            virtual_entity, doc, processed_blocks
                        )
                        block_polylines.extend(nested_geoms)

                # Добавляем группу если есть полилинии
                if block_polylines:
                    # Извлекаем атрибуты блока (ATTRIB entities)
                    block_attributes = {}
                    for attrib in insert.attribs:
                        tag = attrib.dxf.tag
                        text = attrib.dxf.text

                        # Исправляем кодировку для бинарных DXF:
                        # ezdxf читает бинарный DXF как CP1252, но реально данные в CP1251
                        # Перекодируем: str -> bytes(cp1252) -> str(cp1251)
                        if text and is_binary:
                            text = self._fix_binary_dxf_encoding(text)

                        block_attributes[tag] = text

                    groups.append({
                        'polylines': block_polylines,
                        'attributes': block_attributes,
                        'block_name': block_name,
                        'dxf_layer': insert.dxf.layer
                    })

            except Exception as e:
                self.log_message(f"Ошибка при обработке блока '{block_name}': {e}", Qgis.Warning)

        # Подсчитываем блоки с атрибутами
        blocks_with_attrs = sum(1 for g in groups if g['attributes'])
        self.log_message(f"Всего групп (INSERT блоков): {len(groups)}, из них с атрибутами: {blocks_with_attrs}")

        return groups

    def _extract_from_nested_insert(self, insert: Any, doc: Any,
                                    processed_blocks: set) -> List[QgsGeometry]:
        """
        Рекурсивное извлечение полилиний из вложенных блоков

        Args:
            insert: INSERT entity
            doc: Document объект ezdxf
            processed_blocks: Множество обработанных блоков (для предотвращения циклов)

        Returns:
            Список QgsGeometry
        """
        polylines = []
        block_name = insert.dxf.name

        # Предотвращаем бесконечную рекурсию
        if block_name in processed_blocks:
            return polylines

        processed_blocks.add(block_name)

        try:
            for virtual_entity in insert.virtual_entities():
                entity_type = virtual_entity.dxftype()

                if entity_type in ('LWPOLYLINE', 'POLYLINE', 'LINE'):
                    geom = self._entity_to_geometry(virtual_entity)
                    if geom and not geom.isEmpty():
                        polylines.append(geom)

                elif entity_type == 'INSERT':
                    # Рекурсия для вложенных блоков
                    nested = self._extract_from_nested_insert(
                        virtual_entity, doc, processed_blocks
                    )
                    polylines.extend(nested)

        except Exception as e:
            log_warning(f"Fsm_1_1_1: Ошибка при извлечении из блока '{block_name}': {e}")

        return polylines

    def _entity_to_geometry(self, entity: Any) -> Optional[QgsGeometry]:
        """
        Конвертация ezdxf entity в QgsGeometry

        Args:
            entity: Entity объект ezdxf (LWPOLYLINE, POLYLINE, LINE)

        Returns:
            QgsGeometry (LineString) или None
        """
        try:
            entity_type = entity.dxftype()

            if entity_type == 'LWPOLYLINE':
                # LWPOLYLINE - лёгкая полилиния
                points = []
                for x, y, *_ in entity.get_points():
                    points.append(QgsPointXY(x, y))

                if len(points) < 2:
                    return None

                # Проверяем замкнутость (флаг 1)
                is_closed = bool(entity.dxf.flags & 1)
                if is_closed and points[0] != points[-1]:
                    points.append(points[0])  # Замыкаем

                return QgsGeometry.fromPolylineXY(points)

            elif entity_type == 'POLYLINE':
                # POLYLINE - старый формат (2D/3D полилиния)
                # Используем .points() вместо .get_points() для совместимости
                # Документация: https://ezdxf.readthedocs.io/en/stable/dxfentities/polyline.html
                points = []
                for pt in entity.points():
                    # points() возвращает (x, y) или (x, y, z) tuples
                    points.append(QgsPointXY(pt[0], pt[1]))

                if len(points) < 2:
                    return None

                # Проверяем замкнутость (флаг 1)
                is_closed = entity.is_closed
                if is_closed and points[0] != points[-1]:
                    points.append(points[0])

                return QgsGeometry.fromPolylineXY(points)

            elif entity_type == 'LINE':
                # LINE - простая линия из двух точек
                start = entity.dxf.start
                end = entity.dxf.end
                return QgsGeometry.fromPolylineXY([
                    QgsPointXY(start.x, start.y),
                    QgsPointXY(end.x, end.y)
                ])

            return None

        except Exception as e:
            log_warning(f"Fsm_1_1_1: Ошибка конвертации entity: {e}")
            return None

    def _build_polygon_layer(self, polylines: List[QgsGeometry],
                             layer_name: str,
                             is_boundaries_layer: bool) -> Optional[QgsVectorLayer]:
        """
        Построение полигонального слоя из полилиний (плоский список).
        Используется для границ работ (L_1_1_1).

        Args:
            polylines: Список QgsGeometry (LineString)
            layer_name: Имя слоя
            is_boundaries_layer: True если это слой границ работ

        Returns:
            QgsVectorLayer или None
        """
        builder = PolygonBuilder()

        polygons = builder.build_polygons_with_holes(
            polylines,
            min_area=MIN_POLYGON_AREA,
            validate=True,
            remove_largest_outer=is_boundaries_layer
        )

        if not polygons:
            self.log_message("Не удалось создать полигоны из полилиний", Qgis.Warning)
            return None

        result_layer = builder.create_layer_from_polygons(
            polygons,
            layer_name,
            None,
            as_single_multipolygon=is_boundaries_layer
        )

        return result_layer

    def _build_polygon_layer_from_blocks(self,
                                         block_groups: List[Dict[str, Any]],
                                         layer_name: str) -> Optional[QgsVectorLayer]:
        """
        Построение полигонального слоя из групп полилиний (по блокам).
        Каждая группа (INSERT блок) обрабатывается независимо.
        Атрибуты блоков сохраняются в слое QGIS.

        Логика:
        1. Для каждого блока применяем containment (дырки) ВНУТРИ блока
        2. Каждый блок = 1 полигон (с возможными внутренними контурами)
        3. Полигоны разных блоков НЕ влияют друг на друга
        4. Атрибуты блока (ATTRIB) становятся атрибутами полигона

        Args:
            block_groups: Список групп (каждая группа = dict с 'polylines' и 'attributes')
            layer_name: Имя слоя

        Returns:
            QgsVectorLayer или None
        """
        # Собираем данные: геометрии + атрибуты для каждого полигона
        polygons_with_attrs = []  # List[Tuple[QgsGeometry, Dict[str, str]]]
        total_holes = 0

        builder = PolygonBuilder()

        for group in block_groups:
            group_polylines = group.get('polylines', [])
            group_attributes = group.get('attributes', {})

            if not group_polylines:
                continue

            # Обрабатываем каждую группу (блок) независимо
            # Внутри блока применяется логика containment
            block_polygons = builder.build_polygons_with_holes(
                group_polylines,
                min_area=MIN_POLYGON_AREA,
                validate=True,
                remove_largest_outer=False  # НЕ удаляем внешний контур для ЗПР
            )

            if block_polygons:
                # Для каждого блока может быть несколько полигонов
                # (если в блоке несколько несвязанных контуров)
                # Все полигоны блока получают одинаковые атрибуты
                for polygon in block_polygons:
                    polygons_with_attrs.append((polygon, group_attributes))

                # Считаем дырки
                stats = builder.get_statistics()
                total_holes += stats['holes_created']

        if not polygons_with_attrs:
            self.log_message("Не удалось создать полигоны из блоков", Qgis.Warning)
            return None

        self.log_message(f"Итого: {len(polygons_with_attrs)} полигонов с {total_holes} внутренними контурами")

        # Создаём слой с атрибутами блоков
        result_layer = self._create_layer_with_block_attributes(
            polygons_with_attrs,
            layer_name
        )

        return result_layer

    def _create_layer_with_block_attributes(self,
                                            polygons_with_attrs: List[Tuple[QgsGeometry, Dict[str, str]]],
                                            layer_name: str) -> Optional[QgsVectorLayer]:
        """
        Создание слоя с полигонами и атрибутами из DXF блоков.

        Структура полей:
        1. Служебные поля: id, area, holes_count
        2. Поля из атрибутов блоков (ATTRIB): динамически создаются на основе тегов

        Args:
            polygons_with_attrs: Список кортежей (геометрия, атрибуты блока)
            layer_name: Имя слоя

        Returns:
            QgsVectorLayer или None
        """
        from qgis.PyQt.QtCore import QMetaType

        # Собираем все уникальные теги атрибутов из всех блоков
        all_attribute_tags = set()
        for _, attrs in polygons_with_attrs:
            all_attribute_tags.update(attrs.keys())

        all_attribute_tags = sorted(list(all_attribute_tags))

        if all_attribute_tags:
            self.log_message(f"Обнаружено {len(all_attribute_tags)} уникальных атрибутов блоков: {', '.join(all_attribute_tags[:5])}{'...' if len(all_attribute_tags) > 5 else ''}")

        # Получаем CRS
        crs = self.get_project_crs()
        crs_authid = crs.authid() if crs and crs.isValid() else "EPSG:4326"

        # Создаём слой
        layer = QgsVectorLayer(
            f"MultiPolygon?crs={crs_authid}",
            layer_name,
            "memory"
        )

        if not layer.isValid():
            self.log_message("Ошибка: не удалось создать memory layer", Qgis.Critical)
            return None

        # Начинаем редактирование для добавления полей
        layer.startEditing()

        # Определяем типы полей на основе анализа значений
        # DXF хранит все атрибуты как текст, но мы можем определить тип по содержимому
        tag_types = self._detect_attribute_types(polygons_with_attrs, all_attribute_tags)

        # Поля из атрибутов блоков с проверкой дубликатов
        # Включаем "id" и "fid" в reserved для предотвращения конфликта с GeoPackage
        existing_names = {"id", "fid"}
        tag_to_field = {}  # Маппинг тег -> имя поля

        for tag in all_attribute_tags:
            field_name = self._sanitize_field_name(tag, existing_names)
            tag_to_field[tag] = field_name
            field_type = tag_types.get(tag, QMetaType.Type.QString)
            layer.addAttribute(QgsField(field_name, field_type))

        layer.updateFields()

        # Создаём features
        for idx, (polygon, attrs) in enumerate(polygons_with_attrs, start=1):
            if not polygon or polygon.isEmpty():
                continue

            # Валидация и исправление геометрии
            if not polygon.isGeosValid():
                polygon = polygon.makeValid()
                if not polygon or polygon.isEmpty() or not polygon.isGeosValid():
                    log_warning(f"Fsm_1_1_1: Полигон #{idx} невалиден, пропускаем")
                    continue

            # UNIFIED PATTERN: Конвертируем в MultiPolygon если нужно
            if not polygon.isMultipart():
                poly_data = polygon.asPolygon()
                if poly_data:
                    polygon = QgsGeometry.fromMultiPolygonXY([poly_data])

            # Создаём feature
            feature = QgsFeature(layer.fields())
            feature.setGeometry(polygon)

            # Атрибуты блока через маппинг тег -> поле (с конвертацией типов)
            for tag, value in attrs.items():
                field_name = tag_to_field.get(tag)
                if field_name:
                    field_type = tag_types.get(tag, QMetaType.Type.QString)
                    converted_value = self._convert_value(value, field_type)
                    feature.setAttribute(field_name, converted_value)

            layer.addFeature(feature)

        layer.commitChanges()
        layer.updateExtents()

        attrs_count = len(all_attribute_tags)
        self.log_message(f"Создан слой '{layer_name}' с {layer.featureCount()} полигонами и {attrs_count} атрибутами блоков")

        return layer

    def _detect_attribute_types(self,
                                polygons_with_attrs: List[Tuple[QgsGeometry, Dict[str, str]]],
                                tags: List[str]) -> Dict[str, Any]:
        """
        Определение типов атрибутов на основе анализа всех значений.

        DXF хранит все атрибуты как текст. Анализируем значения:
        - Если ВСЕ значения целые числа -> Int
        - Если ВСЕ значения числа (включая дробные) -> Double
        - Иначе -> QString

        Args:
            polygons_with_attrs: Список (геометрия, атрибуты)
            tags: Список тегов для анализа

        Returns:
            Словарь {tag: QMetaType.Type}
        """
        from qgis.PyQt.QtCore import QMetaType

        tag_types = {}

        for tag in tags:
            all_values = []
            for _, attrs in polygons_with_attrs:
                if tag in attrs:
                    value = attrs[tag]
                    if value is not None and value != '':
                        all_values.append(value)

            if not all_values:
                tag_types[tag] = QMetaType.Type.QString
                continue

            # Проверяем: все целые?
            all_int = True
            all_numeric = True

            for val in all_values:
                val_str = str(val).strip()

                # Проверка на целое число
                try:
                    int(val_str)
                except ValueError:
                    all_int = False

                # Проверка на число (включая дробные)
                try:
                    float(val_str.replace(',', '.'))
                except ValueError:
                    all_numeric = False

            if all_int:
                tag_types[tag] = QMetaType.Type.Int
            elif all_numeric:
                tag_types[tag] = QMetaType.Type.Double
            else:
                tag_types[tag] = QMetaType.Type.QString

        return tag_types

    def _convert_value(self, value: str, field_type: Any) -> Any:
        """
        Конвертация строкового значения в нужный тип.

        Args:
            value: Строковое значение из DXF
            field_type: QMetaType.Type

        Returns:
            Сконвертированное значение
        """
        from qgis.PyQt.QtCore import QMetaType

        if value is None or value == '':
            return None

        try:
            if field_type == QMetaType.Type.Int:
                return int(value)
            elif field_type == QMetaType.Type.Double:
                return float(str(value).replace(',', '.'))
            else:
                return str(value)
        except (ValueError, TypeError):
            return str(value)

    def _sanitize_field_name(self, name: str, existing_names: set) -> str:
        """
        Очистка имени поля от недопустимых символов.
        Поддерживает кириллицу (isalnum() корректно работает с Unicode).

        Args:
            name: Исходное имя
            existing_names: Множество уже использованных имён (обновляется)

        Returns:
            Очищенное уникальное имя поля
        """
        # Заменяем пробелы и дефисы на underscore
        sanitized = name.replace(' ', '_').replace('-', '_')
        sanitized = ''.join(c if c.isalnum() or c == '_' else '_' for c in sanitized)

        # Убираем множественные underscore
        while '__' in sanitized:
            sanitized = sanitized.replace('__', '_')

        # Убираем underscore в начале и конце
        sanitized = sanitized.strip('_')

        # Если пустое - генерируем имя
        if not sanitized:
            sanitized = "attr"

        # Обработка дубликатов
        base_name = sanitized
        counter = 1
        while sanitized in existing_names:
            sanitized = f"{base_name}_{counter}"
            counter += 1

        existing_names.add(sanitized)
        return sanitized

    def _build_line_layer(self, polylines: List[QgsGeometry],
                          layer_name: str) -> Optional[QgsVectorLayer]:
        """
        Построение линейного слоя из полилиний

        Args:
            polylines: Список QgsGeometry (LineString)
            layer_name: Имя слоя

        Returns:
            QgsVectorLayer или None
        """
        layer = QgsVectorLayer(
            "LineString?crs=EPSG:4326",
            layer_name,
            "memory"
        )

        layer.startEditing()
        layer.addAttribute(QgsField("id", QMetaType.Type.Int))

        for i, geom in enumerate(polylines):
            if geom and not geom.isEmpty():
                feature = QgsFeature()
                feature.setGeometry(geom)
                feature.setAttributes([i + 1])
                layer.addFeature(feature)

        layer.commitChanges()

        self.log_message(f"Создан линейный слой с {layer.featureCount()} объектами")

        return layer

    def _get_expected_geometry_type(self, layer_name: str) -> Optional[str]:
        """
        Получение ожидаемого типа геометрии из Base_layers.json

        Args:
            layer_name: Полное имя слоя (например "L_1_1_1_Границы_работ")

        Returns:
            Тип геометрии ('Point', 'LineString', 'Polygon') или None
        """
        try:
            from Daman_QGIS.managers import get_reference_managers
            ref_managers = get_reference_managers()
            layer_info = ref_managers.layer.get_layer_by_full_name(layer_name)

            if layer_info:
                geom_type = layer_info.get('geometry_type', '').strip()
                if geom_type and geom_type not in ['-', 'not', '']:
                    self.log_message(f"Ожидаемый тип геометрии для '{layer_name}': {geom_type}")
                    return geom_type

            self.log_message(f"Слой '{layer_name}' не найден в Base_layers.json или geometry_type не задан", Qgis.Warning)
            return None

        except Exception as e:
            self.log_message(f"Ошибка получения geometry_type для '{layer_name}': {str(e)}", Qgis.Warning)
            return None

    def _create_buffer_layers(self, source_layer: QgsVectorLayer) -> None:
        """
        Создание буферных слоёв для L_1_1_1_Границы_работ

        Автоматически создаёт три буферных слоя:
        - L_1_1_2_Границы_работ_10_м (буфер +10 метров)
        - L_1_1_3_Границы_работ_500_м (буфер +500 метров)
        - L_1_1_4_Границы_работ_-2_см (буфер -2 сантиметра)

        Args:
            source_layer: Исходный слой L_1_1_1_Границы_работ
        """
        self.log_message("Создание буферных слоёв для границ работ...")

        # Определяем буферные слои: (имя, расстояние в метрах, описание)
        buffer_configs = [
            ('L_1_1_2_Границы_работ_10_м', 10.0, 'буфер +10 метров'),
            ('L_1_1_3_Границы_работ_500_м', 500.0, 'буфер +500 метров'),
            ('L_1_1_4_Границы_работ_-2_см', -0.02, 'буфер -2 см (внутренний)')
        ]

        for layer_name, distance, description in buffer_configs:
            try:
                self.log_message(f"Создание слоя {layer_name} ({description})...")

                # Создаём буферный слой через processing
                buffer_result = processing.run("native:buffer", {
                    'INPUT': source_layer,
                    'DISTANCE': distance,
                    'SEGMENTS': 25,  # Количество сегментов для аппроксимации окружности
                    'END_CAP_STYLE': 0,  # Round (закругление)
                    'JOIN_STYLE': 0,  # Round (закругление)
                    'MITER_LIMIT': 2,
                    'DISSOLVE': False,
                    'OUTPUT': 'memory:'
                })

                buffer_layer = buffer_result['OUTPUT']

                if not buffer_layer or not buffer_layer.isValid():
                    self.log_message(f"Ошибка создания буферного слоя {layer_name}", Qgis.Warning)
                    continue

                # Устанавливаем имя слоя
                buffer_layer.setName(layer_name)

                # Устанавливаем ту же СК что и у исходного слоя
                buffer_layer.setCrs(source_layer.crs())

                # Сохраняем в GPKG (если memory layer)
                if buffer_layer.dataProvider().name() == 'memory':
                    from ..core import LayerProcessor
                    processor = LayerProcessor(self.project_manager, self.layer_manager)
                    saved_layer = processor.save_to_gpkg(buffer_layer, layer_name)
                    if saved_layer:
                        buffer_layer = saved_layer
                        self.log_message(f"Буферный слой '{layer_name}' сохранён в GPKG")

                # Добавляем слой в проект через LayerManager (автоматическое применение стилей)
                if self.layer_manager:
                    # Если слой уже в GPKG, удаляем его из проекта перед повторным добавлением
                    if buffer_layer.id() in QgsProject.instance().mapLayers():
                        QgsProject.instance().removeMapLayer(buffer_layer.id())

                    self.layer_manager.add_layer(
                        buffer_layer,
                        make_readonly=False,
                        auto_number=False,
                        check_precision=False
                    )
                    self.log_message(f"Буферный слой '{layer_name}' добавлен через LayerManager")
                else:
                    QgsProject.instance().addMapLayer(buffer_layer)
                    self.log_message(f"Буферный слой '{layer_name}' добавлен напрямую")

                # Добавляем в список созданных слоёв для возврата результата
                self.created_layers.append(buffer_layer)

                self.log_message(f"Слой {layer_name} успешно создан ({buffer_layer.featureCount()} объектов)")

            except Exception as e:
                self.log_message(f"Ошибка при создании буферного слоя {layer_name}: {str(e)}", Qgis.Critical)
                log_error(f"DxfImporter: Ошибка создания буферного слоя {layer_name}: {str(e)}")

        self.log_message("Создание буферных слоёв завершено")
