# -*- coding: utf-8 -*-
"""
Субмодуль проверки наличия лесных кварталов для бюджета
ВАЖНО: Только проверяет наличие слоя, НЕ загружает его!
Слой должен быть загружен заранее через F_1_2
"""

from qgis.core import QgsProject, QgsVectorLayer
from Daman_QGIS.utils import log_info, log_warning


class ForestLoader:
    """Проверяльщик наличия лесных кварталов (БЕЗ загрузки)"""

    def __init__(self, iface, project_manager, layer_manager):
        """Инициализация проверяльщика"""
        self.iface = iface
        self.project = QgsProject.instance()
        self.project_manager = project_manager
        self.layer_manager = layer_manager

    def check_forest_quarters(self):
        """Проверка наличия лесных кварталов

        Returns:
            bool: True если слой существует и содержит объекты, False если не найден
        """
        # Проверяем существование слоя
        if self._check_existing_layer('L_1_1_3_ФГИС_ЛК_Кварталы'):
            log_info("Fsm_1_3_3: Слой L_1_1_3_ФГИС_ЛК_Кварталы найден")
            return True

        # Если не найден - НЕ загружаем!
        # F_1_3 Бюджет должен только анализировать, а не загружать
        log_warning("Fsm_1_3_3: Слой L_1_1_3_ФГИС_ЛК_Кварталы не найден. Загрузите слой через F_1_2 перед запуском бюджета.")
        return False

    def check_forest_subdivisions(self):
        """Проверка наличия лесоустроительных выделов

        Returns:
            bool: True если слой существует и содержит объекты, False если не найден
        """
        # Проверяем существование слоя
        if self._check_existing_layer('L_1_1_4_ФГИС_ЛК_Выделы'):
            log_info("Fsm_1_3_3: Слой L_1_1_4_ФГИС_ЛК_Выделы найден")
            return True

        # Если не найден - НЕ загружаем!
        log_warning("Fsm_1_3_3: Слой L_1_1_4_ФГИС_ЛК_Выделы не найден. Загрузите слой через F_1_2 перед запуском бюджета.")
        return False

    def _check_existing_layer(self, layer_name: str):
        """Проверка существования лесного слоя (кварталы или выделы)

        Args:
            layer_name: Имя проверяемого слоя

        Returns:
            bool: True если слой существует
        """

        # Проверяем в проекте
        for layer in self.project.mapLayers().values():
            if layer.name() == layer_name:
                return True

        # Проверяем в GeoPackage
        if not self.project_manager or not self.project_manager.project_db:
            return False

        gpkg_path = self.project_manager.project_db.gpkg_path
        if gpkg_path:
            layer = QgsVectorLayer(
                f"{gpkg_path}|layername={layer_name}",
                layer_name,
                "ogr"
            )

            if layer.isValid():
                # Добавляем через layer_manager
                if self.layer_manager:
                    layer.setName(layer_name)
                    self.layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
                else:
                    self.project.addMapLayer(layer)
                return True

        return False
