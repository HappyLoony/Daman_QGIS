# -*- coding: utf-8 -*-
"""
Fsm_1_1_7_ZprAttributeValidator - Валидатор атрибутов ЗПР при импорте

Проверяет значения обязательных полей (ID, ID_KV, VRI, MIN_AREA_VRI)
в импортированных слоях ЗПР. При невалидных значениях показывает
per-feature GUI диалог для ручного ввода.

Валидация:
- VRI: через Msm_21_1_ExistingVRIValidator.soft_validate()
- ID, ID_KV, MIN_AREA_VRI: проверка на пустоту/NULL

Используется в F_1_1 после сохранения ЗПР в GPKG.
"""

from typing import Dict, List, Optional, Any

from qgis.core import QgsVectorLayer, QgsFeature
from qgis.PyQt.QtCore import QVariant

from Daman_QGIS.utils import log_info, log_warning, log_error

__all__ = ['Fsm_1_1_7_ZprAttributeValidator']


class Fsm_1_1_7_ZprAttributeValidator:
    """Валидатор и оркестратор GUI для атрибутов ЗПР"""

    # Обязательные поля ЗПР (схема ZPR из M_28)
    ZPR_REQUIRED_FIELDS = ['ID', 'ID_KV', 'VRI', 'MIN_AREA_VRI']

    # Значения, считающиеся пустыми
    EMPTY_VALUES = ('', '-', 'NULL', 'None', 'null', 'none')

    def __init__(self) -> None:
        self._vri_manager = None
        self._vri_validator = None
        self._vri_list: List[Dict] = []
        self._vri_initialized = False

    def _init_vri(self) -> bool:
        """Инициализация VRI manager и валидатора.

        Returns:
            True если инициализация успешна
        """
        if self._vri_initialized:
            return bool(self._vri_validator)

        self._vri_initialized = True

        try:
            from Daman_QGIS.managers.validation.M_21_vri_assignment_manager import (
                VRIAssignmentManager,
            )

            self._vri_manager = VRIAssignmentManager.get_instance()
            self._vri_list = self._vri_manager.get_all_vri()

            if not self._vri_list:
                log_warning("Fsm_1_1_7: VRI.json пуст или не загружен")
                return False

            from Daman_QGIS.managers.validation.submodules.Msm_21_1_existing_vri_validator import (
                Msm_21_1_ExistingVRIValidator,
            )

            self._vri_validator = Msm_21_1_ExistingVRIValidator(self._vri_list)
            log_info(f"Fsm_1_1_7: VRI инициализирован ({len(self._vri_list)} записей)")
            return True

        except Exception as e:
            log_warning(f"Fsm_1_1_7: Ошибка инициализации VRI: {e}")
            return False

    def validate_layer(self, layer: QgsVectorLayer) -> Dict[str, Any]:
        """Валидация всех features в слое ЗПР.

        Args:
            layer: Слой ЗПР (GPKG)

        Returns:
            Dict с результатами: all_valid, total_features, invalid_features, valid_count
        """
        result: Dict[str, Any] = {
            'all_valid': True,
            'total_features': 0,
            'invalid_features': [],
            'valid_count': 0,
        }

        if not layer or not layer.isValid():
            log_warning("Fsm_1_1_7: Слой невалиден")
            return result

        # Проверяем наличие обязательных полей
        field_indices: Dict[str, int] = {}
        for field_name in self.ZPR_REQUIRED_FIELDS:
            idx = layer.fields().indexOf(field_name)
            if idx >= 0:
                field_indices[field_name] = idx
            else:
                log_warning(f"Fsm_1_1_7: Поле {field_name} отсутствует в слое {layer.name()}")

        if not field_indices:
            log_warning(f"Fsm_1_1_7: Ни одного обязательного поля в слое {layer.name()}")
            return result

        # Валидация каждого feature
        for feature in layer.getFeatures():
            result['total_features'] += 1

            invalid_info = self._validate_feature(feature, field_indices)
            if invalid_info:
                result['invalid_features'].append(invalid_info)
                result['all_valid'] = False
            else:
                result['valid_count'] += 1

        log_info(
            f"Fsm_1_1_7: Валидация слоя {layer.name()}: "
            f"{result['valid_count']}/{result['total_features']} валидных, "
            f"{len(result['invalid_features'])} невалидных"
        )

        return result

    def _validate_feature(
        self, feature: QgsFeature, field_indices: Dict[str, int]
    ) -> Optional[Dict[str, Any]]:
        """Валидация одного feature.

        Args:
            feature: Feature для проверки
            field_indices: Маппинг field_name -> index

        Returns:
            Dict с информацией о невалидных полях или None если feature валиден
        """
        invalid_fields: Dict[str, Dict[str, Any]] = {}

        for field_name, idx in field_indices.items():
            value = feature.attribute(idx)
            current_value = self._normalize_value(value)

            if field_name == 'VRI':
                # VRI: проверяем через Msm_21_1 soft_validate
                if self._is_empty(value):
                    invalid_fields[field_name] = {
                        'current_value': current_value,
                        'error': 'empty',
                    }
                elif self._vri_validator:
                    is_valid, _ = self._vri_validator.soft_validate(str(value).strip())
                    if not is_valid:
                        invalid_fields[field_name] = {
                            'current_value': current_value,
                            'error': 'invalid_vri',
                        }
            else:
                # ID, ID_KV, MIN_AREA_VRI: проверка на пустоту
                if self._is_empty(value):
                    invalid_fields[field_name] = {
                        'current_value': current_value,
                        'error': 'empty',
                    }

        if invalid_fields:
            return {
                'fid': feature.id(),
                'feature': feature,
                'invalid_fields': invalid_fields,
            }
        return None

    def _is_empty(self, value: Any) -> bool:
        """Проверка на пустоту/NULL.

        Args:
            value: Значение атрибута

        Returns:
            True если значение пустое
        """
        if value is None:
            return True
        if isinstance(value, QVariant) and value.isNull():
            return True
        str_value = str(value).strip()
        if str_value in self.EMPTY_VALUES:
            return True
        return False

    def _normalize_value(self, value: Any) -> Optional[str]:
        """Нормализация значения для отображения.

        Args:
            value: Значение атрибута

        Returns:
            Строковое значение или None
        """
        if value is None:
            return None
        if isinstance(value, QVariant) and value.isNull():
            return None
        str_value = str(value).strip()
        if str_value in self.EMPTY_VALUES:
            return None
        return str_value

    def apply_attributes(
        self,
        layer: QgsVectorLayer,
        updates: Dict[int, Dict[str, str]],
    ) -> Dict[str, Any]:
        """Batch-запись атрибутов в слой.

        Args:
            layer: Слой ЗПР (GPKG)
            updates: {fid: {field_name: new_value, ...}, ...}

        Returns:
            Dict: success, updated_count, errors
        """
        result: Dict[str, Any] = {
            'success': False,
            'updated_count': 0,
            'errors': [],
        }

        if not updates:
            result['success'] = True
            return result

        try:
            layer.startEditing()

            for fid, field_values in updates.items():
                for field_name, new_value in field_values.items():
                    field_idx = layer.fields().indexOf(field_name)
                    if field_idx < 0:
                        result['errors'].append(
                            f"Поле {field_name} не найдено в слое"
                        )
                        continue

                    if not layer.changeAttributeValue(fid, field_idx, new_value):
                        result['errors'].append(
                            f"Ошибка записи {field_name} для fid={fid}"
                        )
                    else:
                        result['updated_count'] += 1

            if layer.commitChanges():
                result['success'] = True
                log_info(
                    f"Fsm_1_1_7: Записано {result['updated_count']} атрибутов "
                    f"в слой {layer.name()}"
                )
            else:
                errors = layer.commitErrors()
                result['errors'].extend(errors)
                log_error(f"Fsm_1_1_7: Ошибка commit: {errors}")
                layer.rollBack()

        except Exception as e:
            log_error(f"Fsm_1_1_7: Ошибка записи атрибутов: {e}")
            result['errors'].append(str(e))
            try:
                layer.rollBack()
            except Exception:
                pass

        return result

    def run_validation_flow(
        self,
        layer: QgsVectorLayer,
        parent_widget: Any,
        iface: Any,
    ) -> Dict[str, Any]:
        """Главный метод: валидация -> серия диалогов -> запись.

        Args:
            layer: Слой ЗПР (GPKG, уже в проекте)
            parent_widget: Родительский виджет для диалогов
            iface: QGIS iface

        Returns:
            Dict: total_invalid, filled, skipped
        """
        stats: Dict[str, Any] = {
            'total_invalid': 0,
            'filled': 0,
            'skipped': 0,
        }

        # Инициализация VRI
        vri_ok = self._init_vri()
        if not vri_ok:
            log_warning(
                "Fsm_1_1_7: VRI не инициализирован, "
                "пропуск валидации атрибутов ЗПР"
            )
            return stats

        # Валидация
        validation = self.validate_layer(layer)
        if validation['all_valid']:
            log_info(
                f"Fsm_1_1_7: Все features слоя {layer.name()} валидны, "
                "GUI не требуется"
            )
            return stats

        invalid_features = validation['invalid_features']
        stats['total_invalid'] = len(invalid_features)

        # Импорт диалога
        from .Fsm_1_1_6_zpr_attribute_dialog import Fsm_1_1_6_ZprAttributeDialog

        # Собираем обновления
        updates: Dict[int, Dict[str, str]] = {}

        # Цикл по невалидным features
        total = len(invalid_features)
        for idx, invalid_info in enumerate(invalid_features):
            fid = invalid_info['fid']
            feature = invalid_info['feature']
            invalid_fields = invalid_info['invalid_fields']

            # Выделяем feature на карте
            try:
                iface.setActiveLayer(layer)
                layer.selectByIds([fid])
                iface.mapCanvas().zoomToSelected(layer)
            except Exception as e:
                log_warning(f"Fsm_1_1_7: Ошибка выделения feature {fid}: {e}")

            # Показываем диалог
            dialog = Fsm_1_1_6_ZprAttributeDialog(
                parent=parent_widget,
                feature=feature,
                invalid_fields=invalid_fields,
                vri_list=self._vri_list,
                current_index=idx + 1,
                total_count=total,
                layer_name=layer.name(),
            )

            dialog.exec()
            values, skipped, skip_all = dialog.get_result()

            if skip_all:
                # Пропустить все оставшиеся
                remaining = total - idx
                stats['skipped'] += remaining
                log_info(
                    f"Fsm_1_1_7: Пользователь пропустил все "
                    f"({remaining} оставшихся)"
                )
                break

            if skipped:
                stats['skipped'] += 1
            else:
                # Фильтруем пустые значения
                non_empty_values = {
                    k: v for k, v in values.items()
                    if v and str(v).strip()
                }
                if non_empty_values:
                    updates[fid] = non_empty_values
                    stats['filled'] += 1
                else:
                    # Пользователь нажал Применить но ничего не заполнил
                    stats['skipped'] += 1

        # Снимаем выделение
        try:
            layer.removeSelection()
        except Exception:
            pass

        # Batch-запись
        if updates:
            write_result = self.apply_attributes(layer, updates)
            if not write_result['success']:
                log_error(
                    f"Fsm_1_1_7: Ошибки записи: {write_result['errors']}"
                )

        log_info(
            f"Fsm_1_1_7: Итог валидации {layer.name()}: "
            f"невалидных {stats['total_invalid']}, "
            f"заполнено {stats['filled']}, "
            f"пропущено {stats['skipped']}"
        )

        return stats
