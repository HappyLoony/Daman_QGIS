# -*- coding: utf-8 -*-
"""
Fsm_2_4_8_Geocoder - Адрес контура по точке привязки

НАЗНАЧЕНИЕ:
    Определяет адрес местоположения по точке внутри полигона (M_9) через
    обратное геокодирование M_39 DaData.

ОСОБЕННОСТИ:
    - Точка берётся ВНУТРИ полигона, не центроид.
    - Геокодер не настроен, точка не получена либо адрес не найден -> "ЗАПОЛНИ!".

ИСПОЛЬЗОВАНИЕ:
    Вызывается при формировании данных 2 этапа для объединённого контура.
"""

from qgis.core import (
    QgsGeometry, QgsProject, QgsPointXY,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem
)

from Daman_QGIS.managers import registry
from Daman_QGIS.managers.processing.submodules.Msm_13_2_attribute_processor import (
    AttributeProcessor,
)
from Daman_QGIS.utils import log_error, log_warning

# Радиус поиска адреса вокруг точки привязки контура
GEOCODE_RADIUS_METERS = 500


class Fsm_2_4_8_Geocoder:
    """Определение адреса контура через M_39"""

    def geocode_address(
        self, geom: QgsGeometry, crs: QgsCoordinateReferenceSystem
    ) -> str:
        """Определение адреса по точке привязки (M_9) геометрии через M_39 DaData.

        Каждая причина неудачи логируется отдельно: сентинел в поле адреса
        одинаков для всех пяти исходов, и без записи в лог непонятно, что
        именно чинить — настройку геокодера, геометрию контура или сеть.
        Пятый исход — сервис ответил, но качество геокодирования (qc_geo 5)
        адреса не даёт.

        Returns:
            str: адрес либо сентинел «требуется ручное заполнение»
        """
        placeholder = AttributeProcessor.FILLME_PLACEHOLDER

        geocoder = registry.get('M_39')
        if not geocoder or not geocoder.is_configured():
            log_warning(
                "Fsm_2_4_8: геокодер M_39 не настроен, адрес требует ручного заполнения"
            )
            return placeholder

        try:
            # Точка ВНУТРИ полигона (M_9); None = нет валидной геометрии.
            from Daman_QGIS.managers.geometry import AnchorPointManager
            point = AnchorPointManager.anchor_point(geom, "surface")
            if point is None:
                log_warning("Fsm_2_4_8: точка привязки не получена, геокодирование пропущено")
                return placeholder

            transform = QgsCoordinateTransform(
                crs, QgsCoordinateReferenceSystem("EPSG:4326"),
                QgsProject.instance()
            )
            if not transform.isValid():
                log_error(
                    f"Fsm_2_4_8: трансформация {crs.authid()} в EPSG:4326 невалидна — "
                    f"координаты в сервис не отправлены"
                )
                return placeholder

            wgs84_point = transform.transform(QgsPointXY(point.x(), point.y()))

            result = geocoder.geolocate(
                lat=wgs84_point.y(), lon=wgs84_point.x(),
                radius_meters=GEOCODE_RADIUS_METERS
            )
            if result:
                address = geocoder.format_address_by_quality(result)
                # Пятый исход: сервис ответил, но качество геокодирования не даёт
                # адреса (контур в поле, лесном массиве) — format_address_by_quality
                # возвращает прочерк. В поле адреса нужен сентинел ручного
                # заполнения, а не прочерк, неотличимый от «сведений нет».
                if not address or str(address).strip() == '-':
                    qc_geo = result.get('data', {}).get('qc_geo')
                    log_warning(
                        f"Fsm_2_4_8: адрес не определён (qc_geo={qc_geo}), "
                        f"поле помечено для ручного заполнения"
                    )
                    return placeholder
                return address

            log_warning(
                f"Fsm_2_4_8: адрес не найден в радиусе {GEOCODE_RADIUS_METERS} м "
                f"от точки привязки контура"
            )
        except Exception as e:
            log_warning(f"Fsm_2_4_8: Ошибка геокодирования: {e}")

        return placeholder
