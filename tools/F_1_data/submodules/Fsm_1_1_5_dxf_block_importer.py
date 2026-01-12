# -*- coding: utf-8 -*-
"""
Fsm_1_1_5_DxfBlockImporter - Импортер блоков DXF с атрибутами (INSERT + ATTRIB)

Использует библиотеку ezdxf для чтения блоков и их атрибутов из DXF файлов.
OGR провайдер QGIS не поддерживает импорт блоков DXF, поэтому необходим
отдельный парсер на ezdxf.

Назначение:
- Импорт INSERT entities (блоков) из DXF
- Извлечение всех ATTRIB значений (переменное количество)
- Создание точечных слоёв с атрибутами из блоков
"""

import os
import re
from types import ModuleType
from typing import Optional, List, Dict, Any
from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsField,
    QgsGeometry, QgsPointXY, QgsProject,
    QgsCoordinateReferenceSystem
)
from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.utils import log_info, log_warning, log_error


class Fsm_1_1_5_DxfBlockImporter:
    """
    Импортер DXF блоков (INSERT entities) с атрибутами (ATTRIB)

    Особенности:
    - Использует ezdxf для парсинга (не OGR)
    - Поддерживает переменное количество атрибутов в блоках
    - Создаёт точечный слой с позициями блоков
    - Все атрибуты блока становятся полями слоя
    """

    def __init__(self, iface=None):
        """
        Инициализация импортера

        Args:
            iface: Интерфейс QGIS (опционально)
        """
        self.iface = iface
        self.project_manager = None
        self.layer_manager = None
        self._ezdxf: Optional[ModuleType] = None

    def set_project_manager(self, project_manager):
        """Установка менеджера проектов"""
        self.project_manager = project_manager

    def set_layer_manager(self, layer_manager):
        """Установка менеджера слоёв"""
        self.layer_manager = layer_manager

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
            log_info("Fsm_1_1_5: ezdxf успешно импортирован")
            return True
        except ImportError as e:
            log_error(f"Fsm_1_1_5: ezdxf не установлен: {e}")
            return False

    def import_blocks(self, file_path: str,
                     target_layer_name: str = "DXF_Blocks",
                     block_names: Optional[List[str]] = None,
                     crs: Optional[QgsCoordinateReferenceSystem] = None,
                     encoding: Optional[str] = None
                     ) -> Dict[str, Any]:
        """
        Импорт блоков из DXF файла

        Args:
            file_path: Путь к DXF файлу
            target_layer_name: Имя создаваемого слоя
            block_names: Список имён блоков для импорта (None = все)
            crs: Система координат (None = из проекта)
            encoding: Кодировка файла (None = авто-определение из $CODEPAGE).
                      Для кириллицы используйте 'cp1251' если авто-определение не работает.

        Returns:
            Словарь с результатами:
            - success: bool
            - layer: QgsVectorLayer или None
            - blocks_count: int
            - attributes_found: List[str]
            - message: str
            - errors: List[str]
        """
        result = {
            'success': False,
            'layer': None,
            'blocks_count': 0,
            'attributes_found': [],
            'message': '',
            'errors': []
        }

        # Проверяем ezdxf
        if not self._ensure_ezdxf():
            result['errors'].append("Библиотека ezdxf не установлена. Установите через F_5_1.")
            result['message'] = "ezdxf не установлен"
            return result

        # Проверяем файл
        if not os.path.exists(file_path):
            result['errors'].append(f"Файл не найден: {file_path}")
            result['message'] = "Файл не найден"
            return result

        try:
            # Читаем DXF файл
            # ezdxf автоматически определяет кодировку из $CODEPAGE в заголовке DXF
            # Поддерживает: UTF-8, CP1251 (кириллица), CP1252 (латиница) и др.
            log_info(f"Fsm_1_1_5: Открытие файла {os.path.basename(file_path)}")
            assert self._ezdxf is not None  # Гарантировано _ensure_ezdxf()

            # Определяем кодировку для чтения
            # Для русских DXF файлов с $CODEPAGE=ANSI_1251 нужно явно указать cp1251
            read_encoding = encoding
            if read_encoding is None:
                # Пробуем определить кодировку из файла
                read_encoding = self._detect_dxf_encoding(file_path)

            doc = self._ezdxf.readfile(file_path, encoding=read_encoding)  # type: ignore[attr-defined]

            # Логируем обнаруженную кодировку
            codepage = doc.header.get('$CODEPAGE', 'не указана')
            log_info(f"Fsm_1_1_5: Кодировка DXF: {codepage}, используемая: {read_encoding or 'auto'}")

            msp = doc.modelspace()

            # Извлекаем блоки с атрибутами
            blocks_data = self._extract_blocks_with_attributes(msp, block_names)

            if not blocks_data:
                result['message'] = "В файле не найдено блоков с атрибутами"
                result['success'] = True  # Не ошибка, просто нет данных
                return result

            # Собираем все уникальные теги атрибутов
            all_attribute_tags = self._collect_all_attribute_tags(blocks_data)
            result['attributes_found'] = all_attribute_tags

            log_info(f"Fsm_1_1_5: Найдено {len(blocks_data)} блоков, "
                    f"атрибутов: {len(all_attribute_tags)}")

            # Определяем CRS
            if crs is None:
                crs = self._get_project_crs()

            # Создаём слой
            layer = self._create_layer_from_blocks(
                blocks_data,
                all_attribute_tags,
                target_layer_name,
                crs
            )

            if not layer or not layer.isValid():
                result['errors'].append("Не удалось создать слой")
                result['message'] = "Ошибка создания слоя"
                return result

            result['success'] = True
            result['layer'] = layer
            result['blocks_count'] = len(blocks_data)
            result['message'] = (f"Импортировано {len(blocks_data)} блоков "
                               f"с {len(all_attribute_tags)} атрибутами")

            log_info(f"Fsm_1_1_5: {result['message']}")

        except Exception as e:
            log_error(f"Fsm_1_1_5: Ошибка импорта: {e}")
            result['errors'].append(str(e))
            result['message'] = f"Ошибка: {e}"

        return result

    def _extract_blocks_with_attributes(self,
                                        modelspace,
                                        block_names: Optional[List[str]] = None
                                        ) -> List[Dict[str, Any]]:
        """
        Извлечение данных блоков с атрибутами из modelspace

        Args:
            modelspace: Modelspace объект ezdxf
            block_names: Фильтр по именам блоков (None = все)

        Returns:
            Список словарей с данными блоков:
            [
                {
                    'block_name': str,
                    'position': (x, y),
                    'rotation': float,
                    'scale': (sx, sy, sz),
                    'layer': str,
                    'attributes': {'TAG1': 'value1', 'TAG2': 'value2', ...}
                },
                ...
            ]
        """
        blocks_data = []

        # Ищем все INSERT entities
        for insert in modelspace.query('INSERT'):
            # Фильтруем по имени блока если задано
            block_name = insert.dxf.name
            if block_names and block_name not in block_names:
                continue

            # Получаем атрибуты блока
            attributes = {}
            for attrib in insert.attribs:
                tag = attrib.dxf.tag
                text = attrib.dxf.text
                attributes[tag] = text

            # Если нет атрибутов - пропускаем (опционально можно убрать)
            # Для задачи пользователя - нужны именно блоки с атрибутами
            if not attributes:
                continue

            # Позиция вставки блока
            insert_point = insert.dxf.insert

            # Собираем данные блока
            block_data = {
                'block_name': block_name,
                'position': (insert_point.x, insert_point.y),
                'rotation': insert.dxf.rotation if hasattr(insert.dxf, 'rotation') else 0.0,
                'scale': (
                    insert.dxf.xscale if hasattr(insert.dxf, 'xscale') else 1.0,
                    insert.dxf.yscale if hasattr(insert.dxf, 'yscale') else 1.0,
                    insert.dxf.zscale if hasattr(insert.dxf, 'zscale') else 1.0
                ),
                'layer': insert.dxf.layer,
                'attributes': attributes
            }

            blocks_data.append(block_data)

        return blocks_data

    def _collect_all_attribute_tags(self, blocks_data: List[Dict[str, Any]]) -> List[str]:
        """
        Сбор всех уникальных тегов атрибутов из блоков

        Args:
            blocks_data: Список данных блоков

        Returns:
            Отсортированный список уникальных тегов
        """
        all_tags = set()

        for block in blocks_data:
            all_tags.update(block['attributes'].keys())

        return sorted(list(all_tags))

    def _create_layer_from_blocks(self,
                                  blocks_data: List[Dict[str, Any]],
                                  attribute_tags: List[str],
                                  layer_name: str,
                                  crs: QgsCoordinateReferenceSystem
                                  ) -> Optional[QgsVectorLayer]:
        """
        Создание точечного слоя из данных блоков

        Args:
            blocks_data: Список данных блоков
            attribute_tags: Список тегов атрибутов для создания полей
            layer_name: Имя слоя
            crs: Система координат

        Returns:
            QgsVectorLayer или None
        """
        # Создаём memory layer
        crs_string = crs.authid() if crs and crs.isValid() else "EPSG:4326"

        layer = QgsVectorLayer(
            f"Point?crs={crs_string}",
            layer_name,
            "memory"
        )

        if not layer.isValid():
            log_error(f"Fsm_1_1_5: Не удалось создать memory layer")
            return None

        # Начинаем редактирование
        layer.startEditing()

        # Добавляем служебные поля
        layer.addAttribute(QgsField("block_name", QMetaType.Type.QString))
        layer.addAttribute(QgsField("dxf_layer", QMetaType.Type.QString))
        layer.addAttribute(QgsField("rotation", QMetaType.Type.Double))

        # Создаём маппинг tag -> field_name с проверкой дубликатов
        existing_names: set = {"block_name", "dxf_layer", "rotation"}
        tag_to_field: Dict[str, str] = {}

        # Добавляем поля для каждого атрибута
        for tag in attribute_tags:
            # Имя поля: используем tag, очищенный от недопустимых символов
            field_name = self._sanitize_field_name(tag, existing_names)
            tag_to_field[tag] = field_name
            layer.addAttribute(QgsField(field_name, QMetaType.Type.QString))

        layer.updateFields()

        # Добавляем features
        for block in blocks_data:
            feature = QgsFeature(layer.fields())

            # Геометрия - точка в позиции блока
            x, y = block['position']
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))

            # Служебные поля
            feature.setAttribute("block_name", block['block_name'])
            feature.setAttribute("dxf_layer", block['layer'])
            feature.setAttribute("rotation", block['rotation'])

            # Атрибуты блока через маппинг
            for tag, value in block['attributes'].items():
                field_name = tag_to_field.get(tag)
                if field_name:
                    feature.setAttribute(field_name, value)

            layer.addFeature(feature)

        layer.commitChanges()

        log_info(f"Fsm_1_1_5: Создан слой '{layer_name}' с {layer.featureCount()} объектами")

        return layer

    def _sanitize_field_name(self, name: str, existing_names: Optional[set] = None) -> str:
        """
        Очистка имени поля от недопустимых символов

        Поддерживает кириллицу в именах полей (isalnum() корректно работает с Unicode).

        Args:
            name: Исходное имя (может содержать кириллицу)
            existing_names: Множество уже использованных имён (для предотвращения дубликатов)

        Returns:
            Очищенное имя поля
        """
        # Заменяем недопустимые символы на underscore
        # isalnum() корректно обрабатывает Unicode (включая кириллицу)
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

        # Обработка дубликатов если указано множество существующих имён
        if existing_names is not None:
            base_name = sanitized
            counter = 1
            while sanitized in existing_names:
                sanitized = f"{base_name}_{counter}"
                counter += 1
            existing_names.add(sanitized)

        return sanitized

    def _detect_dxf_encoding(self, file_path: str) -> Optional[str]:
        """
        Определение кодировки DXF файла из заголовка $CODEPAGE

        DXF файлы созданные в русских версиях AutoCAD обычно имеют $CODEPAGE=ANSI_1251.
        ezdxf не всегда корректно интерпретирует эту кодировку, поэтому определяем вручную.

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
                log_info(f"Fsm_1_1_5: Обнаружена $CODEPAGE: {codepage}")

                encoding = codepage_map.get(codepage)
                if encoding:
                    log_info(f"Fsm_1_1_5: Используем кодировку: {encoding}")
                    return encoding
                else:
                    log_warning(f"Fsm_1_1_5: Неизвестная $CODEPAGE: {codepage}, используем cp1251")
                    # Для неизвестных ANSI кодировок на русских системах - cp1251
                    return 'cp1251'
            else:
                # $CODEPAGE не найден - для русских систем предполагаем cp1251
                log_info("Fsm_1_1_5: $CODEPAGE не найден, используем cp1251 по умолчанию")
                return 'cp1251'

        except Exception as e:
            log_warning(f"Fsm_1_1_5: Ошибка определения кодировки: {e}, используем cp1251")
            return 'cp1251'

    def _get_project_crs(self) -> QgsCoordinateReferenceSystem:
        """
        Получение CRS из проекта

        Returns:
            CRS проекта или WGS-84 по умолчанию
        """
        # Сначала пробуем из project_manager
        if self.project_manager:
            try:
                crs = self.project_manager.get_project_crs()
                if crs and crs.isValid():
                    return crs
            except Exception:
                pass

        # Затем из текущего проекта QGIS
        project = QgsProject.instance()
        crs = project.crs()
        if crs.isValid():
            return crs

        # Fallback
        return QgsCoordinateReferenceSystem("EPSG:4326")

    def get_block_names(self, file_path: str) -> List[str]:
        """
        Получение списка имён блоков в DXF файле

        Args:
            file_path: Путь к DXF файлу

        Returns:
            Список уникальных имён блоков
        """
        if not self._ensure_ezdxf():
            return []

        try:
            assert self._ezdxf is not None  # Гарантировано _ensure_ezdxf()
            encoding = self._detect_dxf_encoding(file_path)
            doc = self._ezdxf.readfile(file_path, encoding=encoding)  # type: ignore[attr-defined]
            msp = doc.modelspace()

            block_names = set()
            for insert in msp.query('INSERT'):
                block_names.add(insert.dxf.name)

            return sorted(list(block_names))

        except Exception as e:
            log_error(f"Fsm_1_1_5: Ошибка чтения блоков: {e}")
            return []

    def get_block_attributes_preview(self, file_path: str,
                                     max_blocks: int = 5) -> Dict[str, List[Dict[str, str]]]:
        """
        Предварительный просмотр атрибутов блоков

        Args:
            file_path: Путь к DXF файлу
            max_blocks: Максимальное количество блоков для предпросмотра

        Returns:
            Словарь {block_name: [{'tag': 'value', ...}, ...]}
        """
        if not self._ensure_ezdxf():
            return {}

        try:
            assert self._ezdxf is not None  # Гарантировано _ensure_ezdxf()
            encoding = self._detect_dxf_encoding(file_path)
            doc = self._ezdxf.readfile(file_path, encoding=encoding)  # type: ignore[attr-defined]
            msp = doc.modelspace()

            preview = {}
            block_counts = {}

            for insert in msp.query('INSERT'):
                block_name = insert.dxf.name

                # Ограничиваем количество блоков каждого типа
                block_counts[block_name] = block_counts.get(block_name, 0) + 1
                if block_counts[block_name] > max_blocks:
                    continue

                # Собираем атрибуты
                attributes = {attrib.dxf.tag: attrib.dxf.text
                             for attrib in insert.attribs}  # type: ignore[attr-defined]

                if attributes:
                    if block_name not in preview:
                        preview[block_name] = []
                    preview[block_name].append(attributes)

            return preview

        except Exception as e:
            log_error(f"Fsm_1_1_5: Ошибка предпросмотра: {e}")
            return {}
