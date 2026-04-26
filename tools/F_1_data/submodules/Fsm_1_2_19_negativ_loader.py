# -*- coding: utf-8 -*-
"""
Субмодуль F_1_2: Загрузка и классификация негативных процессов
Загружает объекты через egrn_loader, классифицирует по правилам из Base_negativ_classification.json
и распределяет по целевым подслоям. Нераспознанные объекты -> GUI диалог.
Пропущенные -> fallback слой Le_1_2_11_1_Негатив_Иные.
"""

import re
from typing import Optional, List, Dict

from qgis.core import QgsVectorLayer, QgsFeature
from qgis.PyQt.QtWidgets import QDialog

from Daman_QGIS.utils import log_info, log_warning, log_error, log_success, normalize_for_classification

FALLBACK_LAYER_NAME = "Le_1_2_11_1_Негатив_Иные"


class Fsm_1_2_19_NegativLoader:
    """Загрузчик и классификатор негативных процессов"""

    def __init__(self, iface, egrn_loader, layer_manager, geometry_processor, api_manager):
        """
        Инициализация загрузчика негативных процессов

        Args:
            iface: Интерфейс QGIS
            egrn_loader: Экземпляр Fsm_1_2_1_EgrnLoader для загрузки данных
            layer_manager: LayerManager для добавления слоёв
            geometry_processor: Fsm_1_2_8_GeometryProcessor для сохранения в GPKG
            api_manager: APIManager для получения endpoint параметров
        """
        self.iface = iface
        self.egrn_loader = egrn_loader
        self.layer_manager = layer_manager
        self.geometry_processor = geometry_processor
        self.api_manager = api_manager

    def load_negativ_layers(self, boundary_layer, gpkg_path: str, progress_task=None) -> int:
        """Загрузить и классифицировать негативные процессы

        Загружает все объекты через egrn_loader, классифицирует по правилам
        из Base_negativ_classification.json, показывает GUI для нераспознанных,
        пропущенные попадают в fallback слой Le_1_2_11_1_Негатив_Иные.

        Args:
            boundary_layer: Слой границ работ
            gpkg_path: Путь к GeoPackage
            progress_task: Задача прогресса (опционально)

        Returns:
            int: Количество сохранённых объектов
        """
        try:
            # Проверка что egrn_loader инициализирован
            if not self.egrn_loader:
                log_error("Fsm_1_2_19: egrn_loader не инициализирован для загрузки негативных процессов")
                return 0

            log_info("Fsm_1_2_19: Загрузка негативных процессов с классификацией")

            # 1. Создаём geometry provider с буфером 500м
            egrn_loader = self.egrn_loader
            geometry_provider = lambda: egrn_loader.get_boundary_extent(use_500m_buffer=True)

            # 2. Загружаем ВСЕ негативные процессы через стандартный load_layer
            layer, total = self.egrn_loader.load_layer(
                layer_name="Негатив_проц_UNIVERSAL",
                geometry_provider=geometry_provider,
                progress_task=progress_task
            )

            if not layer or total == 0:
                log_info("Fsm_1_2_19: Негативные процессы не найдены в данной области")
                return 0

            log_info(f"Fsm_1_2_19: Загружено {total} объектов негативных процессов")

            # 3. Получаем правила классификации
            from Daman_QGIS.managers import get_reference_managers
            ref_managers = get_reference_managers()
            rules = ref_managers.negativ_classification.get_rules()

            if not rules:
                log_warning("Fsm_1_2_19: Правила классификации не загружены, пропуск классификации")
                return 0

            log_info(f"Fsm_1_2_19: Загружено {len(rules)} правил классификации")

            # 4. Классификация features
            grouped: Dict[str, List[QgsFeature]] = {}
            unknown_features: List[QgsFeature] = []

            for feat in layer.getFeatures():
                target_layer = self._classify_by_rules(feat, rules)
                if target_layer:
                    if target_layer not in grouped:
                        grouped[target_layer] = []
                    grouped[target_layer].append(feat)
                else:
                    unknown_features.append(feat)

            log_info(
                f"Fsm_1_2_19: Автоклассификация: {sum(len(v) for v in grouped.values())} распознано, "
                f"{len(unknown_features)} не распознано"
            )

            # 5. GUI для нераспознанных объектов
            if unknown_features:
                self._classify_unknown_via_gui(unknown_features, grouped, ref_managers)

            # 6. Создание подслоёв и сохранение в GPKG
            total_saved = 0

            for target_name, features in grouped.items():
                try:
                    # Создание memory layer с полями исходника
                    target = QgsVectorLayer(
                        f"MultiPolygon?crs={layer.crs().authid()}",
                        target_name, "memory"
                    )
                    target.startEditing()
                    for field in layer.fields():
                        target.addAttribute(field)
                    target.commitChanges()

                    # Копирование features
                    target.startEditing()
                    for feat in features:
                        new_feat = QgsFeature(target.fields())
                        new_feat.setGeometry(feat.geometry())
                        new_feat.setAttributes(feat.attributes())
                        target.addFeature(new_feat)
                    target.commitChanges()

                    # Сохранение в GeoPackage
                    clean_name = target_name.replace(' ', '_')
                    clean_name = re.sub(r'_{2,}', '_', clean_name)
                    target.setName(clean_name)

                    saved_layer = self.geometry_processor.save_to_geopackage(target, gpkg_path, clean_name)
                    if saved_layer:
                        target = saved_layer

                    if self.layer_manager:
                        target.setName(clean_name)
                        self.layer_manager.add_layer(
                            target, make_readonly=False, auto_number=False, check_precision=False
                        )

                    total_saved += len(features)
                    log_info(f"Fsm_1_2_19: {clean_name} - {len(features)} объектов")

                except Exception as e:
                    log_error(f"Fsm_1_2_19: Ошибка обработки подслоя {target_name}: {str(e)}")

            log_success(
                f"Fsm_1_2_19: Загружено и распределено {total_saved} объектов по {len(grouped)} подслоям"
            )
            return total_saved

        except Exception as e:
            log_error(f"Fsm_1_2_19: Ошибка загрузки негативных процессов: {str(e)}")
            return 0

    def _classify_by_rules(self, feature: QgsFeature, rules: list) -> Optional[str]:
        """Классифицировать feature по правилам из Base_negativ_classification.json

        Логика идентична egrn_loader._classify_by_database(), но работает с QgsFeature.

        Args:
            feature: QgsFeature для классификации
            rules: Список правил (отсортированных по rule_id)

        Returns:
            Имя целевого слоя или None если не распознано
        """
        # Извлекаем значения полей из feature (с нормализацией невидимых символов NSPD + lower)
        search_texts = {}
        for field in feature.fields():
            name = field.name()
            value = feature[name]
            search_texts[name] = normalize_for_classification(str(value)).lower() if value is not None else ""

        # Проверяем каждое правило по порядку rule_id
        for rule in rules:
            search_field_raw = rule.get('search_field', '').strip()
            keywords_raw = rule.get('keywords', '').strip()

            if not search_field_raw or not keywords_raw:
                continue

            # Нормализуем keywords к тому же виду что search_texts
            search_fields = [f.strip() for f in search_field_raw.split(';') if f.strip()]
            keywords_list = [
                normalize_for_classification(k).lower()
                for k in keywords_raw.split(';') if k.strip()
            ]

            if len(search_fields) > 1:
                # Несколько полей -- AND логика
                if len(search_fields) != len(keywords_list):
                    continue
                all_matched = True
                for field_name, keyword in zip(search_fields, keywords_list):
                    search_text = search_texts.get(field_name, '')
                    if keyword not in search_text:
                        all_matched = False
                        break
                if all_matched:
                    return rule.get('target_layer')
            else:
                # Одно поле -- OR логика (любое ключевое слово)
                field_name = search_fields[0]
                search_text = search_texts.get(field_name, '')
                if any(keyword in search_text for keyword in keywords_list):
                    return rule.get('target_layer')

        return None

    def _classify_unknown_via_gui(
        self,
        unknown_features: List[QgsFeature],
        grouped: Dict[str, List[QgsFeature]],
        ref_managers
    ) -> None:
        """Показать GUI диалог для ручной классификации нераспознанных объектов

        Пропущенные объекты попадают в fallback слой Le_1_2_11_1_Негатив_Иные.

        Args:
            unknown_features: Список нераспознанных features
            grouped: Словарь target_name -> features (мутируется)
            ref_managers: Менеджеры справочников для получения списка слоёв
        """
        from .Fsm_1_2_19_negativ_classifier_dialog import NegativClassifierDialog

        # Получаем список всех слоёв для комбобокса
        all_layers = ref_managers.layer.get_base_layers()

        skipped_count = 0
        classified_count = 0

        for i, feat in enumerate(unknown_features):
            dialog = NegativClassifierDialog(
                parent=self.iface.mainWindow(),
                feature=feat,
                target_layers=all_layers,
                current_index=i + 1,
                total_count=len(unknown_features)
            )

            result = dialog.exec()

            if result == QDialog.DialogCode.Accepted:
                selected_layer, skip_all = dialog.get_result()

                if skip_all:
                    # Пропустить все оставшиеся -- в fallback слой
                    remaining = len(unknown_features) - i
                    if FALLBACK_LAYER_NAME not in grouped:
                        grouped[FALLBACK_LAYER_NAME] = []
                    for remaining_feat in unknown_features[i:]:
                        grouped[FALLBACK_LAYER_NAME].append(remaining_feat)
                    skipped_count += remaining
                    log_info(
                        f"Fsm_1_2_19: Все оставшиеся ({remaining} объектов) "
                        f"направлены в {FALLBACK_LAYER_NAME}"
                    )
                    break

                if selected_layer:
                    # Пользователь выбрал слой
                    if selected_layer not in grouped:
                        grouped[selected_layer] = []
                    grouped[selected_layer].append(feat)
                    classified_count += 1
                else:
                    # Пропустить -- в fallback слой
                    if FALLBACK_LAYER_NAME not in grouped:
                        grouped[FALLBACK_LAYER_NAME] = []
                    grouped[FALLBACK_LAYER_NAME].append(feat)
                    skipped_count += 1
            else:
                # Диалог закрыт -- все оставшиеся в fallback
                remaining = len(unknown_features) - i
                if FALLBACK_LAYER_NAME not in grouped:
                    grouped[FALLBACK_LAYER_NAME] = []
                for remaining_feat in unknown_features[i:]:
                    grouped[FALLBACK_LAYER_NAME].append(remaining_feat)
                skipped_count += remaining
                log_info(
                    f"Fsm_1_2_19: Диалог закрыт, оставшиеся объекты "
                    f"направлены в {FALLBACK_LAYER_NAME}"
                )
                break

        if classified_count > 0:
            log_info(f"Fsm_1_2_19: Вручную классифицировано {classified_count} объектов")
        if skipped_count > 0:
            log_info(f"Fsm_1_2_19: {skipped_count} объектов направлено в {FALLBACK_LAYER_NAME}")
