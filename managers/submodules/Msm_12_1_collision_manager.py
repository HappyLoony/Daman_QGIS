# -*- coding: utf-8 -*-
"""
Менеджер управления коллизиями и приоритетами подписей слоёв

Отвечает за:
- Настройку приоритетов подписей
- Управление препятствиями (obstacles)
- Настройку Z-Index (порядок отрисовки)
- Конфигурацию глобального движка подписей QGIS
"""

from qgis.core import (
    QgsProject,
    QgsPalLayerSettings,
    QgsLabelObstacleSettings,
    QgsLabelingEngineSettings,
    QgsPropertyCollection,
    QgsProperty,
    Qgis
)
from Daman_QGIS.utils import log_error


class CollisionManager:
    """Управление коллизиями и приоритетами подписей"""

    def apply_collision_rules(self, settings: QgsPalLayerSettings,
                              config: dict) -> QgsPalLayerSettings:
        """
        Применить правила коллизий к настройкам подписей

        Args:
            settings: Настройки подписей QGIS
            config: Конфигурация из Base_labels.json

        Returns:
            Обновлённые настройки подписей

        Example:
            >>> settings = QgsPalLayerSettings()
            >>> config = {'label_priority': 10, 'label_is_obstacle': False}
            >>> settings = collision_manager.apply_collision_rules(settings, config)
        """
        # 1. Приоритет подписей (0-10, где 10=максимальный)
        if 'label_priority' in config:
            properties = settings.dataDefinedProperties()
            if not properties:
                properties = QgsPropertyCollection()

            properties.setProperty(
                QgsPalLayerSettings.Priority,
                QgsProperty.fromValue(config['label_priority'])
            )
            settings.setDataDefinedProperties(properties)

        # 2. Z-Index (порядок отрисовки, выше = рисуется позже)
        if 'label_z_index' in config:
            settings.zIndex = config['label_z_index']

        # 3. Препятствия (ГЕОМЕТРИЯ слоя блокирует размещение подписей других слоёв)
        obstacle = QgsLabelObstacleSettings()
        obstacle.setIsObstacle(True)

        if config.get('label_is_obstacle', False):
            # Сильное препятствие - максимальная блокировка всего полигона
            obstacle.setFactor(2.0)
            obstacle.setType(QgsLabelObstacleSettings.PolygonInterior)
        else:
            # Слабое препятствие - минимальная блокировка только границ
            obstacle.setFactor(0.1)
            obstacle.setType(QgsLabelObstacleSettings.PolygonBoundary)

        settings.setObstacleSettings(obstacle)

        return settings

    def configure_global_engine(self, iface=None) -> bool:
        """
        Настроить глобальный движок подписей QGIS

        ВАЖНО: Вызывается ОДИН РАЗ при загрузке проекта!
        Эти настройки влияют на ВСЕ подписи в проекте.

        Args:
            iface: Интерфейс QGIS (опционально, не используется сейчас)

        Returns:
            True если настройки успешно применены

        Example:
            >>> collision_manager = CollisionManager()
            >>> collision_manager.configure_global_engine(iface)
        """
        try:
            project = QgsProject.instance()
            engine_settings = QgsLabelingEngineSettings()

            # 1. Улучшенный алгоритм размещения (Version2)
            if hasattr(Qgis, 'LabelPlacementEngineVersion'):
                engine_settings.setPlacementVersion(
                    Qgis.LabelPlacementEngineVersion.Version2
                )

            # 2. Оптимизация размещения
            # Не использовать частичные кандидаты (лучше пропустить чем показать плохо)
            engine_settings.setFlag(
                QgsLabelingEngineSettings.UsePartialCandidates,
                False
            )

            # Не показывать неразмещённые подписи (иначе будут накладываться)
            engine_settings.setFlag(
                QgsLabelingEngineSettings.DrawUnplacedLabels,
                False
            )

            # 3. Увеличиваем количество кандидатов для лучшего размещения
            engine_settings.setMaximumLineCandidatesPerCm(8.0)
            engine_settings.setMaximumPolygonCandidatesPerCmSquared(7.0)

            # Применяем к проекту
            project.setLabelingEngineSettings(engine_settings)
            return True

        except Exception as e:
            log_error(f"Msm_12_1: Ошибка настройки движка коллизий: {str(e)}")
            return False

    def get_collision_info(self, settings: QgsPalLayerSettings) -> dict:
        """
        Получить информацию о настройках коллизий слоя

        Args:
            settings: Настройки подписей

        Returns:
            Словарь с информацией о коллизиях

        Example:
            >>> info = collision_manager.get_collision_info(settings)
            >>> print(f"Приоритет: {info['priority']}")
            >>> print(f"Препятствие: {info['is_obstacle']}")
        """
        # Получаем приоритет
        priority = None
        properties = settings.dataDefinedProperties()
        if properties:
            priority_prop = properties.property(QgsPalLayerSettings.Priority)
            if priority_prop and priority_prop.isActive():
                priority = priority_prop.staticValue()

        # Получаем настройки препятствий
        obstacle_settings = settings.obstacleSettings()
        is_obstacle = obstacle_settings.isObstacle() if obstacle_settings else False
        obstacle_factor = obstacle_settings.factor() if obstacle_settings else 1.0

        return {
            'priority': priority,
            'z_index': settings.zIndex,
            'is_obstacle': is_obstacle,
            'obstacle_factor': obstacle_factor
        }
