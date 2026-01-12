# -*- coding: utf-8 -*-
"""
Субмодуль экспорта перечней кадастровых номеров для бюджета
Экспортирует списки кадастровых номеров ЗУ, ОКС и Кварталов в XLSX
"""

import os
from typing import List, Tuple
from qgis.core import QgsProject, QgsVectorLayer
from Daman_QGIS.utils import log_info, log_warning, log_error


class CadnumListExporter:
    """Экспортер перечней кадастровых номеров"""

    def __init__(self, iface):
        """
        Инициализация экспортера

        Args:
            iface: Интерфейс QGIS
        """
        self.iface = iface

    def export_cadnum_lists(self, output_folder: str) -> Tuple[bool, str]:
        """
        Экспорт перечней кадастровых номеров в XLSX

        Args:
            output_folder: Папка для сохранения файла

        Returns:
            tuple: (success, filepath) - успешность экспорта и путь к файлу
        """
        try:
            import xlsxwriter
        except ImportError:
            log_error("Fsm_1_3_8: Библиотека xlsxwriter не установлена!")
            return False, ""

        # Собираем кадастровые номера из слоев
        # ВАЖНО: Для ЗУ используем слой Le_2_1_1_1_Выборка_ЗУ (без буфера 10м),
        # а НЕ L_1_2_1_WFS_ЗУ (который загружается с буфером для WFS запросов)
        land_plots = self._collect_cadnums_from_layer('Le_2_1_1_1_Выборка_ЗУ')
        capital_objects = self._collect_capital_objects_cadnums()
        cadastral_quarters = self._collect_cadnums_from_layer('L_1_2_2_WFS_КК')

        # Убираем дубликаты и сортируем по числовому порядку
        land_plots_sorted = self._sort_cadastral_numbers(list(set(land_plots)))
        capital_objects_sorted = self._sort_cadastral_numbers(list(set(capital_objects)))
        cadastral_quarters_sorted = self._sort_cadastral_numbers(list(set(cadastral_quarters)))

        # Создаем Excel файл
        filepath = os.path.join(output_folder, "Перечень.xlsx")

        try:
            workbook = xlsxwriter.Workbook(filepath)

            # Форматы
            header_format = workbook.add_format({
                'font_name': 'Times New Roman',
                'font_size': 12,
                'bold': True,
                'align': 'center',
                'valign': 'vcenter',
                'border': 1
            })

            cell_format = workbook.add_format({
                'font_name': 'Times New Roman',
                'font_size': 11,
                'align': 'left',
                'valign': 'vcenter',
                'border': 1
            })

            # Создаем 3 отдельных листа
            # Лист 1: Земельные участки
            ws_zu = workbook.add_worksheet('Земельные участки')
            ws_zu.set_column(0, 0, 30)
            ws_zu.write(0, 0, 'Кадастровый номер', header_format)
            for row, cadnum in enumerate(land_plots_sorted, start=1):
                ws_zu.write(row, 0, cadnum, cell_format)

            # Лист 2: ОКС
            ws_oks = workbook.add_worksheet('ОКС')
            ws_oks.set_column(0, 0, 30)
            ws_oks.write(0, 0, 'Кадастровый номер', header_format)
            for row, cadnum in enumerate(capital_objects_sorted, start=1):
                ws_oks.write(row, 0, cadnum, cell_format)

            # Лист 3: Кадастровые кварталы
            ws_kk = workbook.add_worksheet('Кадастровые кварталы')
            ws_kk.set_column(0, 0, 30)
            ws_kk.write(0, 0, 'Кадастровый номер', header_format)
            for row, cadnum in enumerate(cadastral_quarters_sorted, start=1):
                ws_kk.write(row, 0, cadnum, cell_format)

            # Закрываем файл
            workbook.close()

            log_info(f"Fsm_1_3_8: Перечень кадастровых номеров сохранен: {filepath}")
            log_info(f"Fsm_1_3_8:   ЗУ: {len(land_plots_sorted)}, ОКС: {len(capital_objects_sorted)}, Кварталы: {len(cadastral_quarters_sorted)}")

            return True, filepath

        except Exception as e:
            log_error(f"Fsm_1_3_8: Ошибка создания Excel файла: {str(e)}")
            return False, ""

    def _collect_cadnums_from_layer(self, layer_name: str) -> List[str]:
        """
        Собрать кадастровые номера из слоя с фильтрацией по границам L_1_1_1

        Args:
            layer_name: Имя слоя

        Returns:
            list: Список кадастровых номеров только внутри границ (может содержать дубликаты, дедупликация происходит позже)
        """
        from qgis.core import QgsGeometry, QgsFeatureRequest, QgsCoordinateTransform

        cadnums = []

        # Ищем слой в проекте
        layers = QgsProject.instance().mapLayersByName(layer_name)
        if not layers:
            log_warning(f"Fsm_1_3_8: Слой '{layer_name}' не найден")
            return cadnums

        layer = layers[0]
        if not isinstance(layer, QgsVectorLayer):
            log_warning(f"Fsm_1_3_8: Слой '{layer_name}' не является векторным")
            return cadnums

        # Проверяем наличие поля cad_num
        field_names = [field.name() for field in layer.fields()]
        if 'cad_num' not in field_names:
            log_warning(f"Fsm_1_3_8: Слой '{layer_name}' не содержит поле 'cad_num'")
            return cadnums

        # Получаем геометрию границ L_1_1_1
        boundaries_geom = self._get_boundaries_geometry()
        if not boundaries_geom:
            log_warning("Fsm_1_3_8: Не удалось получить геометрию границ L_1_1_1, экспорт всех объектов слоя")
            # Резервный вариант - экспортируем все
            for feature in layer.getFeatures():
                cad_num = feature['cad_num']
                if cad_num and cad_num not in [None, '', 'NULL']:
                    cadnums.append(str(cad_num))
            return cadnums

        # Получаем слой границ для CRS
        boundaries_layers = QgsProject.instance().mapLayersByName('L_1_1_1_Границы_работ')
        if not boundaries_layers:
            log_warning("Fsm_1_3_8: Слой L_1_1_1_Границы_работ не найден")
            return cadnums

        boundaries_layer = boundaries_layers[0]
        boundaries_crs = boundaries_layer.crs()
        layer_crs = layer.crs()

        # Создаем трансформацию если нужно
        transform = None
        if boundaries_crs != layer_crs:
            transform = QgsCoordinateTransform(layer_crs, boundaries_crs, QgsProject.instance())

        # Получаем bbox для оптимизации
        bbox = boundaries_geom.boundingBox()
        if transform:
            # Трансформируем bbox в CRS слоя
            transform_bbox = QgsCoordinateTransform(boundaries_crs, layer_crs, QgsProject.instance())
            bbox = transform_bbox.transformBoundingBox(bbox)

        # Создаем запрос с фильтрацией по bbox
        request = QgsFeatureRequest()
        request.setFilterRect(bbox)

        # Собираем кадастровые номера только для объектов внутри границ
        for feature in layer.getFeatures(request):
            if feature.hasGeometry():
                geom = feature.geometry()
                if geom and not geom.isNull():
                    # Трансформируем геометрию если нужно
                    if transform:
                        geom = QgsGeometry(geom)  # Копия
                        geom.transform(transform)

                    # Проверяем пересечение с границами
                    if geom.intersects(boundaries_geom):
                        cad_num = feature['cad_num']
                        if cad_num and cad_num not in [None, '', 'NULL']:
                            cadnums.append(str(cad_num))

        return cadnums

    def _get_boundaries_geometry(self):
        """
        Получить объединенную геометрию границ L_1_1_1

        Returns:
            QgsGeometry: Объединенная геометрия или None
        """
        from qgis.core import QgsGeometry

        try:
            # Ищем слой границ
            boundaries_layers = QgsProject.instance().mapLayersByName('L_1_1_1_Границы_работ')
            if not boundaries_layers:
                log_warning("Слой L_1_1_1_Границы_работ не найден")
                return None

            boundaries_layer = boundaries_layers[0]
            if not isinstance(boundaries_layer, QgsVectorLayer):
                log_warning("Слой L_1_1_1_Границы_работ не является векторным")
                return None
            geometries = []

            for feature in boundaries_layer.getFeatures():
                if feature.hasGeometry():
                    geom = feature.geometry()
                    if geom and not geom.isNull():
                        geometries.append(geom)

            if geometries:
                # Объединяем все геометрии
                united = QgsGeometry.unaryUnion(geometries)
                if united and not united.isNull():
                    return united

            return None

        except Exception as e:
            log_warning(f"Fsm_1_3_8: Ошибка получения геометрии границ: {str(e)}")
            return None

    def _collect_capital_objects_cadnums(self) -> List[str]:
        """
        Собрать кадастровые номера ОКС из родительского слоя L_1_2_4_WFS_ОКС

        Returns:
            list: Список кадастровых номеров всех ОКС (может содержать дубликаты, дедупликация происходит позже)
        """
        # Используем родительский слой ОКС, который объединяет все подслои (ОНС, Здания, Сооружения)
        return self._collect_cadnums_from_layer('L_1_2_4_WFS_ОКС')

    def _sort_cadastral_numbers(self, cadnums: List[str]) -> List[str]:
        """
        Сортировка кадастровых номеров по числовому порядку

        Кадастровый номер имеет вид AA:BB:CCCCCC:DD
        Сортируем по каждой части как по числу

        Args:
            cadnums: Список уникальных кадастровых номеров

        Returns:
            list: Отсортированный список уникальных кадастровых номеров
        """
        def parse_cadnum(cadnum: str) -> Tuple:
            """Парсинг кадастрового номера в кортеж чисел"""
            try:
                parts = cadnum.split(':')
                # Преобразуем каждую часть в int для корректной сортировки
                return tuple(int(part) for part in parts)
            except (ValueError, AttributeError):
                # Если не удается распарсить, возвращаем строку как есть
                # Такие номера будут в конце списка
                return (999999, 999999, 999999, 999999)

        # Сортируем по разобранным частям
        sorted_cadnums = sorted(cadnums, key=parse_cadnum)

        return sorted_cadnums
