# -*- coding: utf-8 -*-
"""
Главный менеджер подписей слоёв QGIS

Единая точка входа для:
- Применения настроек подписей к слоям из Base_labels.json
- Управления коллизиями и приоритетами
- Настройки глобального движка подписей QGIS

Архитектура:
- LabelManager - фасад (главный интерфейс)
- LabelSettingsBuilder - построение QgsPalLayerSettings из БД
- CollisionManager - управление коллизиями
- LabelReferenceManager - доступ к данным Base_labels.json
"""

import os
from typing import Optional
from qgis.core import (
    QgsVectorLayer,
    QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling
)
from Daman_QGIS.managers.submodules.Msm_12_2_label_settings_builder import LabelSettingsBuilder
from Daman_QGIS.managers.submodules.Msm_12_1_collision_manager import CollisionManager
from Daman_QGIS.managers.submodules.Msm_4_15_label_reference_manager import LabelReferenceManager
from Daman_QGIS.managers.M_7_expression_manager import ExpressionManager
from Daman_QGIS.utils import log_info, log_warning, log_error


class LabelManager:
    """
    Главный менеджер подписей слоёв

    Использование:
        >>> label_manager = LabelManager()
        >>> label_manager.configure_global_engine(iface)  # ОДИН РАЗ при загрузке проекта
        >>> label_manager.apply_labels(layer, "L_1_2_1_WFS_ЗУ")  # Для каждого слоя
    """

    def __init__(self):
        """Инициализация менеджера подписей"""
        # Инициализируем ExpressionManager для data-defined свойств
        self.expr_manager = ExpressionManager()

        # Инициализируем reference managers
        self.ref_manager = LabelReferenceManager()

        # Получаем доступ к layer reference manager для метаданных слоёв
        from Daman_QGIS.managers.M_4_reference_manager import get_reference_managers
        self.all_ref_managers = get_reference_managers()

        # Получаем layers_manager из all_ref_managers (NamedTuple)
        layers_ref_manager = self.all_ref_managers.layer

        # Передаём все необходимые менеджеры в settings builder
        self.settings_builder = LabelSettingsBuilder(
            expr_manager=self.expr_manager,
            label_ref_manager=self.ref_manager,
            layers_ref_manager=layers_ref_manager
        )
        self.collision_manager = CollisionManager()

        # Счётчики для итоговой статистики
        self._applied_count = 0
        self._obstacle_count = 0
        self._skipped_count = 0
        self._error_count = 0

    def apply_labels(self, layer: QgsVectorLayer, full_name: str) -> bool:
        """
        Применить настройки подписей к слою из Base_labels.json

        Алгоритм:
        1. Получить конфигурацию из Base_labels.json
        2. Проверить что подписи включены (есть label_field)
        3. Построить QgsPalLayerSettings через LabelSettingsBuilder
        4. Применить правила коллизий через CollisionManager
        5. Применить к слою

        Args:
            layer: Векторный слой QGIS
            full_name: Полное имя слоя (например "L_1_2_1_WFS_ЗУ")

        Returns:
            True если подписи успешно применены, False если отключены или ошибка

        Example:
            >>> layer_manager = LabelManager()
            >>> success = layer_manager.apply_labels(layer, "L_1_2_1_WFS_ЗУ")
            >>> if success:
            >>>     print("Подписи применены")
        """
        try:
            # 0. Проверка валидности слоя
            if not layer or not layer.isValid():
                log_warning(f"M_12: Слой невалиден: {full_name}")
                self._error_count += 1
                return False

            # 1. Получаем конфигурацию из БД
            label_config = self.ref_manager.get_label_config(full_name)

            if not label_config:
                self._skipped_count += 1
                return False

            # 2. Проверяем что есть поле для подписи
            label_field = label_config.get('label_field')
            has_labels = label_field and label_field != '-'

            # Если подписей нет, проверяем нужно ли установить препятствие
            if not has_labels:
                is_obstacle = label_config.get('label_is_obstacle', False)
                if not is_obstacle:
                    self._skipped_count += 1
                    return False
                else:
                    label_field = None

            # 2.5. Проверяем что поле существует в слое (только если есть подписи)
            if has_labels:
                field_names = [field.name() for field in layer.fields()]
                if label_field not in field_names:
                    log_warning(f"M_12: Поле '{label_field}' не найдено в слое {full_name}")
                    self._error_count += 1
                    return False

            # 3. Дополняем конфигурацию значениями по умолчанию
            defaults = self.ref_manager.get_default_config()
            full_config = {**defaults, **label_config}

            # 4. Строим настройки подписей
            settings = self.settings_builder.build(layer, full_config)

            # Проверяем что настройки активны
            if not settings.enabled:
                self._skipped_count += 1
                return False

            # 5. Применяем правила коллизий (включая label_is_obstacle)
            settings = self.collision_manager.apply_collision_rules(settings, full_config)

            # 6. Применяем к слою
            layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
            layer.setLabelsEnabled(settings.enabled)
            layer.triggerRepaint()

            # Обновляем счётчики
            if has_labels:
                self._applied_count += 1
            else:
                self._obstacle_count += 1

            return True

        except Exception as e:
            log_error(f"M_12: Ошибка подписей {full_name}: {str(e)}")
            self._error_count += 1
            return False

    def configure_global_engine(self, iface=None) -> bool:
        """
        Настроить глобальный движок коллизий подписей QGIS

        ВАЖНО: Вызывается ОДИН РАЗ при загрузке проекта!

        Args:
            iface: Интерфейс QGIS (опционально)

        Returns:
            True если успешно настроен
        """
        return self.collision_manager.configure_global_engine(iface)

    def reset_counters(self) -> None:
        """Сброс счётчиков статистики (вызывать перед пакетной обработкой)"""
        self._applied_count = 0
        self._obstacle_count = 0
        self._skipped_count = 0
        self._error_count = 0

    def log_summary(self) -> None:
        """Вывести итоговую статистику применения подписей"""
        total = self._applied_count + self._obstacle_count + self._skipped_count + self._error_count
        if total > 0:
            parts = []
            if self._applied_count > 0:
                parts.append(f"подписей: {self._applied_count}")
            if self._obstacle_count > 0:
                parts.append(f"препятствий: {self._obstacle_count}")
            if self._error_count > 0:
                parts.append(f"ошибок: {self._error_count}")
            log_info(f"M_12: Итого применено: {', '.join(parts)}")

    def remove_labels(self, layer: QgsVectorLayer) -> bool:
        """
        Удалить подписи со слоя

        Args:
            layer: Векторный слой

        Returns:
            True если успешно удалено
        """
        try:
            layer.setLabelsEnabled(False)
            layer.triggerRepaint()
            return True
        except Exception as e:
            log_error(f"M_12: Ошибка удаления подписей: {str(e)}")
            return False

    def has_labels_configured(self, full_name: str) -> bool:
        """
        Проверить настроены ли подписи для слоя

        Args:
            full_name: Полное имя слоя

        Returns:
            True если слой найден в Base_labels.json и имеет label_field

        Example:
            >>> if label_manager.has_labels_configured("L_1_2_1_WFS_ЗУ"):
            >>>     print("Подписи настроены")
        """
        return self.ref_manager.has_labels_enabled(full_name)

    def get_label_info(self, full_name: str) -> Optional[dict]:
        """
        Получить информацию о настройках подписей слоя

        Args:
            full_name: Полное имя слоя

        Returns:
            Словарь с информацией или None если не настроено

        Example:
            >>> info = label_manager.get_label_info("L_1_2_1_WFS_ЗУ")
            >>> if info:
            >>>     print(f"Поле: {info['label_field']}")
            >>>     print(f"Приоритет: {info['label_priority']}")
        """
        config = self.ref_manager.get_label_config(full_name)
        if config:
            # Дополняем defaults
            defaults = self.ref_manager.get_default_config()
            return {**defaults, **config}
        return None

    def get_layers_with_labels(self) -> list:
        """
        Получить список всех слоёв с настроенными подписями

        Returns:
            Список full_name слоёв

        Example:
            >>> layers = label_manager.get_layers_with_labels()
            >>> print(f"Подписи настроены для {len(layers)} слоёв")
        """
        return self.ref_manager.get_layers_with_labels()


    def get_statistics(self) -> dict:
        """
        Получить статистику по настроенным подписям

        Returns:
            Словарь со статистикой

        Example:
            >>> stats = label_manager.get_statistics()
            >>> print(f"Всего слоёв с подписями: {stats['total_layers']}")
            >>> print(f"По приоритетам: {stats['by_priority']}")
        """
        all_labels = self.ref_manager.get_all_labels()

        # Подсчитываем слои с подписями
        with_labels = [l for l in all_labels if l.get('label_field')]

        # Группируем по приоритетам
        by_priority = {}
        for label in with_labels:
            priority = label.get('label_priority', 5)
            by_priority[priority] = by_priority.get(priority, 0) + 1

        # Группируем по типам (с препятствием / без)
        obstacles = sum(1 for l in with_labels if l.get('label_is_obstacle', True))
        non_obstacles = len(with_labels) - obstacles

        return {
            'total_layers': len(with_labels),
            'total_in_db': len(all_labels),
            'by_priority': by_priority,
            'obstacles': obstacles,
            'non_obstacles': non_obstacles
        }
