# -*- coding: utf-8 -*-
"""
Msm_31_2_MaskFilter - Фильтрация подписей слоев по маске.

Отвечает за:
- Добавление фильтра in_mask(srid) к свойству Show подписей
- Удаление фильтра с подписей
- Проверка наличия фильтра
- Поддержка Simple и Rule-based labeling
"""

from qgis.core import (
    QgsVectorLayer,
    QgsProject,
    QgsPalLayerSettings,
    QgsProperty,
    QgsVectorLayerSimpleLabeling,
    QgsRuleBasedLabeling,
)

from Daman_QGIS.utils import log_info, log_warning, log_error


# Имя пространственного фильтра (expression функция)
SPATIAL_FILTER = "in_mask"


class MaskLabelFilter:
    """Фильтрация подписей по маске."""

    def add_filter_to_layer(
        self,
        layer: QgsVectorLayer,
        mask_srid: int
    ) -> bool:
        """
        Добавить фильтр маски к подписям слоя.

        Устанавливает Data-defined property Show = in_mask(srid)
        для фильтрации подписей только внутри маски.

        Args:
            layer: Векторный слой
            mask_srid: EPSG код маски (postgisSrid)

        Returns:
            True если фильтр добавлен
        """
        if not isinstance(layer, QgsVectorLayer):
            return False

        if layer.labeling() is None:
            # Слой не имеет подписей
            return False

        try:
            # Формируем выражение фильтра
            expr = f"{SPATIAL_FILTER}({mask_srid})"
            prop = QgsProperty()
            prop.setExpressionString(expr)

            # Simple labeling (QgsVectorLayerSimpleLabeling)
            if isinstance(layer.labeling(), QgsVectorLayerSimpleLabeling):
                settings = QgsPalLayerSettings(layer.labeling().settings())
                settings.dataDefinedProperties().setProperty(
                    QgsPalLayerSettings.Property.Show, prop
                )
                layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
                return True

            # Rule-based labeling (QgsRuleBasedLabeling)
            if isinstance(layer.labeling(), QgsRuleBasedLabeling):
                root_rule = layer.labeling().rootRule()
                for rule in root_rule.children():
                    settings = rule.settings()
                    settings.dataDefinedProperties().setProperty(
                        QgsPalLayerSettings.Property.Show, prop
                    )
                    rule.setSettings(settings)
                return True

            return False

        except Exception as e:
            log_error(f"Msm_31_2: Ошибка добавления фильтра к {layer.name()}: {e}")
            return False

    def remove_filter_from_layer(self, layer: QgsVectorLayer) -> bool:
        """
        Удалить фильтр маски с подписей слоя.

        Устанавливает Show = True (всегда показывать).

        Args:
            layer: Векторный слой

        Returns:
            True если фильтр удалён
        """
        if not isinstance(layer, QgsVectorLayer):
            return False

        if layer.labeling() is None:
            return False

        try:
            # Simple labeling
            if isinstance(layer.labeling(), QgsVectorLayerSimpleLabeling):
                settings = layer.labeling().settings()

                # Проверяем, есть ли наш фильтр
                if settings.dataDefinedProperties().hasProperty(
                    QgsPalLayerSettings.Property.Show
                ):
                    show_prop = settings.dataDefinedProperties().property(
                        QgsPalLayerSettings.Property.Show
                    )
                    expr_str = show_prop.expressionString() if show_prop else ""

                    if expr_str.startswith(SPATIAL_FILTER):
                        # Удаляем фильтр (устанавливаем Show = True)
                        new_settings = QgsPalLayerSettings(settings)
                        new_settings.dataDefinedProperties().setProperty(
                            QgsPalLayerSettings.Property.Show, True
                        )
                        layer.setLabeling(QgsVectorLayerSimpleLabeling(new_settings))
                        return True

            # Rule-based labeling
            if isinstance(layer.labeling(), QgsRuleBasedLabeling):
                modified = False
                root_rule = layer.labeling().rootRule()

                for rule in root_rule.children():
                    settings = rule.settings()
                    if settings.dataDefinedProperties().hasProperty(
                        QgsPalLayerSettings.Property.Show
                    ):
                        show_prop = settings.dataDefinedProperties().property(
                            QgsPalLayerSettings.Property.Show
                        )
                        expr_str = show_prop.expressionString() if show_prop else ""

                        if expr_str.startswith(SPATIAL_FILTER):
                            settings.dataDefinedProperties().setProperty(
                                QgsPalLayerSettings.Property.Show, True
                            )
                            rule.setSettings(settings)
                            modified = True

                return modified

            return False

        except Exception as e:
            log_error(f"Msm_31_2: Ошибка удаления фильтра с {layer.name()}: {e}")
            return False

    def has_filter(self, layer: QgsVectorLayer) -> bool:
        """
        Проверить, есть ли у слоя фильтр маски.

        Args:
            layer: Векторный слой

        Returns:
            True если фильтр установлен
        """
        if not isinstance(layer, QgsVectorLayer):
            return False

        if layer.labeling() is None:
            return False

        try:
            # Simple labeling
            if isinstance(layer.labeling(), QgsVectorLayerSimpleLabeling):
                settings = layer.labeling().settings()
                show_prop = settings.dataDefinedProperties().property(
                    QgsPalLayerSettings.Property.Show
                )
                if show_prop is None:
                    return False

                expr_str = show_prop.expressionString()
                return expr_str.startswith(SPATIAL_FILTER) if expr_str else False

            # Rule-based labeling - проверяем первое правило
            if isinstance(layer.labeling(), QgsRuleBasedLabeling):
                root_rule = layer.labeling().rootRule()
                for rule in root_rule.children():
                    settings = rule.settings()
                    show_prop = settings.dataDefinedProperties().property(
                        QgsPalLayerSettings.Property.Show
                    )
                    if show_prop is None:
                        return False

                    expr_str = show_prop.expressionString()
                    return expr_str.startswith(SPATIAL_FILTER) if expr_str else False

            return False

        except Exception:
            return False

    def add_filter_to_all_layers(
        self,
        mask_layer: QgsVectorLayer
    ) -> int:
        """
        Добавить фильтр ко всем векторным слоям проекта.

        Пропускает сам слой маски.

        Args:
            mask_layer: Слой маски (для получения SRID)

        Returns:
            Количество слоёв с добавленным фильтром
        """
        if mask_layer is None or not mask_layer.isValid():
            log_error("Msm_31_2: Слой маски недействителен")
            return 0

        mask_srid = mask_layer.crs().postgisSrid()
        mask_id = mask_layer.id()
        count = 0

        for layer_id, layer in QgsProject.instance().mapLayers().items():
            # Пропускаем не-векторные слои
            if not isinstance(layer, QgsVectorLayer):
                continue

            # Пропускаем сам слой маски
            if layer_id == mask_id:
                continue

            # Добавляем фильтр
            if self.add_filter_to_layer(layer, mask_srid):
                count += 1

        log_info(f"Msm_31_2: Фильтр маски добавлен к {count} слоям")
        return count

    def remove_filter_from_all_layers(self) -> int:
        """
        Удалить фильтр маски со всех слоёв проекта.

        Returns:
            Количество слоёв с удалённым фильтром
        """
        count = 0

        for layer_id, layer in QgsProject.instance().mapLayers().items():
            if not isinstance(layer, QgsVectorLayer):
                continue

            if self.remove_filter_from_layer(layer):
                count += 1

        log_info(f"Msm_31_2: Фильтр маски удалён с {count} слоёв")
        return count

    def get_layers_with_filter(self) -> list:
        """
        Получить список слоёв с установленным фильтром маски.

        Returns:
            Список QgsVectorLayer с фильтром
        """
        result = []

        for layer_id, layer in QgsProject.instance().mapLayers().items():
            if isinstance(layer, QgsVectorLayer) and self.has_filter(layer):
                result.append(layer)

        return result
