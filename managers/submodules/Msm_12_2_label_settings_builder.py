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
    QgsVectorLayer,
    QgsGeometry,
    QgsPointXY,
    QgsRectangle,
    QgsCoordinateTransform,
    QgsProject,
    Qgis,
    QgsUnitTypes,
    QgsPropertyCollection,
    QgsProperty
)
from qgis.PyQt.QtGui import QColor, QFont
import math
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

            # ПРИБЛИЖЕНИЕ: Используем ТУ ЖЕ формулу что и в F_1_4_template.qpt
            # ВРЕМЕННОЕ РЕШЕНИЕ: boundaries ± 5% (как data-defined expressions в template)
            # TODO (2025-10-27): После создания layout в F_1_4, получать extent из layout.referenceMap()
            #
            # Template expressions (строки 843-860):
            # xMin = x_min(@layer_bounds) - (x_max - x_min) * 0.05
            # xMax = x_max(@layer_bounds) + (x_max - x_min) * 0.05
            # yMin = y_min(@layer_bounds) - (y_max - y_min) * 0.05
            # yMax = y_max(@layer_bounds) + (y_max - y_min) * 0.05

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

        # Data-defined координаты для позиционирования (опционально)
        # Передаём full_name для определения порядка слоя
        full_name = config.get('full_name', '')
        self._configure_position_override(settings, config, full_name)

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
        text_format.setSizeUnit(QgsUnitTypes.RenderMillimeters)

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
        buffer.setSizeUnit(QgsUnitTypes.RenderMillimeters)

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
        from qgis.core import QgsWkbTypes

        geometry_type = layer.geometryType()

        if geometry_type == QgsWkbTypes.PolygonGeometry:
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

        elif geometry_type == QgsWkbTypes.LineGeometry:
            # Для линий: вдоль линии
            settings.placement = Qgis.LabelPlacement.Curved

        elif geometry_type == QgsWkbTypes.PointGeometry:
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
            settings.distUnits = QgsUnitTypes.RenderMillimeters

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
                                     config: dict, full_name: str) -> None:
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
            boundary_layers = project.mapLayersByName('L_1_1_1_Границы_работ')

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

            # Получаем слой из проекта
            current_layer = None
            for layer_obj in project.mapLayers().values():
                if layer_obj.name() == full_name:
                    current_layer = layer_obj
                    break

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

            for feature in current_layer.getFeatures():
                feature_geom = feature.geometry()

                # Проверка валидности геометрии
                if not feature_geom or not feature_geom.isGeosValid():
                    # ИСПРАВЛЕНО (2025-10-27): poleOfInaccessibility вместо pointOnSurface
                    # poleOfInaccessibility() возвращает tuple (QgsGeometry, distance), берем [0]
                    fallback_point = feature_geom.poleOfInaccessibility(1.0)[0].asPoint() if feature_geom else QgsPointXY(0, 0)

                    # ИСПРАВЛЕНО (2025-10-27): Смещаем центроид в направлении назначенного угла
                    shift_factor = 0.3  # Смещение на 30% от центроида к углу
                    dx = corner_x - fallback_point.x()
                    dy = corner_y - fallback_point.y()

                    shifted_x = fallback_point.x() + dx * shift_factor
                    shifted_y = fallback_point.y() + dy * shift_factor

                    # КРИТИЧЕСКАЯ ПРОВЕРКА: Смещённая точка внутри геометрии?
                    if feature_geom:
                        shifted_point_geom = QgsGeometry.fromPointXY(QgsPointXY(shifted_x, shifted_y))
                        if feature_geom.contains(shifted_point_geom):
                            label_x = shifted_x
                            label_y = shifted_y
                        else:
                            # Смещение выходит за границы → чистый центроид
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
                    # ИСПРАВЛЕНО (2025-10-27): poleOfInaccessibility вместо pointOnSurface
                    # poleOfInaccessibility() возвращает tuple (QgsGeometry, distance), берем [0]
                    fallback_point = feature_geom.poleOfInaccessibility(1.0)[0].asPoint()

                    # ИСПРАВЛЕНО (2025-10-27): Смещаем центроид в направлении назначенного угла
                    shift_factor = 0.3  # Смещение на 30% от центроида к углу
                    dx = corner_x - fallback_point.x()
                    dy = corner_y - fallback_point.y()

                    shifted_x = fallback_point.x() + dx * shift_factor
                    shifted_y = fallback_point.y() + dy * shift_factor

                    # КРИТИЧЕСКАЯ ПРОВЕРКА: Смещённая точка внутри геометрии?
                    shifted_point_geom = QgsGeometry.fromPointXY(QgsPointXY(shifted_x, shifted_y))
                    if feature_geom.contains(shifted_point_geom):
                        label_x = shifted_x
                        label_y = shifted_y
                    else:
                        # Смещение выходит за границы → чистый центроид
                        label_x = fallback_point.x()
                        label_y = fallback_point.y()

                    centroid_used_count += 1
                else:
                    # Проверка 2: Угол внутри видимой части?
                    corner_geom = QgsGeometry.fromPointXY(QgsPointXY(corner_x, corner_y))

                    if visible_part.contains(corner_geom):
                        # Угол ВНУТРИ видимой части → используем угол
                        label_x = corner_x
                        label_y = corner_y
                        corner_used_count += 1
                    else:
                        # Угол СНАРУЖИ видимой части → используем ЦЕНТРОИД со смещением к углу
                        # ИСПРАВЛЕНО (2025-10-27): poleOfInaccessibility вместо pointOnSurface
                        # poleOfInaccessibility() возвращает tuple (QgsGeometry, distance), берем [0]
                        visible_centroid = visible_part.poleOfInaccessibility(1.0)[0].asPoint()

                        # ИСПРАВЛЕНО (2025-10-27): Смещаем центроид в направлении назначенного угла
                        # Это решает проблему одинаковых координат для полигонов, охватывающих всю территорию
                        shift_factor = 0.3  # Смещение на 30% от центроида к углу

                        # Вычисляем вектор от центроида к углу
                        dx = corner_x - visible_centroid.x()
                        dy = corner_y - visible_centroid.y()

                        # Применяем смещение: центроид + 30% вектора к углу
                        shifted_x = visible_centroid.x() + dx * shift_factor
                        shifted_y = visible_centroid.y() + dy * shift_factor

                        # КРИТИЧЕСКАЯ ПРОВЕРКА (2025-10-27): Смещённая точка внутри visible_part?
                        shifted_point_geom = QgsGeometry.fromPointXY(QgsPointXY(shifted_x, shifted_y))

                        if visible_part.contains(shifted_point_geom):
                            # Смещённая точка ВНУТРИ → используем смещение
                            label_x = shifted_x
                            label_y = shifted_y
                        else:
                            # Смещённая точка СНАРУЖИ → используем чистый центроид
                            label_x = visible_centroid.x()
                            label_y = visible_centroid.y()

                        centroid_used_count += 1

                # Записываем координаты в атрибуты
                current_layer.changeAttributeValue(feature.id(), label_x_idx, label_x)
                current_layer.changeAttributeValue(feature.id(), label_y_idx, label_y)
                processed_count += 1

            current_layer.commitChanges()

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
