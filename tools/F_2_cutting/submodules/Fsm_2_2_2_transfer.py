# -*- coding: utf-8 -*-
"""
Fsm_2_2_2_Transfer - Логика переноса ЗУ из Раздел/Изм в Без_Меж

Выполняет:
1. Поиск всех нарезанных частей ЗУ по КН в слоях Раздел и Изм
2. Удаление всех найденных частей
3. Копирование ИСХОДНОГО ЗУ из Выборки в слой Без_Меж
4. Перенумерование ID во всех затронутых слоях (NW->SE)
5. Сохранение в GPKG

Атрибуты для Без_Меж (берутся из исходного ЗУ в Выборке):
- Услов_КН = КН (копируется, не генерируется)
- План_категория = Категория
- План_ВРИ = ВРИ
- Площадь_ОЗУ = Площадь
- Вид_Работ = "Существующий (сохраняемый) земельный участок"
- Точки = "-" (нет нумерации)

ВАЖНО: Геометрия берётся из ИСХОДНОГО ЗУ в Выборке, а не из нарезанных частей!
"""

import os
from typing import List, Optional, Dict, Any, Set, TYPE_CHECKING

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsFeature,
    QgsGeometry,
    QgsFields,
    QgsPointXY,
)

from Daman_QGIS.utils import log_info, log_warning, log_error

if TYPE_CHECKING:
    from Daman_QGIS.managers import LayerManager


class Fsm_2_2_2_Transfer:
    """Модуль переноса исходных ЗУ из Выборки в Без_Меж

    Удаляет все нарезанные части из Раздел/Изм и копирует
    исходную геометрию ЗУ из Выборки в слой Без_Меж.
    """

    def __init__(
        self,
        gpkg_path: str,
        selection_layer: QgsVectorLayer,
        razdel_layers: List[QgsVectorLayer],
        izm_layers: List[QgsVectorLayer],
        layer_to_zpr_type: Dict[str, str],
        zpr_type_to_bez_mezh: Dict[str, str],
        work_type: str,
        layer_manager: Optional['LayerManager'] = None
    ) -> None:
        """Инициализация модуля переноса

        Args:
            gpkg_path: Путь к GeoPackage проекта
            selection_layer: Слой Выборки ЗУ (источник исходных геометрий)
            razdel_layers: Список слоёв Раздел (нарезанные части)
            izm_layers: Список слоёв Изм (нарезанные части)
            layer_to_zpr_type: Маппинг имя_слоя -> тип_ЗПР ('ОКС', 'ПО', 'ВО')
            zpr_type_to_bez_mezh: Маппинг тип_ЗПР -> имя_слоя_Без_Меж
            work_type: Значение поля Вид_Работ для Без_Меж
            layer_manager: Менеджер слоёв (опционально)
        """
        self.gpkg_path = gpkg_path
        self.selection_layer = selection_layer
        self.razdel_layers = razdel_layers
        self.izm_layers = izm_layers
        self.layer_to_zpr_type = layer_to_zpr_type
        self.zpr_type_to_bez_mezh = zpr_type_to_bez_mezh
        self.work_type = work_type
        self.layer_manager = layer_manager

        # Слои затронутые операцией (для перенумерации)
        self._affected_layers: Set[QgsVectorLayer] = set()
        # Созданные/использованные слои Без_Меж
        self._bez_mezh_layers: Dict[str, QgsVectorLayer] = {}

    def execute(self, kn_list: List[str]) -> Dict[str, Any]:
        """Выполнить перенос ЗУ по списку КН

        Args:
            kn_list: Список кадастровых номеров для переноса

        Returns:
            Словарь с результатом:
            {
                'transferred': int,           # Количество перенесённых ЗУ
                'deleted_from_razdel': int,   # Удалено частей из Раздел
                'deleted_from_izm': int,      # Удалено частей из Изм
                'target_layers': List[str],   # Имена целевых слоёв
                'errors': List[str]           # Ошибки (если есть)
            }
        """
        log_info(f"Fsm_2_2_2: Перенос {len(kn_list)} ЗУ по КН")

        results = {
            'transferred': 0,
            'deleted_from_razdel': 0,
            'deleted_from_izm': 0,
            'target_layers': [],
            'errors': []
        }

        self._affected_layers.clear()
        self._bez_mezh_layers.clear()

        try:
            for kn in kn_list:
                kn_result = self._transfer_single_kn(kn)

                if kn_result.get('error'):
                    results['errors'].append(f"{kn}: {kn_result['error']}")
                else:
                    results['transferred'] += 1
                    results['deleted_from_razdel'] += kn_result.get('deleted_razdel', 0)
                    results['deleted_from_izm'] += kn_result.get('deleted_izm', 0)

            # Перенумеровать ID во всех затронутых слоях
            self._renumber_all_affected_layers()

            # Commit изменений во всех слоях
            self._commit_all_changes()

            # Добавить слои Без_Меж в проект если новые
            for layer_name, layer in self._bez_mezh_layers.items():
                self._add_layer_to_project(layer, layer_name)
                if layer_name not in results['target_layers']:
                    results['target_layers'].append(layer_name)

            log_info(
                f"Fsm_2_2_2: Завершено. Перенесено: {results['transferred']}, "
                f"удалено из Раздел: {results['deleted_from_razdel']}, "
                f"удалено из Изм: {results['deleted_from_izm']}"
            )

        except Exception as e:
            log_error(f"Fsm_2_2_2: Исключение при переносе: {e}")
            results['errors'].append(str(e))

        return results

    def _transfer_single_kn(self, kn: str) -> Dict[str, Any]:
        """Перенос одного ЗУ по КН

        Шаги:
        1. Найти в каких слоях Раздел/Изм есть этот КН
        2. Определить целевые слои Без_Меж по типам ЗПР
        3. Удалить ВСЕ части с этим КН из Раздел и Изм
        4. Найти исходный ЗУ в Выборке
        5. Скопировать в каждый целевой слой Без_Меж

        Args:
            kn: Кадастровый номер

        Returns:
            Результат переноса для данного КН
        """
        log_info(f"Fsm_2_2_2: Обработка КН {kn}")

        result = {
            'deleted_razdel': 0,
            'deleted_izm': 0,
            'copied_to': []
        }

        # 1. Найти все вхождения КН в слоях нарезки
        kn_locations = self._find_kn_locations(kn)

        if not kn_locations:
            return {'error': f"КН {kn} не найден в слоях Раздел/Изм"}

        # 2. Определить типы ЗПР для данного КН
        zpr_types: Set[str] = set()
        for layer_name in kn_locations.keys():
            zpr_type = self.layer_to_zpr_type.get(layer_name)
            if zpr_type:
                zpr_types.add(zpr_type)

        log_info(f"Fsm_2_2_2: КН {kn} найден в ЗПР типов: {zpr_types}")

        # 3. Получить исходный ЗУ из Выборки
        zu_feature = self._get_zu_from_selection(kn)
        if not zu_feature:
            return {'error': f"Исходный ЗУ с КН {kn} не найден в Выборке"}

        # 4. Удалить все части из Раздел
        for layer in self.razdel_layers:
            layer_name = layer.name()
            if layer_name in kn_locations:
                fids = kn_locations[layer_name]
                deleted = self._delete_features_by_fids(layer, fids)
                result['deleted_razdel'] += deleted
                self._affected_layers.add(layer)

        # 5. Удалить все части из Изм
        for layer in self.izm_layers:
            layer_name = layer.name()
            if layer_name in kn_locations:
                fids = kn_locations[layer_name]
                deleted = self._delete_features_by_fids(layer, fids)
                result['deleted_izm'] += deleted
                self._affected_layers.add(layer)

        # 6. Скопировать исходный ЗУ в каждый целевой слой Без_Меж
        for zpr_type in zpr_types:
            bez_mezh_name = self.zpr_type_to_bez_mezh.get(zpr_type)
            if not bez_mezh_name:
                log_warning(f"Fsm_2_2_2: Не найден слой Без_Меж для типа {zpr_type}")
                continue

            # Получить или создать слой Без_Меж
            bez_mezh_layer = self._get_or_create_bez_mezh_layer(bez_mezh_name, zpr_type)
            if not bez_mezh_layer:
                result['error'] = f"Не удалось создать слой {bez_mezh_name}"
                continue

            # Копировать ЗУ в слой Без_Меж
            if self._copy_zu_to_bez_mezh(zu_feature, bez_mezh_layer, zpr_type):
                result['copied_to'].append(bez_mezh_name)
                self._affected_layers.add(bez_mezh_layer)
                self._bez_mezh_layers[bez_mezh_name] = bez_mezh_layer

        return result

    def _find_kn_locations(self, kn: str) -> Dict[str, List[int]]:
        """Найти все вхождения КН в слоях Раздел и Изм

        Args:
            kn: Кадастровый номер для поиска

        Returns:
            Dict[layer_name, List[fid]] - где найден КН и fid features
        """
        locations: Dict[str, List[int]] = {}

        # Поиск в слоях Раздел
        for layer in self.razdel_layers:
            fids = self._find_kn_in_layer(layer, kn)
            if fids:
                locations[layer.name()] = fids

        # Поиск в слоях Изм
        for layer in self.izm_layers:
            fids = self._find_kn_in_layer(layer, kn)
            if fids:
                locations[layer.name()] = fids

        return locations

    def _find_kn_in_layer(self, layer: QgsVectorLayer, kn: str) -> List[int]:
        """Найти features с заданным КН в слое

        Args:
            layer: Слой для поиска
            kn: Кадастровый номер

        Returns:
            Список fid найденных features
        """
        fids = []

        kn_idx = layer.fields().indexOf('КН')
        if kn_idx < 0:
            return fids

        for feature in layer.getFeatures():
            feature_kn = feature['КН']
            if feature_kn and str(feature_kn).strip() == str(kn).strip():
                fids.append(feature.id())

        return fids

    def _get_zu_from_selection(self, kn: str) -> Optional[QgsFeature]:
        """Получить исходный ЗУ из слоя Выборки по КН

        Args:
            kn: Кадастровый номер

        Returns:
            QgsFeature или None
        """
        if not self.selection_layer:
            return None

        kn_idx = self.selection_layer.fields().indexOf('КН')
        if kn_idx < 0:
            log_warning("Fsm_2_2_2: Поле КН не найдено в слое Выборки")
            return None

        for feature in self.selection_layer.getFeatures():
            feature_kn = feature['КН']
            if feature_kn and str(feature_kn).strip() == str(kn).strip():
                if feature.isValid() and feature.hasGeometry():
                    return feature

        return None

    def _delete_features_by_fids(
        self,
        layer: QgsVectorLayer,
        fids: List[int]
    ) -> int:
        """Удалить features из слоя по списку fid

        Args:
            layer: Слой
            fids: Список fid для удаления

        Returns:
            Количество удалённых features
        """
        if not fids:
            return 0

        if not layer.isEditable():
            layer.startEditing()

        deleted = 0
        for fid in fids:
            if layer.deleteFeature(fid):
                deleted += 1
            else:
                log_warning(f"Fsm_2_2_2: Не удалось удалить feature {fid} из {layer.name()}")

        layer.updateExtents()
        log_info(f"Fsm_2_2_2: Удалено {deleted} features из {layer.name()}")

        return deleted

    def _get_or_create_bez_mezh_layer(
        self,
        layer_name: str,
        zpr_type: str
    ) -> Optional[QgsVectorLayer]:
        """Получить существующий или создать новый слой Без_Меж

        Args:
            layer_name: Имя слоя Без_Меж
            zpr_type: Тип ЗПР (для определения слоя-образца)

        Returns:
            QgsVectorLayer или None
        """
        # Проверить кэш
        if layer_name in self._bez_mezh_layers:
            return self._bez_mezh_layers[layer_name]

        project = QgsProject.instance()

        # Проверить существующий слой в проекте
        existing_layers = project.mapLayersByName(layer_name)
        if existing_layers:
            layer = existing_layers[0]
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                log_info(f"Fsm_2_2_2: Используем существующий слой {layer_name}")
                layer.startEditing()
                return layer

        # Проверить слой в GPKG
        uri = f"{self.gpkg_path}|layername={layer_name}"
        gpkg_layer = QgsVectorLayer(uri, layer_name, "ogr")
        if gpkg_layer.isValid():
            log_info(f"Fsm_2_2_2: Загружен слой {layer_name} из GPKG")
            gpkg_layer.startEditing()
            return gpkg_layer

        # Создать новый слой на основе слоя Раздел того же типа
        template_layer = self._find_template_layer(zpr_type)
        if template_layer:
            log_info(f"Fsm_2_2_2: Создание нового слоя {layer_name}")
            return self._create_new_layer(template_layer, layer_name)

        log_error(f"Fsm_2_2_2: Не удалось найти шаблон для слоя {layer_name}")
        return None

    def _find_template_layer(self, zpr_type: str) -> Optional[QgsVectorLayer]:
        """Найти слой-шаблон для создания нового слоя Без_Меж

        Args:
            zpr_type: Тип ЗПР ('ОКС', 'ПО', 'ВО')

        Returns:
            Слой Раздел того же типа или None
        """
        for layer in self.razdel_layers:
            layer_zpr_type = self.layer_to_zpr_type.get(layer.name())
            if layer_zpr_type == zpr_type:
                return layer

        # Fallback: использовать любой слой Раздел
        if self.razdel_layers:
            return self.razdel_layers[0]

        return None

    def _create_new_layer(
        self,
        template_layer: QgsVectorLayer,
        layer_name: str
    ) -> Optional[QgsVectorLayer]:
        """Создать новый слой в GPKG с такой же структурой

        Args:
            template_layer: Слой-образец
            layer_name: Имя нового слоя

        Returns:
            QgsVectorLayer или None
        """
        try:
            crs = template_layer.crs()
            fields = template_layer.fields()

            # Создаём memory layer
            mem_layer = QgsVectorLayer(
                f"MultiPolygon?crs={crs.authid()}",
                layer_name,
                "memory"
            )

            if not mem_layer.isValid():
                log_error(f"Fsm_2_2_2: Не удалось создать memory layer")
                return None

            # Добавляем поля
            mem_layer.dataProvider().addAttributes(fields.toList())
            mem_layer.updateFields()

            # Сохраняем в GPKG
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = layer_name

            if os.path.exists(self.gpkg_path):
                options.actionOnExistingFile = (
                    QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
                )
            else:
                options.actionOnExistingFile = (
                    QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
                )

            error = QgsVectorFileWriter.writeAsVectorFormatV3(
                mem_layer,
                self.gpkg_path,
                QgsProject.instance().transformContext(),
                options
            )

            if error[0] != QgsVectorFileWriter.WriterError.NoError:
                log_error(f"Fsm_2_2_2: Ошибка создания слоя в GPKG: {error[1]}")
                return None

            # Загружаем созданный слой
            uri = f"{self.gpkg_path}|layername={layer_name}"
            new_layer = QgsVectorLayer(uri, layer_name, "ogr")

            if new_layer.isValid():
                new_layer.startEditing()
                return new_layer
            else:
                log_error(f"Fsm_2_2_2: Не удалось загрузить созданный слой")
                return None

        except Exception as e:
            log_error(f"Fsm_2_2_2: Ошибка создания слоя: {e}")
            return None

    def _copy_zu_to_bez_mezh(
        self,
        zu_feature: QgsFeature,
        target_layer: QgsVectorLayer,
        zpr_type: str
    ) -> bool:
        """Скопировать исходный ЗУ в слой Без_Меж

        Args:
            zu_feature: Feature из Выборки
            target_layer: Слой Без_Меж
            zpr_type: Тип ЗПР

        Returns:
            True если успешно
        """
        if not target_layer.isEditable():
            target_layer.startEditing()

        try:
            # Создаём новый feature с полями целевого слоя
            new_feat = QgsFeature(target_layer.fields())

            # Копируем геометрию из исходного ЗУ
            if zu_feature.hasGeometry():
                new_feat.setGeometry(QgsGeometry(zu_feature.geometry()))

            # Копируем базовые атрибуты из исходного ЗУ
            self._copy_base_attributes(zu_feature, new_feat, target_layer.fields())

            # Устанавливаем специфичные для Без_Меж атрибуты
            self._set_bez_mezh_attributes(zu_feature, new_feat, target_layer.fields(), zpr_type)

            # Добавляем feature в слой
            if not target_layer.addFeature(new_feat):
                log_error(f"Fsm_2_2_2: Не удалось добавить feature в {target_layer.name()}")
                return False

            target_layer.updateExtents()
            log_info(f"Fsm_2_2_2: ЗУ скопирован в {target_layer.name()}")
            return True

        except Exception as e:
            log_error(f"Fsm_2_2_2: Ошибка копирования ЗУ: {e}")
            return False

    # Маппинг полей Выборка_ЗУ -> слои нарезки (1:1, имена одинаковые)
    ZU_FIELD_MAPPING = {
        'КН': 'КН',
        'ЕЗ': 'ЕЗ',
        'Тип_объекта': 'Тип_объекта',
        'Адрес_Местоположения': 'Адрес_Местоположения',
        'Категория': 'Категория',
        'ВРИ': 'ВРИ',
        'Площадь': 'Площадь',
        'Права': 'Права',
        'Обременения': 'Обременения',
        'Собственники': 'Собственники',
        'Арендаторы': 'Арендаторы',
    }

    def _copy_base_attributes(
        self,
        source: QgsFeature,
        target: QgsFeature,
        target_fields: QgsFields
    ) -> None:
        """Копировать базовые атрибуты из исходного ЗУ

        Args:
            source: Исходный feature из Выборки
            target: Целевой feature для Без_Меж
            target_fields: Поля целевого слоя
        """
        # Используем маппинг для корректного копирования полей
        # (имена полей в Выборке и целевых слоях могут отличаться)
        for source_field, target_field in self.ZU_FIELD_MAPPING.items():
            target_idx = target_fields.indexOf(target_field)
            if target_idx >= 0:
                try:
                    value = source[source_field]
                    target.setAttribute(target_idx, value)
                except (KeyError, IndexError):
                    pass

    def _set_bez_mezh_attributes(
        self,
        source: QgsFeature,
        target: QgsFeature,
        target_fields: QgsFields,
        zpr_type: str
    ) -> None:
        """Установить специфичные для Без_Меж атрибуты

        Args:
            source: Исходный feature из Выборки
            target: Целевой feature для Без_Меж
            target_fields: Поля целевого слоя
            zpr_type: Тип ЗПР
        """
        # Услов_КН = КН (копируется, не генерируется)
        self._set_attr(target, target_fields, 'Услов_КН',
                       self._get_value(source, 'КН', '-'))

        # План_категория = Категория
        self._set_attr(target, target_fields, 'План_категория',
                       self._get_value(source, 'Категория', '-'))

        # План_ВРИ = ВРИ (из исходного ЗУ)
        vri_value = self._get_value(source, 'ВРИ', '-')
        self._set_attr(target, target_fields, 'План_ВРИ', vri_value)

        # Общая_земля - определяется по ВРИ из исходного ЗУ через M_21
        public_territory_status = self._determine_public_territory(vri_value)
        self._set_attr(target, target_fields, 'Общая_земля', public_territory_status)

        # Площадь_ОЗУ = Площадь
        self._set_attr(target, target_fields, 'Площадь_ОЗУ',
                       self._get_value(source, 'Площадь', 0))

        # Вид_Работ = константа
        self._set_attr(target, target_fields, 'Вид_Работ', self.work_type)

        # Точки = "-" (нет нумерации для Без_Меж)
        self._set_attr(target, target_fields, 'Точки', '-')

        # ЗПР = тип ЗПР
        self._set_attr(target, target_fields, 'ЗПР', zpr_type)

    def _determine_public_territory(self, vri_value: str) -> str:
        """Определить значение поля Общая_земля по ВРИ

        Использует M_21 (VRIAssignmentManager) для проверки is_public_territory.
        Поддерживает множественные ВРИ через разделитель ",".

        Args:
            vri_value: Значение ВРИ из исходного ЗУ (может быть множественным)

        Returns:
            "Отнесен" если хотя бы один ВРИ относится к территории общего пользования,
            "Не отнесен" в противном случае
        """
        if not vri_value or vri_value == '-':
            log_info("Fsm_2_2_2: ВРИ пустой или '-', Общая_земля = 'Не отнесен'")
            return "Не отнесен"

        try:
            from Daman_QGIS.managers.validation.M_21_vri_assignment_manager import VRIAssignmentManager

            vri_manager = VRIAssignmentManager.get_instance()

            # Разбиваем множественные ВРИ по запятой
            vri_parts = [v.strip() for v in vri_value.split(',') if v.strip()]
            log_info(f"Fsm_2_2_2: Проверка ВРИ на общие земли: {vri_parts}")

            for vri_str in vri_parts:
                # Используем внутренний метод для получения данных ВРИ
                vri_data = vri_manager._get_vri_data_for_single(vri_str)
                if vri_data:
                    is_public = vri_data.get('is_public_territory', False)
                    log_info(f"Fsm_2_2_2: ВРИ '{vri_str}' -> is_public_territory={is_public}")
                    if is_public:
                        log_info(f"Fsm_2_2_2: ВРИ '{vri_str}' относится к территории общего пользования")
                        return VRIAssignmentManager.PUBLIC_TERRITORY_YES
                else:
                    log_warning(f"Fsm_2_2_2: ВРИ '{vri_str}' не найден в базе VRI.json")

            log_info(f"Fsm_2_2_2: Ни один из ВРИ не относится к общим землям, Общая_земля = 'Не отнесен'")
            return VRIAssignmentManager.PUBLIC_TERRITORY_NO

        except Exception as e:
            log_warning(f"Fsm_2_2_2: Ошибка определения Общая_земля: {e}")
            return "Не отнесен"

    def _get_value(self, feature: QgsFeature, field_name: str, default: Any) -> Any:
        """Безопасное получение значения атрибута

        Args:
            feature: Feature
            field_name: Имя поля
            default: Значение по умолчанию

        Returns:
            Значение или default
        """
        try:
            value = feature[field_name]
            if value is None or value == '':
                return default
            return value
        except (KeyError, IndexError):
            return default

    def _set_attr(
        self,
        feature: QgsFeature,
        fields: QgsFields,
        field_name: str,
        value: Any
    ) -> None:
        """Установить атрибут по имени поля

        Args:
            feature: Feature
            fields: Структура полей
            field_name: Имя поля
            value: Значение
        """
        idx = fields.indexOf(field_name)
        if idx >= 0:
            feature.setAttribute(idx, value)

    def _renumber_all_affected_layers(self) -> None:
        """Перенумеровать ID во всех затронутых слоях (NW->SE сортировка)"""
        for layer in self._affected_layers:
            self._renumber_ids(layer)

    def _renumber_ids(self, layer: QgsVectorLayer) -> None:
        """Перенумеровать ID в слое (NW->SE сортировка)

        Args:
            layer: Слой для перенумерации
        """
        if not layer.isEditable():
            layer.startEditing()

        id_idx = layer.fields().indexOf('ID')
        if id_idx < 0:
            log_warning(f"Fsm_2_2_2: Поле ID не найдено в слое {layer.name()}")
            return

        # Получаем features и сортируем NW->SE
        features = list(layer.getFeatures())
        if not features:
            return

        sorted_features = self._sort_by_northwest(features)

        # Перенумерация
        for new_id, feature in enumerate(sorted_features, start=1):
            layer.changeAttributeValue(feature.id(), id_idx, new_id)

        log_info(f"Fsm_2_2_2: Перенумерованы ID в {layer.name()} ({len(features)} объектов)")

    @staticmethod
    def _sort_by_northwest(features: List[QgsFeature]) -> List[QgsFeature]:
        """Сортировка features от СЗ к ЮВ для корректной нумерации ID

        Алгоритм: сортировка по расстоянию центроида до СЗ угла глобального MBR.
        Это унифицированный алгоритм, используемый также в M_20 и F_2_3.

        Args:
            features: Список features для сортировки

        Returns:
            Отсортированный список
        """
        if len(features) <= 1:
            return features

        # Собираем центроиды и глобальный MBR
        centroids = []
        global_min_x = float('inf')
        global_max_y = float('-inf')

        for f in features:
            if f.hasGeometry() and not f.geometry().isEmpty():
                centroid = f.geometry().centroid().asPoint()
                centroids.append((centroid.x(), centroid.y()))
                bbox = f.geometry().boundingBox()
                global_min_x = min(global_min_x, bbox.xMinimum())
                global_max_y = max(global_max_y, bbox.yMaximum())
            else:
                centroids.append(None)

        # СЗ угол глобального MBR
        nw_x, nw_y = global_min_x, global_max_y

        # Сортируем по расстоянию до СЗ угла
        def sort_key(idx_feat):
            idx, _ = idx_feat
            c = centroids[idx]
            if c is None:
                return float('inf')
            return (c[0] - nw_x) ** 2 + (c[1] - nw_y) ** 2

        indexed = list(enumerate(features))
        indexed.sort(key=sort_key)

        return [feat for _, feat in indexed]

    def _commit_all_changes(self) -> None:
        """Сохранить изменения во всех затронутых слоях"""
        for layer in self._affected_layers:
            if layer.isEditable():
                if not layer.commitChanges():
                    log_warning(f"Fsm_2_2_2: Ошибка сохранения слоя {layer.name()}")
                else:
                    log_info(f"Fsm_2_2_2: Слой {layer.name()} сохранён")

    def _add_layer_to_project(
        self,
        layer: QgsVectorLayer,
        layer_name: str
    ) -> None:
        """Добавить слой в проект QGIS (если ещё не добавлен)

        Args:
            layer: Слой
            layer_name: Имя слоя
        """
        project = QgsProject.instance()

        # Проверить, есть ли уже такой слой
        existing = project.mapLayersByName(layer_name)
        if existing:
            return

        # Добавить слой
        project.addMapLayer(layer)
        log_info(f"Fsm_2_2_2: Слой {layer_name} добавлен в проект")

        # Применить стили через LayerManager если доступен
        if self.layer_manager:
            try:
                self.layer_manager.apply_style_to_layer(layer)
                self.layer_manager.apply_labels_to_layer(layer)
            except Exception as e:
                log_warning(f"Fsm_2_2_2: Не удалось применить стили: {e}")
