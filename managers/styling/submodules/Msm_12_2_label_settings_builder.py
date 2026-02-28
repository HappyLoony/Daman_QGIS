# -*- coding: utf-8 -*-
"""
Построитель настроек подписей QGIS из конфигурации БД

Отвечает за:
- Создание QgsPalLayerSettings из конфигурации Base_labels.json
- Построение QgsTextFormat (шрифт, размер, цвет)
- Настройку буфера (QgsTextBufferSettings)
- Настройку размещения подписей
- Форматирование многострочного текста
"""

from qgis.core import (
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsTextBufferSettings,
    QgsSimpleLineCallout,
    QgsCallout,
    QgsLineSymbol,
    QgsMarkerLineSymbolLayer,
    QgsSimpleMarkerSymbolLayer,
    QgsMarkerSymbol,
    QgsVectorLayer,
    QgsGeometry,
    QgsPointXY,
    QgsRectangle,
    QgsCoordinateTransform,
    QgsProject,
    Qgis,
    QgsPropertyCollection,
    QgsProperty
)
from qgis.PyQt.QtGui import QColor, QFont
import math
from Daman_QGIS.constants import LAYER_BOUNDARIES_EXACT
from Daman_QGIS.utils import log_warning


class LabelSettingsBuilder:
    """Построитель QgsPalLayerSettings из конфигурации БД"""

    def __init__(self, expr_manager=None, label_ref_manager=None, layers_ref_manager=None):
        """
        Инициализация построителя

        Args:
            expr_manager: ExpressionManager для работы с выражениями (опционально)
            label_ref_manager: LabelReferenceManager для доступа к Base_labels.json (опционально)
            layers_ref_manager: LayerReferenceManager для доступа к Base_layers.json и order_layers (опционально)
        """
        self.expr_manager = expr_manager
        self.label_ref_manager = label_ref_manager
        self.layers_ref_manager = layers_ref_manager

    @staticmethod
    def get_sheet_extent(project, boundary_layer=None):
        """
        Получить extent листа для позиционирования надписей

        ПРИОРИТЕТЫ (от лучшего к fallback):
        1. Из активного Print Layout (layoutManager().layouts()[0].referenceMap().extent())
        2. ПРИБЛИЖЁННОЕ вычисление по масштабу и aspect ratio (fallback, если layout не создан)

        ВАЖНО:
        - Extent ВСЕГДА возвращается в СК слоя границ (трансформируется если нужно)
        - Метод выбора может измениться в будущем для поддержки Atlas
        - Fallback использует приближённую формулу (aspect_ratio ≈ 2.5), точность не гарантируется!

        Args:
            project: QgsProject.instance()
            boundary_layer: Слой границ (для СК и fallback, обязателен!)

        Returns:
            QgsRectangle: extent листа в СК boundaries или None
        """
        if not boundary_layer:
            log_warning("Msm_12_2: boundary_layer обязателен для get_sheet_extent()")
            return None

        boundary_crs = boundary_layer.crs()

        # УРОВЕНЬ 1: Попытка получить extent из Print Layout
        # TODO (будущее): Добавить поддержку Atlas (atlas.currentFeature().geometry().boundingBox())
        try:
            layout_manager = project.layoutManager()
            layouts = layout_manager.layouts()

            if layouts:
                first_layout = layouts[0]
                reference_map = first_layout.referenceMap()

                if reference_map:
                    extent = reference_map.extent()
                    map_crs = reference_map.crs()

                    if map_crs != boundary_crs:
                        transform = QgsCoordinateTransform(map_crs, boundary_crs, project)
                        extent_geom = QgsGeometry.fromRect(extent)
                        extent_geom.transform(transform)
                        extent = extent_geom.boundingBox()

                    return extent

        except Exception as e:
            log_warning(f"Msm_12_2: Ошибка получения extent из layout: {e}")

        # УРОВЕНЬ 2: Fallback - вычисление extent по масштабу (как в F_1_4)
        if boundary_layer:
            extent = boundary_layer.extent()

            # Вычисляем extent листа по масштабу как в F_1_4
            # Формула из Base_expressions.json (calc_map_scale)

            extent_width = extent.xMaximum() - extent.xMinimum()
            extent_height = extent.yMaximum() - extent.yMinimum()
            max_extent = max(extent_width, extent_height)

            # Универсальная формула масштаба (ряд 1-2-5)
            # Синхронизировано с calc_map_scale в Base_expressions.json
            raw_scale = max_extent * 5
            if raw_scale > 0:
                magnitude = math.floor(math.log10(raw_scale))
                normalized = raw_scale / (10 ** magnitude)
                if normalized <= 1:
                    scale = 10 ** magnitude
                elif normalized <= 2:
                    scale = 2 * (10 ** magnitude)
                elif normalized <= 5:
                    scale = 5 * (10 ** magnitude)
                else:
                    scale = 10 ** (magnitude + 1)
            else:
                scale = 1000  # fallback для пустого extent

            # ПРИБЛИЖЕНИЕ: boundaries ± 5% для масштаба подписей
            # TODO: После создания layout в F_1_4, получать extent из layout.referenceMap()

            margin_percent = 0.05  # 5% со всех сторон (как в template)

            margin_x = extent_width * margin_percent
            margin_y = extent_height * margin_percent

            calculated_extent = QgsRectangle(
                extent.xMinimum() - margin_x,  # left
                extent.yMinimum() - margin_y,  # bottom
                extent.xMaximum() + margin_x,  # right
                extent.yMaximum() + margin_y   # top
            )

            return calculated_extent

        return None

    def build(self, layer: QgsVectorLayer, config: dict) -> QgsPalLayerSettings:
        """
        Построить QgsPalLayerSettings из конфигурации Base_labels.json

        Алгоритм:
        1. ВСЕГДА создаём новые настройки (игнорируем QML)
        2. Применить параметры из БД
        3. Настройки из Base_labels.json имеют приоритет над QML

        Args:
            layer: Векторный слой QGIS
            config: Конфигурация подписей из Base_labels.json

        Returns:
            Настроенный QgsPalLayerSettings

        Example:
            >>> builder = LabelSettingsBuilder()
            >>> config = {'label_field': 'cad_num', 'label_font_size': 4.0, ...}
            >>> settings = builder.build(layer, config)
        """
        # ВСЕГДА создаём новые настройки, игнорируя старые из QML
        # Это гарантирует что настройки из Base_labels.json применяются корректно
        settings = QgsPalLayerSettings()

        # Поле для подписи
        label_field = config.get('label_field')
        has_labels = label_field and label_field != '-'

        if has_labels:
            # Проверяем существование поля в слое
            field_names = [field.name() for field in layer.fields()]
            if label_field not in field_names:
                log_warning(f"Msm_12_2: Поле подписи '{label_field}' не найдено в слое. Доступные поля: {', '.join(field_names)}")
                settings.enabled = False
                return settings

            # Устанавливаем поле подписи
            settings.fieldName = label_field if label_field else ''
            settings.isExpression = config.get('label_is_expression', False)

            # Базовые настройки
            settings.enabled = True
            settings.drawLabels = True

            # Текст и шрифт
            text_format = self._build_text_format(config)
            settings.setFormat(text_format)
        else:
            # Подписей нет, проверяем нужно ли препятствие
            is_obstacle = config.get('label_is_obstacle', False)
            if is_obstacle:
                # Для obstacle нужно включить labeling, но не рисовать подписи
                settings.enabled = True
                settings.drawLabels = False

                # ВАЖНО: QGIS требует fieldName даже для obstacle-only
                # Используем первое попавшееся поле из слоя
                field_names = [field.name() for field in layer.fields()]
                if field_names:
                    settings.fieldName = field_names[0]
            else:
                settings.enabled = False
                settings.drawLabels = False

        # Размещение подписей (константы, одинаковы для всех слоёв)
        # ВАЖНО: Проверяем автопозиционирование ДО настройки placement
        has_auto_position = config.get('label_position_auto', False)
        self._configure_placement(settings, layer, has_auto_position)

        # Форматирование текста (константы)
        self._configure_formatting(settings, config)

        # Масштаб-зависимая видимость (опционально)
        self._configure_scale_visibility(settings, config)

        # Выноски (callout) — линии от подписи к объекту (опционально)
        self._configure_callout(settings, layer, config)

        # Data-defined координаты для позиционирования (опционально)
        # Передаём full_name для определения порядка слоя
        full_name = config.get('full_name', '')
        self._configure_position_override(settings, config, full_name, layer)

        # Отключаем поворот надписей - всегда горизонтальные
        settings.angleOffset = 0
        settings.preserveRotation = False

        return settings

    def _build_text_format(self, config: dict) -> QgsTextFormat:
        """
        Построить QgsTextFormat из конфигурации

        Args:
            config: Конфигурация подписей

        Returns:
            Настроенный QgsTextFormat
        """
        text_format = QgsTextFormat()

        # 1. Шрифт
        font_family = config.get('label_font_family', 'GOST 2.304')
        font = QFont(font_family)

        font_style = config.get('label_font_style', 'Bold Italic')
        if 'Bold' in font_style:
            font.setBold(True)
        if 'Italic' in font_style:
            font.setItalic(True)

        text_format.setFont(font)

        # 2. Размер шрифта
        font_size = config.get('label_font_size', 4.0)
        text_format.setSize(font_size)
        text_format.setSizeUnit(Qgis.RenderUnit.Millimeters)

        # 3. Цвет текста
        color_rgb = config.get('label_font_color_RGB', '0,0,0')
        r, g, b = map(int, color_rgb.split(','))
        text_format.setColor(QColor(r, g, b))

        # Прозрачность текста (0-100 -> 0.0-1.0)
        opacity = config.get('label_font_opacity', 100)
        text_format.setOpacity(opacity / 100.0)

        # 4. Буфер
        if config.get('label_buffer_enabled', True):
            buffer = self._build_buffer_settings(config)
            text_format.setBuffer(buffer)

        return text_format

    def _build_buffer_settings(self, config: dict) -> QgsTextBufferSettings:
        """
        Построить QgsTextBufferSettings из конфигурации

        Args:
            config: Конфигурация подписей

        Returns:
            Настроенный QgsTextBufferSettings
        """
        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)

        # Размер буфера
        buffer_size = config.get('label_buffer_size', 1.0)
        buffer.setSize(buffer_size)
        buffer.setSizeUnit(Qgis.RenderUnit.Millimeters)

        # Цвет буфера
        buffer_color = config.get('label_buffer_color_RGB', '255,255,255')
        br, bg, bb = map(int, buffer_color.split(','))
        buffer.setColor(QColor(br, bg, bb))

        # Прозрачность буфера
        buffer_opacity = config.get('label_buffer_opacity', 100)
        buffer.setOpacity(buffer_opacity / 100.0)

        # Заполнять внутренность буфера (не только контур)
        buffer.setFillBufferInterior(True)

        return buffer

    def _configure_placement(self, settings: QgsPalLayerSettings,
                           layer: QgsVectorLayer, has_auto_position: bool = False) -> None:
        """
        Настроить размещение подписей

        Args:
            settings: Настройки подписей
            layer: Векторный слой
            has_auto_position: Если True, используется OffsetFromPoint для data-defined координат
        """
        geometry_type = layer.geometryType()

        if geometry_type == Qgis.GeometryType.Polygon:
            if has_auto_position:
                # Для автопозиционирования: используем OrderedPositionsAroundPoint
                # Этот режим поддерживает data-defined PositionX/PositionY для абсолютных координат
                settings.placement = Qgis.LabelPlacement.OrderedPositionsAroundPoint
            else:
                # Для обычных полигонов: вокруг центроида
                # QGIS 3.40 LTR: используем AroundPoint для размещения вокруг центроида
                settings.placement = Qgis.LabelPlacement.AroundPoint

                # Центроид видимой части (не всего полигона)
                settings.centroidInside = True
                settings.centroidWhole = False

                settings.fitInPolygonOnly = False

        elif geometry_type == Qgis.GeometryType.Line:
            # Для линий: вдоль линии
            settings.placement = Qgis.LabelPlacement.Curved

        elif geometry_type == Qgis.GeometryType.Point:
            # Для точек: вокруг точки
            settings.placement = Qgis.LabelPlacement.AroundPoint

        # Переворачивать подписи если они вверх ногами
        settings.upsidedownLabels = Qgis.UpsideDownLabelHandling.FlipUpsideDownLabels

    def _configure_formatting(self, settings: QgsPalLayerSettings,
                             config: dict) -> None:
        """
        Настроить форматирование текста

        Args:
            settings: Настройки подписей
            config: Конфигурация подписей
        """
        # Автоматический перенос строк
        if config.get('label_auto_wrap_enabled', True):
            wrap_length = config.get('label_auto_wrap_length', 50)
            settings.autoWrapLength = wrap_length

        # Выравнивание многострочного текста
        settings.multilineAlign = Qgis.LabelMultiLineAlignment.Center

        # Расстояние от объекта (мм)
        distance = config.get('label_distance_from_feature', 0.0)
        if distance > 0:
            settings.dist = distance
            settings.distUnits = Qgis.RenderUnit.Millimeters

    def _configure_scale_visibility(self, settings: QgsPalLayerSettings,
                                   config: dict) -> None:
        """
        Настроить масштаб-зависимую видимость подписей

        Args:
            settings: Настройки подписей
            config: Конфигурация подписей
        """
        min_scale = config.get('label_min_scale')
        max_scale = config.get('label_max_scale')

        # Проверка на пустые значения и "-" (означает "не задано")
        if min_scale in (None, '', '-'):
            min_scale = None
        if max_scale in (None, '', '-'):
            max_scale = None

        if min_scale is not None or max_scale is not None:
            settings.scaleVisibility = True

            if min_scale is not None:
                try:
                    settings.minimumScale = float(min_scale)
                except (ValueError, TypeError):
                    log_warning(f"Msm_12_2: Некорректное значение label_min_scale: {min_scale}, использую значение по умолчанию")

            if max_scale is not None:
                try:
                    settings.maximumScale = float(max_scale)
                except (ValueError, TypeError):
                    pass
        else:
            settings.scaleVisibility = False

    def _configure_position_override(self, settings: QgsPalLayerSettings,
                                     config: dict, full_name: str,
                                     layer: QgsVectorLayer = None) -> None:
        """
        Настроить автоматическое позиционирование подписей по углам макета

        Если label_position_auto=1, распределяет подписи по 4 углам циклически:
        - Получает все слои с label_position_auto=1
        - Сортирует по order_layers из Base_layers.json
        - Определяет угол: top_left, top_right, bottom_left, bottom_right
        - Применяет выражения из Base_expressions.json

        Args:
            settings: Настройки подписей
            config: Конфигурация подписей
            full_name: Полное имя слоя (например "L_1_2_3_1_АТД_РФ")

        Example:
            config = {'label_position_auto': True, 'full_name': 'L_1_2_3_1_АТД_РФ'}
            # Подпись автоматически размещается в одном из 4 углов
        """
        # Проверяем флаг автоматического позиционирования
        if not config.get('label_position_auto', False):
            return

        # Проверяем что все необходимые менеджеры доступны
        if not self.expr_manager or not self.label_ref_manager or not self.layers_ref_manager:
            return

        try:
            # Проверяем, существует ли слой границ работ (нужен для вычисления координат)
            from qgis.core import QgsProject
            project = QgsProject.instance()
            boundary_layers = project.mapLayersByName(LAYER_BOUNDARIES_EXACT)

            if not boundary_layers:
                return

            boundary_layer = boundary_layers[0]
            if not boundary_layer.isValid() or not isinstance(boundary_layer, QgsVectorLayer):
                return

            if boundary_layer.featureCount() == 0:
                return

            # 1. Получаем все слои с label_position_auto=1 из Base_labels.json
            all_labels = self.label_ref_manager.get_all_labels()
            auto_layers = [
                lbl for lbl in all_labels
                if lbl.get('label_position_auto', False) and lbl.get('full_name')
            ]

            if not auto_layers:
                return

            # 2. Получаем order_layers для каждого слоя из Base_layers.json
            layers_with_order = []
            for lbl in auto_layers:
                layer_name = lbl['full_name']
                layer_info = self.layers_ref_manager.get_layer_by_full_name(layer_name)
                if layer_info:
                    order = layer_info.get('order_layers', 999999)
                    layers_with_order.append((layer_name, order))

            # 3. Сортируем по order_layers (меньше = раньше)
            layers_with_order.sort(key=lambda x: x[1])

            # 4. Находим индекс текущего слоя
            layer_names = [name for name, _ in layers_with_order]
            if full_name not in layer_names:
                return

            layer_index = layer_names.index(full_name)

            # 5. Определяем угол циклически (0=top_left, 1=top_right, 2=bottom_left, 3=bottom_right)
            corners = ['top_left', 'top_right', 'bottom_left', 'bottom_right']
            corner = corners[layer_index % 4]

            # 6. Получаем выражения для этого угла
            expr_x_id = f'coord_{corner}_x'
            expr_y_id = f'coord_{corner}_y'

            expr_x = self.expr_manager.get(expr_x_id)
            expr_y = self.expr_manager.get(expr_y_id)

            if not expr_x or not expr_y:
                return

            # 7. Создаём поля label_x и label_y в слое (если их нет)
            # ВАЖНО: PositionX/PositionY требуют ПОЛЯ, а не выражения!
            from qgis.core import QgsField, QgsPalLayerSettings as PLS, QgsExpression, QgsExpressionContext, QgsExpressionContextUtils
            from qgis.PyQt.QtCore import QMetaType

            # Используем переданный слой напрямую
            current_layer = layer
            if not current_layer:
                return

            # Проверяем и создаём поля
            field_names = [field.name() for field in current_layer.fields()]
            fields_to_add = []

            if 'label_x' not in field_names:
                fields_to_add.append(QgsField('label_x', QMetaType.Type.Double))
            if 'label_y' not in field_names:
                fields_to_add.append(QgsField('label_y', QMetaType.Type.Double))

            if fields_to_add:
                current_layer.startEditing()
                current_layer.dataProvider().addAttributes(fields_to_add)
                current_layer.updateFields()
                current_layer.commitChanges()

            # ========== РАСЧЕТ КООРДИНАТ НАДПИСЕЙ ==========
            # Логика: проверяем угол extent внутри ВИДИМОЙ части геометрии
            # Если угол снаружи → используем центроид видимой части

            # ИСПРАВЛЕНО (2025-10-27): Получаем extent из Print Layout вместо слоя границ
            # Приоритет: layout.referenceMap().extent() → boundary_layer.extent() (fallback)
            extent = self.get_sheet_extent(project, boundary_layer)

            if not extent:
                return

            boundary_crs = boundary_layer.crs().authid()
            current_crs = current_layer.crs().authid()

            # Создаём transform для координат (если СК разные)
            transform = None
            if boundary_crs != current_crs:
                transform = QgsCoordinateTransform(
                    boundary_layer.crs(),
                    current_layer.crs(),
                    project
                )

            extent_geom = QgsGeometry.fromRect(extent)

            if transform:
                extent_geom.transform(transform)

            # ========== СТАРЫЙ КОД - ДО РЕАЛИЗАЦИИ ПРОВЕРКИ ВИДИМОЙ ЧАСТИ (2025-10-26) ==========
            # ОСТАВЛЕНО ДЛЯ СПРАВКИ: старая логика без проверки пересечения
            #
            # if 'left' in corner:
            #     x_coord = extent.xMinimum() + (extent.xMaximum() - extent.xMinimum()) * 0.05
            # else:  # right
            #     x_coord = extent.xMaximum() - (extent.xMaximum() - extent.xMinimum()) * 0.05
            #
            # if 'top' in corner:
            #     y_coord = extent.yMaximum() - (extent.yMaximum() - extent.yMinimum()) * 0.05
            # else:  # bottom
            #     y_coord = extent.yMinimum() + (extent.yMaximum() - extent.yMinimum()) * 0.05
            #
            # log_info(f"Координаты угла {corner} (в СК границ {boundary_crs}): X={x_coord:.2f}, Y={y_coord:.2f}")
            #
            # if boundary_crs != current_crs:
            #     point = QgsPointXY(x_coord, y_coord)
            #     transformed_point = transform.transform(point)
            #     log_info(f"Трансформация координат: ({x_coord:.2f}, {y_coord:.2f}) → ({transformed_point.x():.2f}, {transformed_point.y():.2f})")
            #     x_coord = transformed_point.x()
            #     y_coord = transformed_point.y()
            #
            # log_info(f"ФИНАЛЬНЫЕ координаты для записи (в СК {current_crs}): X={x_coord:.2f}, Y={y_coord:.2f}")
            # ========== КОНЕЦ СТАРОГО КОДА ==========

            # ========== НОВЫЙ КОД - ПРОВЕРКА УГЛА ДЛЯ КАЖДОГО FEATURE (2025-10-26) ==========
            # Заполняем поля для каждого объекта ИНДИВИДУАЛЬНО
            label_x_idx = current_layer.fields().indexOf('label_x')
            label_y_idx = current_layer.fields().indexOf('label_y')

            if label_x_idx < 0 or label_y_idx < 0:
                log_warning("Msm_12_2: Поля label_x/label_y не найдены после создания")
                return

            # Вычисляем базовые координаты угла extent (в СК boundaries)
            # ИСПРАВЛЕНО (2025-10-27): Extent из layout УЖЕ правильный (с выражениями)
            # Углы размещаются РОВНО на границах extent (без дополнительного смещения)
            extent_bounds = extent  # Extent из layout или расширенный boundaries

            if 'left' in corner:
                corner_x_base = extent_bounds.xMinimum()
            else:  # right
                corner_x_base = extent_bounds.xMaximum()

            if 'top' in corner:
                corner_y_base = extent_bounds.yMaximum()
            else:  # bottom
                corner_y_base = extent_bounds.yMinimum()

            # Трансформируем базовую точку угла в СК целевого слоя
            if transform:
                corner_point_base = QgsPointXY(corner_x_base, corner_y_base)
                corner_point_transformed = transform.transform(corner_point_base)
                corner_x = corner_point_transformed.x()
                corner_y = corner_point_transformed.y()
            else:
                corner_x = corner_x_base
                corner_y = corner_y_base

            # Обрабатываем каждый feature отдельно
            current_layer.startEditing()
            processed_count = 0
            corner_used_count = 0
            centroid_used_count = 0

            try:
                for feature in current_layer.getFeatures():
                    feature_geom = feature.geometry()

                    # Проверка валидности геометрии
                    if not feature_geom or not feature_geom.isGeosValid():
                        if not feature_geom:
                            fallback_point = QgsPointXY(0, 0)
                        else:
                            # makeValid() перед GEOS операцией на невалидной геометрии
                            valid_geom = feature_geom.makeValid()
                            if valid_geom and not valid_geom.isEmpty():
                                fallback_point = valid_geom.poleOfInaccessibility(1.0)[0].asPoint()
                            else:
                                fallback_point = feature_geom.centroid().asPoint()

                        # Смещаем центроид в направлении назначенного угла
                        shift_factor = 0.3
                        dx = corner_x - fallback_point.x()
                        dy = corner_y - fallback_point.y()

                        shifted_x = fallback_point.x() + dx * shift_factor
                        shifted_y = fallback_point.y() + dy * shift_factor

                        # Смещённая точка внутри геометрии?
                        if feature_geom:
                            shifted_point_geom = QgsGeometry.fromPointXY(QgsPointXY(shifted_x, shifted_y))
                            if feature_geom.contains(shifted_point_geom):
                                label_x = shifted_x
                                label_y = shifted_y
                            else:
                                label_x = fallback_point.x()
                                label_y = fallback_point.y()
                        else:
                            label_x = shifted_x
                            label_y = shifted_y

                        centroid_used_count += 1
                        current_layer.changeAttributeValue(feature.id(), label_x_idx, label_x)
                        current_layer.changeAttributeValue(feature.id(), label_y_idx, label_y)
                        processed_count += 1
                        continue

                    # Пересечение геометрии feature с extent (видимая часть)
                    visible_part = feature_geom.intersection(extent_geom)

                    # Проверка 1: Пересечение пустое (feature полностью вне extent)
                    if visible_part.isEmpty():
                        fallback_point = feature_geom.poleOfInaccessibility(1.0)[0].asPoint()

                        shift_factor = 0.3
                        dx = corner_x - fallback_point.x()
                        dy = corner_y - fallback_point.y()

                        shifted_x = fallback_point.x() + dx * shift_factor
                        shifted_y = fallback_point.y() + dy * shift_factor

                        shifted_point_geom = QgsGeometry.fromPointXY(QgsPointXY(shifted_x, shifted_y))
                        if feature_geom.contains(shifted_point_geom):
                            label_x = shifted_x
                            label_y = shifted_y
                        else:
                            label_x = fallback_point.x()
                            label_y = fallback_point.y()

                        centroid_used_count += 1
                    else:
                        # Проверка 2: Угол внутри видимой части?
                        corner_geom = QgsGeometry.fromPointXY(QgsPointXY(corner_x, corner_y))

                        if visible_part.contains(corner_geom):
                            label_x = corner_x
                            label_y = corner_y
                            corner_used_count += 1
                        else:
                            # Угол снаружи видимой части -> центроид со смещением к углу
                            visible_centroid = visible_part.poleOfInaccessibility(1.0)[0].asPoint()

                            shift_factor = 0.3
                            dx = corner_x - visible_centroid.x()
                            dy = corner_y - visible_centroid.y()

                            shifted_x = visible_centroid.x() + dx * shift_factor
                            shifted_y = visible_centroid.y() + dy * shift_factor

                            shifted_point_geom = QgsGeometry.fromPointXY(QgsPointXY(shifted_x, shifted_y))

                            if visible_part.contains(shifted_point_geom):
                                label_x = shifted_x
                                label_y = shifted_y
                            else:
                                label_x = visible_centroid.x()
                                label_y = visible_centroid.y()

                            centroid_used_count += 1

                    # Записываем координаты в атрибуты
                    current_layer.changeAttributeValue(feature.id(), label_x_idx, label_x)
                    current_layer.changeAttributeValue(feature.id(), label_y_idx, label_y)
                    processed_count += 1

                current_layer.commitChanges()
            except Exception:
                current_layer.rollBack()
                raise

            # Теперь устанавливаем data-defined свойства на ПОЛЯ, а не выражения
            properties = settings.dataDefinedProperties()
            if not properties:
                properties = QgsPropertyCollection()

            prop_x = QgsProperty.fromField('label_x')
            prop_y = QgsProperty.fromField('label_y')

            properties.setProperty(PLS.Property.PositionX, prop_x)
            properties.setProperty(PLS.Property.PositionY, prop_y)

            settings.setDataDefinedProperties(properties)

        except Exception as e:
            log_warning(f"Msm_12_2: Ошибка автопозиционирования для '{full_name}': {str(e)}")

    @staticmethod
    def _get_map_scale() -> float:
        """
        Получить масштаб карты для расчёта размера подписей

        Приоритеты:
        1. Layout referenceMap scale
        2. Вычисление из boundary layer extent (ряд 1-2-5)

        Returns:
            Знаменатель масштаба (например 2000 для 1:2000), или 0 если не удалось определить
        """
        project = QgsProject.instance()

        # 1. Из Print Layout
        try:
            layouts = project.layoutManager().layouts()
            if layouts:
                ref_map = layouts[0].referenceMap()
                if ref_map and ref_map.scale() > 0:
                    return ref_map.scale()
        except Exception:
            pass

        # 2. Из boundary layer (ряд 1-2-5, как в get_sheet_extent)
        try:
            boundary_layers = project.mapLayersByName(LAYER_BOUNDARIES_EXACT)
            if boundary_layers:
                extent = boundary_layers[0].extent()
                max_dim = max(extent.width(), extent.height())
                raw_scale = max_dim * 5
                if raw_scale > 0:
                    magnitude = math.floor(math.log10(raw_scale))
                    normalized = raw_scale / (10 ** magnitude)
                    if normalized <= 1:
                        return 10 ** magnitude
                    elif normalized <= 2:
                        return 2 * (10 ** magnitude)
                    elif normalized <= 5:
                        return 5 * (10 ** magnitude)
                    else:
                        return 10 ** (magnitude + 1)
        except Exception:
            pass

        return 0

    @staticmethod
    def _estimate_label_fits(geom: QgsGeometry, pole_point: QgsPointXY,
                             pole_radius: float, char_count: int,
                             font_size_mm: float, scale: float) -> tuple:
        """
        Проверить помещается ли текст подписи внутри полигона

        Сравнивает ширину текста (в map units) с радиусом вписанной окружности.
        Если не помещается — вычисляет точку снаружи полигона для выноски.

        Args:
            geom: Геометрия полигона
            pole_point: Точка poleOfInaccessibility
            pole_radius: Радиус вписанной окружности (в map units)
            char_count: Количество символов в тексте подписи
            font_size_mm: Размер шрифта (мм)
            scale: Знаменатель масштаба (например 2000)

        Returns:
            (fits: bool, outside_point: QgsPointXY | None)
        """
        AVG_CHAR_WIDTH_RATIO = 0.5
        MARGIN_FACTOR = 1.2

        text_width_map = char_count * font_size_mm * AVG_CHAR_WIDTH_RATIO / 1000.0 * scale
        half_text = text_width_map / 2.0

        if pole_radius >= half_text * MARGIN_FACTOR:
            return (True, None)

        # Не помещается — вычислить точку снаружи
        try:
            pole_geom = QgsGeometry.fromPointXY(pole_point)
            nearest_geom = geom.nearestPoint(pole_geom)
            if nearest_geom.isEmpty():
                return (False, None)

            boundary_pt = nearest_geom.asPoint()
            dx = boundary_pt.x() - pole_point.x()
            dy = boundary_pt.y() - pole_point.y()
            dist = math.sqrt(dx * dx + dy * dy)

            if dist < 0.001:
                return (False, None)

            # Нормализованное направление наружу
            nx = dx / dist
            ny = dy / dist

            # Смещение за границу на половину ширины текста
            offset = half_text * 0.5
            outside_x = boundary_pt.x() + nx * offset
            outside_y = boundary_pt.y() + ny * offset

            return (False, QgsPointXY(outside_x, outside_y))

        except Exception:
            return (False, None)

    def _ensure_label_coordinates(self, layer: QgsVectorLayer, config: dict) -> None:
        """
        Создать и заполнить поля label_x/label_y для callout expression

        Для слоёв БЕЗ label_position_auto координаты подписи не вычисляются
        автоматически. Этот метод создаёт поля и записывает координаты
        poleOfInaccessibility каждого feature — они используются в expression
        callout для динамического выбора точки привязки подписи.

        Для слоёв С label_position_auto поля уже создаются в _configure_position_override().

        Args:
            layer: Векторный слой QGIS
            config: Конфигурация подписей из Base_labels.json
        """
        if config.get('label_position_auto', False):
            return

        try:
            from qgis.core import QgsField
            from qgis.PyQt.QtCore import QMetaType

            field_names = [f.name() for f in layer.fields()]
            fields_to_add = []

            if 'label_x' not in field_names:
                fields_to_add.append(QgsField('label_x', QMetaType.Type.Double))
            if 'label_y' not in field_names:
                fields_to_add.append(QgsField('label_y', QMetaType.Type.Double))

            if fields_to_add:
                layer.startEditing()
                layer.dataProvider().addAttributes(fields_to_add)
                layer.updateFields()
                layer.commitChanges()

            label_x_idx = layer.fields().indexOf('label_x')
            label_y_idx = layer.fields().indexOf('label_y')

            if label_x_idx < 0 or label_y_idx < 0:
                log_warning("Msm_12_2: Не удалось найти поля label_x/label_y после создания")
                return

            # Проверяем заполнены ли значения (не перезаписываем существующие)
            has_values = False
            for feat in layer.getFeatures():
                has_values = feat.attribute('label_x') is not None
                break

            if has_values:
                return

            # Параметры для проверки "помещается ли подпись"
            label_field = config.get('label_field', '')
            is_expression = config.get('label_is_expression', False)
            font_size_mm = config.get('label_font_size', 4.0)
            callout_enabled = config.get('label_callout_enabled', False)

            # Fit-check только для callout-слоёв с обычным полем (не expression)
            do_fit_check = callout_enabled and label_field and not is_expression
            scale = self._get_map_scale() if do_fit_check else 0

            layer.startEditing()
            try:
                for feature in layer.getFeatures():
                    geom = feature.geometry()
                    if not geom or geom.isEmpty():
                        continue

                    pole = geom.poleOfInaccessibility(1.0)
                    if not pole[0] or pole[0].isEmpty():
                        continue

                    pole_pt = pole[0].asPoint()
                    pole_radius = pole[1]

                    # Проверка: помещается ли текст внутри полигона
                    if do_fit_check and scale > 0:
                        text = feature.attribute(label_field)
                        char_count = len(str(text)) if text else 0

                        if char_count > 0:
                            fits, outside_pt = self._estimate_label_fits(
                                geom, pole_pt, pole_radius,
                                char_count, font_size_mm, scale
                            )
                            if not fits and outside_pt:
                                layer.changeAttributeValue(
                                    feature.id(), label_x_idx, outside_pt.x())
                                layer.changeAttributeValue(
                                    feature.id(), label_y_idx, outside_pt.y())
                                continue

                    # По умолчанию: подпись в poleOfInaccessibility
                    layer.changeAttributeValue(feature.id(), label_x_idx, pole_pt.x())
                    layer.changeAttributeValue(feature.id(), label_y_idx, pole_pt.y())
                layer.commitChanges()
            except Exception:
                layer.rollBack()
                raise

        except Exception as e:
            log_warning(f"Msm_12_2: Ошибка создания label координат: {str(e)}")

    def _configure_callout(self, settings: QgsPalLayerSettings,
                           layer: QgsVectorLayer, config: dict) -> None:
        """
        Настроить выноски (callout lines) от подписи к объекту

        Создаёт выноску в стиле AutoCAD MULTILEADER:
        - Наклонная линия: серая (#666666), 0.15 мм + точка-наконечник у объекта
        - Полочка: HTML underline (настраивается в _configure_callout_shelf)
        - Точка привязки объекта: PoleOfInaccessibility
        - Точка привязки подписи: динамическая (LabelBottomLeft / LabelBottomRight)
        - Минимальная длина: 1 мм (не рисовать когда подпись совпадает с объектом)
        - Отступ от объекта: 0.5 мм (предотвращает слияние с контуром)
        - Логика expression: если объект правее подписи -> BottomRight, иначе BottomLeft

        Args:
            settings: Настройки подписей QgsPalLayerSettings
            layer: Векторный слой QGIS
            config: Конфигурация подписей из Base_labels.json
        """
        if not config.get('label_callout_enabled', False):
            return

        try:
            # 1. Обеспечить наличие label_x/label_y (для expression)
            self._ensure_label_coordinates(layer, config)

            # 2. Создать callout
            callout = QgsSimpleLineCallout()
            callout.setEnabled(True)

            # 3. Стиль линии выноски: тонкая серая линия + точка-наконечник у объекта
            line_symbol = QgsLineSymbol.createSimple({
                'color': '#666666',
                'width': '0.15',
                'width_unit': 'MM'
            })

            # Точка-наконечник на конце линии у объекта (ГОСТ 2.316: точка при пересечении контура)
            dot_marker = QgsSimpleMarkerSymbolLayer(
                Qgis.MarkerShape.Circle, 0.6
            )
            dot_marker.setColor(QColor('#666666'))
            dot_marker.setStrokeColor(QColor('#666666'))
            dot_marker.setSizeUnit(Qgis.RenderUnit.Millimeters)

            marker_symbol = QgsMarkerSymbol()
            marker_symbol.changeSymbolLayer(0, dot_marker)

            marker_line = QgsMarkerLineSymbolLayer(True, 0)
            marker_line.setSubSymbol(marker_symbol)
            marker_line.setPlacements(Qgis.MarkerLinePlacement.LastVertex)

            line_symbol.appendSymbolLayer(marker_line)
            callout.setLineSymbol(line_symbol)

            # 4. Точка привязки объекта: PoleOfInaccessibility
            callout.setAnchorPoint(QgsCallout.PoleOfInaccessibility)

            # 5. Рисовать ко всем частям объекта
            callout.setDrawCalloutToAllParts(
                config.get('label_callout_draw_to_all_parts', True)
            )

            # 6. Минимальная длина выноски (1 мм — не рисовать когда подпись на месте)
            callout.setMinimumLength(1)
            callout.setMinimumLengthUnit(Qgis.RenderUnit.Millimeters)

            # 7. Отступ от объекта (предотвращает слияние линии с контуром)
            callout.setOffsetFromAnchor(0.5)
            callout.setOffsetFromAnchorUnit(Qgis.RenderUnit.Millimeters)

            # 8. Дефолтная точка привязки подписи (переопределяется expression ниже)
            callout.setLabelAnchorPoint(QgsCallout.LabelBottomLeft)

            # 9. Dynamic expression для точки привязки подписи
            # LabelBottomLeft = 7, LabelBottomRight = 9
            # Если центр объекта (pole) правее позиции подписи -> BottomRight (линия от правого края)
            # Если центр объекта левее позиции подписи -> BottomLeft (линия от левого края)
            expr = (
                'CASE WHEN x(pole_of_inaccessibility($geometry, 1)) > "label_x" '
                'THEN 9 ELSE 7 END'
            )
            dd_props = callout.dataDefinedProperties()
            dd_props.setProperty(
                QgsCallout.Property.LabelAnchorPointPosition,
                QgsProperty.fromExpression(expr)
            )
            callout.setDataDefinedProperties(dd_props)

            # 10. Применить callout к settings
            settings.setCallout(callout)

            # 11. Полочка: HTML underline создаёт горизонтальную линию под текстом
            # Визуально стыкуется с callout линией от BottomLeft/BottomRight
            # Результат: наклонная линия (callout) + горизонтальная полочка (underline)
            self._configure_callout_shelf(settings, config)

        except Exception as e:
            log_warning(f"Msm_12_2: Ошибка настройки callout: {str(e)}")

    def _configure_callout_shelf(self, settings: QgsPalLayerSettings,
                                 config: dict) -> None:
        """
        Настроить полочку (горизонтальную линию под текстом подписи)

        Реализация через HTML <u> underline:
        - Оборачивает fieldName в HTML expression с <u>тегом
        - Включает HTML rendering в QgsTextFormat
        - Визуально underline стыкуется с callout линией от BottomLeft/BottomRight
        - Результат: наклонная линия (callout) + горизонтальная полочка (underline)
          аналогично MULTILEADER в AutoCAD

        Args:
            settings: Настройки подписей QgsPalLayerSettings
            config: Конфигурация подписей из Base_labels.json
        """
        current_field = settings.fieldName
        is_expression = settings.isExpression

        if not current_field:
            return

        # Обернуть в HTML underline expression
        if is_expression:
            # Уже expression — оборачиваем результат
            shelf_expr = f"'<u>' || ({current_field}) || '</u>'"
        else:
            # Простое поле — конвертируем в expression
            shelf_expr = f"'<u>' || \"{current_field}\" || '</u>'"

        settings.fieldName = shelf_expr
        settings.isExpression = True

        # Включить HTML rendering
        text_format = settings.format()
        text_format.setAllowHtmlFormatting(True)
        settings.setFormat(text_format)

    def get_defaults(self) -> dict:
        """
        Получить значения по умолчанию для всех параметров

        Returns:
            Словарь со стандартными значениями
        """
        return {
            'label_font_family': 'GOST 2.304',
            'label_font_style': 'Bold Italic',
            'label_font_size': 4.0,
            'label_font_color_RGB': '0,0,0',
            'label_font_opacity': 100,
            'label_buffer_enabled': True,
            'label_buffer_size': 1.0,
            'label_buffer_color_RGB': '255,255,255',
            'label_buffer_opacity': 100,
            'label_is_expression': False,
            'label_auto_wrap_enabled': True,
            'label_auto_wrap_length': 50,
            'label_distance_from_feature': 0.0
        }
