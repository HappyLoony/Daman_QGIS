# -*- coding: utf-8 -*-
"""
Msm_31_3_MaskExpressions - QGIS Expression функции для маски.

Регистрирует функции:
- $mask_geometry - возвращает геометрию маски
- in_mask(srid) - проверяет, находится ли feature внутри маски

Используется для фильтрации подписей через Data-defined Show property.
"""

from typing import Optional, TYPE_CHECKING

from qgis.core import (
    QgsExpression,
    QgsExpressionFunction,
    QgsGeometry,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsWkbTypes,
    QgsPointXY,
    QgsRectangle,
)

from Daman_QGIS.utils import log_info, log_error, log_warning

if TYPE_CHECKING:
    from Daman_QGIS.managers.M_31_mask_manager import MaskManager


class MaskGeometryFunction(QgsExpressionFunction):
    """
    Expression функция $mask_geometry.

    Возвращает текущую геометрию маски.

    Использование в Expression Builder:
        $mask_geometry

    Возвращает:
        QgsGeometry маски или NULL если маска не активна
    """

    def __init__(self, mask_manager: 'MaskManager'):
        """
        Инициализация функции.

        Args:
            mask_manager: Ссылка на MaskManager для получения геометрии
        """
        super().__init__(
            "$mask_geometry",
            0,  # Количество аргументов
            "Daman_QGIS",  # Группа в Expression Builder
            self._get_help_text()
        )
        self._mask_manager = mask_manager

    @staticmethod
    def _get_help_text() -> str:
        """Текст справки для Expression Builder."""
        return """<h1>$mask_geometry</h1>
<p>Возвращает геометрию маски Daman_QGIS.</p>

<h2>Возвращаемое значение</h2>
<p>Геометрия маски (QgsGeometry) или NULL если маска не активна.</p>

<h2>Пример использования</h2>
<pre>
-- Проверка пересечения с маской
intersects($geometry, $mask_geometry)

-- Площадь пересечения с маской
area(intersection($geometry, $mask_geometry))
</pre>
"""

    def func(self, values, context, parent, node):
        """
        Вызывается при вычислении выражения.

        Returns:
            QgsGeometry маски или None
        """
        return self._mask_manager.get_mask_geometry()


class InMaskFunction(QgsExpressionFunction):
    """
    Expression функция in_mask(srid).

    Проверяет, пересекает ли текущий feature геометрию маски.
    Используется для фильтрации подписей.

    Использование в Expression Builder:
        in_mask(2154)  -- где 2154 это EPSG код слоя

    Возвращает:
        true/false
    """

    def __init__(self, mask_manager: 'MaskManager'):
        """
        Инициализация функции.

        Args:
            mask_manager: Ссылка на MaskManager для получения геометрии
        """
        super().__init__(
            "in_mask",
            1,  # Один аргумент - SRID
            "Daman_QGIS",  # Группа в Expression Builder
            self._get_help_text()
        )
        self._mask_manager = mask_manager

    @staticmethod
    def _get_help_text() -> str:
        """Текст справки для Expression Builder."""
        return """<h1>in_mask</h1>
<p>Проверяет, находится ли объект внутри маски Daman_QGIS.</p>

<h2>Синтаксис</h2>
<pre>in_mask(srid)</pre>

<h2>Аргументы</h2>
<ul>
<li><b>srid</b> - EPSG код системы координат слоя (например 2154, 32637)</li>
</ul>

<h2>Возвращаемое значение</h2>
<p>true если объект внутри или пересекает маску, false в противном случае.</p>
<p>Если маска не активна, всегда возвращает true.</p>

<h2>Пример использования</h2>
<pre>
-- В настройках подписей (Data-defined Show)
in_mask(layer_property(@layer, 'srid'))

-- С явным указанием SRID
in_mask(32637)
</pre>
"""

    def func(self, values, context, parent, node):  # type: ignore[override]
        """
        Вызывается для каждого объекта при вычислении выражения.

        Args:
            values: Список аргументов [srid]
            context: QgsExpressionContext с текущим feature
            parent: Родительский узел выражения
            node: Текущий узел выражения

        Returns:
            bool: True если объект внутри маски
        """
        feature = context.feature()
        # values - это list аргументов от QgsExpression
        srid = list(values)[0] if values else None
        return self._check_in_mask(feature, srid)

    def _check_in_mask(self, feature, srid) -> bool:
        """
        Проверка пересечения feature с маской.

        Реализация основана на AEAG Mask plugin с оптимизациями:
        - Проверка видимости слоя маски
        - Проверка валидности геометрии
        - BBox оптимизация перед пространственной проверкой

        Args:
            feature: QgsFeature для проверки
            srid: SRID слоя объекта (для трансформации)

        Returns:
            True если объект внутри маски
        """
        # Нет feature - не показываем
        if feature is None:
            return False

        mask_layer = self._mask_manager.get_mask_layer()

        # Нет слоя маски - показываем всё
        if mask_layer is None:
            return True

        # Слой маски пустой - показываем всё
        if mask_layer.featureCount() == 0:
            return True

        # Слой маски не видим - показываем всё (как в оригинале AEAG)
        layer_tree_root = QgsProject.instance().layerTreeRoot()
        layer_tree_layer = layer_tree_root.findLayer(mask_layer.id())
        if layer_tree_layer is not None and not layer_tree_layer.isVisible():
            return True

        # Получаем геометрию маски
        mask_geom = self._mask_manager.get_mask_geometry()

        # Нет маски или пустая - показываем всё
        if mask_geom is None or mask_geom.isEmpty():
            return True

        # Получаем геометрию feature
        geom = feature.geometry()
        if geom is None or geom.isEmpty():
            return False

        # Копируем геометрию для модификаций
        geom = QgsGeometry(geom)

        # Проверка и исправление валидности геометрии (как в оригинале AEAG)
        if not geom.isGeosValid():
            geom = geom.buffer(0.0, 1)

        # Трансформация CRS если нужно
        if srid:
            mask_srid = mask_layer.crs().postgisSrid()
            if mask_srid != srid:
                geom = self._transform_geometry(geom, srid, mask_layer.crs())
                if geom is None:
                    return False

        # Получаем BBox маски для оптимизации
        mask_bbox = mask_geom.boundingBox()

        # Пространственная проверка по типу геометрии
        return self._spatial_check(mask_geom, mask_bbox, geom)

    def _transform_geometry(
        self,
        geom: QgsGeometry,
        src_srid: int,
        dest_crs: QgsCoordinateReferenceSystem
    ) -> Optional[QgsGeometry]:
        """
        Трансформировать геометрию в CRS маски.

        Args:
            geom: Исходная геометрия
            src_srid: SRID исходной CRS
            dest_crs: Целевая CRS (маски)

        Returns:
            Трансформированная геометрия или None при ошибке
        """
        try:
            src_crs = QgsCoordinateReferenceSystem(src_srid)
            xform = QgsCoordinateTransform(src_crs, dest_crs, QgsProject.instance())

            geom_copy = QgsGeometry(geom)
            geom_copy.transform(xform)

            return geom_copy

        except Exception:
            # Ошибка трансформации - возвращаем None
            return None

    def _spatial_check(
        self,
        mask_geom: QgsGeometry,
        mask_bbox: QgsRectangle,
        feature_geom: QgsGeometry
    ) -> bool:
        """
        Пространственная проверка по типу геометрии.

        Использует оптимальный метод в зависимости от типа:
        - Полигоны: BBox + pointOnSurface (баланс точности и скорости)
        - Линии: intersects
        - Точки: intersects

        BBox оптимизация (как в AEAG Mask):
        Сначала проверяем первую точку геометрии по BBox маски.
        Это быстрая проверка для отсечения объектов явно вне маски.

        Args:
            mask_geom: Геометрия маски
            mask_bbox: BBox маски (для оптимизации)
            feature_geom: Геометрия объекта

        Returns:
            True если объект внутри/пересекает маску
        """
        geom_type = feature_geom.type()

        if geom_type == QgsWkbTypes.GeometryType.PolygonGeometry:
            # BBox оптимизация: быстрая проверка первой точки
            first_vertex = feature_geom.vertexAt(0)
            if not mask_bbox.contains(QgsPointXY(first_vertex)):
                return False

            # Для полигонов - проверка pointOnSurface
            # Это оптимальный баланс между точностью и скоростью
            point_on_surface = feature_geom.pointOnSurface()
            if point_on_surface is None or point_on_surface.isEmpty():
                # Fallback на centroid
                return mask_geom.contains(feature_geom.centroid())
            return mask_geom.contains(point_on_surface)

        elif geom_type == QgsWkbTypes.GeometryType.LineGeometry:
            # Для линий - intersects (пересечение любой частью)
            return mask_geom.intersects(feature_geom)

        elif geom_type == QgsWkbTypes.GeometryType.PointGeometry:
            # Для точек - intersects
            return mask_geom.intersects(feature_geom)

        # Неизвестный тип - не показываем
        return False


class MaskExpressionManager:
    """
    Менеджер expression функций маски.

    Отвечает за регистрацию и удаление функций $mask_geometry и in_mask.
    """

    def __init__(self, mask_manager: 'MaskManager'):
        """
        Инициализация менеджера.

        Args:
            mask_manager: Ссылка на MaskManager
        """
        self._mask_manager = mask_manager
        self._mask_geometry_func: Optional[MaskGeometryFunction] = None
        self._in_mask_func: Optional[InMaskFunction] = None
        self._registered: bool = False

    def register(self) -> bool:
        """
        Зарегистрировать expression функции.

        Функции становятся доступны в Expression Builder и
        могут использоваться в выражениях слоёв.

        Returns:
            True если функции зарегистрированы
        """
        if self._registered:
            log_warning("Msm_31_3: Expression функции уже зарегистрированы")
            return True

        try:
            # Создаём функции
            self._mask_geometry_func = MaskGeometryFunction(self._mask_manager)
            self._in_mask_func = InMaskFunction(self._mask_manager)

            # Регистрируем в QGIS
            QgsExpression.registerFunction(self._mask_geometry_func)
            QgsExpression.registerFunction(self._in_mask_func)

            self._registered = True
            log_info("Msm_31_3: Expression функции зарегистрированы ($mask_geometry, in_mask)")
            return True

        except Exception as e:
            log_error(f"Msm_31_3: Ошибка регистрации expression функций: {e}")
            return False

    def unregister(self) -> None:
        """
        Отменить регистрацию expression функций.

        Вызывается при выгрузке плагина или отключении маски.
        """
        if not self._registered:
            return

        try:
            QgsExpression.unregisterFunction("$mask_geometry")
            QgsExpression.unregisterFunction("in_mask")

            self._mask_geometry_func = None
            self._in_mask_func = None
            self._registered = False

            log_info("Msm_31_3: Expression функции удалены")

        except Exception as e:
            log_error(f"Msm_31_3: Ошибка удаления expression функций: {e}")

    def is_registered(self) -> bool:
        """
        Проверить, зарегистрированы ли функции.

        Returns:
            True если функции зарегистрированы
        """
        return self._registered
