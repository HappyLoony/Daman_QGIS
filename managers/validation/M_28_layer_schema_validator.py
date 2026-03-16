# -*- coding: utf-8 -*-
"""
M_28_LayerSchemaValidator - Валидатор структуры слоёв

Проверяет наличие обязательных полей в критически важных слоях.
Валидирует только СТРУКТУРУ (наличие полей), НЕ значения.

Текущая реализация: схемы для ЗПР и лесных выделов (имена слоёв из constants.py).

Используется в:
- F_2_1 (нарезка) - перед нарезкой проверить структуру ЗПР
- F_2_3 (импорт DXF) - после импорта проверить структуру
"""

from typing import Dict, List, Optional, Tuple, Any

from qgis.core import QgsProject, QgsVectorLayer

from Daman_QGIS.constants import LAYERS_ZPR_ALL, LAYER_FOREST_VYDELY, CUTTING_PREFIXES
from Daman_QGIS.utils import log_info, log_warning, log_error

__all__ = ['LayerSchemaValidator']


class LayerSchemaValidator:
    """Валидатор структуры слоёв"""

    # Схемы слоёв (имена из constants.py)
    LAYER_SCHEMAS: Dict[str, Dict[str, Any]] = {
        'ZPR': {
            'description': 'Схема для слоёв ЗПР (зоны планируемого размещения)',
            'layers': list(LAYERS_ZPR_ALL),
            'required_fields': ['ID', 'ID_KV', 'VRI', 'MIN_AREA_VRI'],
        },
        'FOREST_VYDELY': {
            'description': 'Схема для слоя лесных выделов',
            'layers': [
                LAYER_FOREST_VYDELY,
            ],
            'required_fields': [],  # Загружаются динамически из Base_forest_vydely.json
            'dynamic_provider': 'forest_vydely',
        },
        'CUTTING': {
            'description': 'Схема для слоёв нарезки (Le_2_1_*, Le_2_2_*)',
            'required_fields': [],  # Загружаются динамически из Base_cutting.json
            'dynamic_provider': 'cutting',
            'prefix_match': CUTTING_PREFIXES,
        },
    }

    def __init__(self, plugin_dir: Optional[str] = None) -> None:
        """Инициализация валидатора

        Args:
            plugin_dir: Путь к папке плагина (для будущей загрузки JSON)
        """
        self._plugin_dir = plugin_dir

    def validate_layer(
        self,
        layer: Optional[QgsVectorLayer],
        schema_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Валидация структуры одного слоя

        Args:
            layer: Слой для проверки
            schema_name: Имя схемы (если None - определяется автоматически)

        Returns:
            Dict: {
                'valid': bool,
                'layer_name': str,
                'schema': str или None,
                'missing_fields': List[str],
                'present_fields': List[str],
                'error': str или None
            }
        """
        result = {
            'valid': False,
            'layer_name': layer.name() if layer is not None else 'Unknown',
            'schema': schema_name,
            'missing_fields': [],
            'present_fields': [],
            'error': None
        }

        if layer is None or not layer.isValid():
            result['error'] = 'Слой невалиден или не существует'
            return result

        layer_name = layer.name()

        # Определяем схему если не указана
        if not schema_name:
            schema_name = self._get_schema_for_layer(layer_name)
            result['schema'] = schema_name

        if not schema_name:
            result['error'] = f'Схема не найдена для слоя {layer_name}'
            return result

        schema = self.LAYER_SCHEMAS.get(schema_name)
        if not schema:
            result['error'] = f'Схема {schema_name} не существует'
            return result

        # Получаем поля слоя
        field_names = [f.name() for f in layer.fields()]
        result['present_fields'] = field_names

        # Проверяем обязательные поля
        # Для динамических провайдеров получаем имена полей из провайдера
        typed_fields = self._get_typed_fields(schema_name)
        if typed_fields is not None:
            required_fields = [f["name"] for f in typed_fields]
        else:
            required_fields = schema.get('required_fields', [])
        field_names_lower = {f.lower() for f in field_names}
        missing = [f for f in required_fields if f.lower() not in field_names_lower]
        result['missing_fields'] = missing

        result['valid'] = len(missing) == 0

        if result['valid']:
            log_info(f"M_28: Слой {layer_name} соответствует схеме {schema_name}")
        else:
            log_warning(f"M_28: Слой {layer_name} не соответствует схеме {schema_name}, "
                       f"отсутствуют поля: {', '.join(missing)}")

        return result

    def validate_layer_by_name(
        self,
        layer_name: str,
        schema_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Валидация слоя по имени

        Args:
            layer_name: Имя слоя в проекте
            schema_name: Имя схемы (опционально)

        Returns:
            Dict: Результат валидации
        """
        project = QgsProject.instance()
        layers = project.mapLayersByName(layer_name)

        if not layers:
            return {
                'valid': False,
                'layer_name': layer_name,
                'schema': schema_name,
                'missing_fields': [],
                'present_fields': [],
                'error': f'Слой {layer_name} не найден в проекте'
            }

        layer = layers[0]
        if not isinstance(layer, QgsVectorLayer):
            return {
                'valid': False,
                'layer_name': layer_name,
                'schema': schema_name,
                'missing_fields': [],
                'present_fields': [],
                'error': f'Слой {layer_name} не является векторным'
            }

        return self.validate_layer(layer, schema_name)

    def validate_schema_group(
        self,
        schema_name: str,
        only_existing: bool = True
    ) -> Dict[str, Any]:
        """Валидация всех слоёв группы (схемы)

        Args:
            schema_name: Имя схемы (например 'ZPR')
            only_existing: Проверять только существующие слои

        Returns:
            Dict: {
                'valid': bool - все слои валидны,
                'schema': str,
                'total_layers': int,
                'checked_layers': int,
                'valid_layers': List[str],
                'invalid_layers': List[Dict] - с деталями ошибок,
                'missing_layers': List[str] - если only_existing=False
            }
        """
        result = {
            'valid': True,
            'schema': schema_name,
            'total_layers': 0,
            'checked_layers': 0,
            'valid_layers': [],
            'invalid_layers': [],
            'missing_layers': []
        }

        schema = self.LAYER_SCHEMAS.get(schema_name)
        if not schema:
            result['valid'] = False
            log_error(f"M_28: Схема {schema_name} не существует")
            return result

        layer_names = schema.get('layers', [])
        result['total_layers'] = len(layer_names)

        project = QgsProject.instance()

        for layer_name in layer_names:
            layers = project.mapLayersByName(layer_name)

            if not layers:
                if not only_existing:
                    result['missing_layers'].append(layer_name)
                continue

            layer = layers[0]
            if not isinstance(layer, QgsVectorLayer):
                result['invalid_layers'].append({
                    'layer_name': layer_name,
                    'missing_fields': [],
                    'error': f'Слой {layer_name} не является векторным'
                })
                continue
            validation = self.validate_layer(layer, schema_name)
            result['checked_layers'] += 1

            if validation['valid']:
                result['valid_layers'].append(layer_name)
            else:
                result['invalid_layers'].append({
                    'layer_name': layer_name,
                    'missing_fields': validation['missing_fields'],
                    'error': validation.get('error')
                })
                result['valid'] = False

        log_info(f"M_28: Валидация группы {schema_name}: "
                f"проверено {result['checked_layers']}/{result['total_layers']}, "
                f"валидных {len(result['valid_layers'])}, "
                f"невалидных {len(result['invalid_layers'])}")

        return result

    def validate_zpr_layers(self, only_existing: bool = True) -> Dict[str, Any]:
        """Валидация всех слоёв ЗПР

        Удобный метод для проверки группы ЗПР.

        Args:
            only_existing: Проверять только существующие слои

        Returns:
            Dict: Результат валидации группы ZPR
        """
        return self.validate_schema_group('ZPR', only_existing)

    def get_missing_fields(
        self,
        layer: QgsVectorLayer,
        schema_name: Optional[str] = None
    ) -> List[str]:
        """Получить список недостающих полей

        Args:
            layer: Слой для проверки
            schema_name: Имя схемы (опционально)

        Returns:
            List[str]: Список имён недостающих полей
        """
        result = self.validate_layer(layer, schema_name)
        return result.get('missing_fields', [])

    def get_required_fields(self, schema_name: str) -> List[str]:
        """Получить список обязательных полей для схемы

        Args:
            schema_name: Имя схемы

        Returns:
            List[str]: Список обязательных полей
        """
        # Для динамических провайдеров получаем имена из провайдера
        typed_fields = self._get_typed_fields(schema_name)
        if typed_fields is not None:
            return [f["name"] for f in typed_fields]

        schema = self.LAYER_SCHEMAS.get(schema_name)
        if not schema:
            return []
        return schema.get('required_fields', [])

    def _get_schema_for_layer(self, layer_name: str) -> Optional[str]:
        """Определить схему по имени слоя

        Поддерживает два режима:
        - Точное совпадение по списку layers
        - Совпадение по префиксу через prefix_match

        Args:
            layer_name: Имя слоя

        Returns:
            str: Имя схемы или None
        """
        for schema_name, schema in self.LAYER_SCHEMAS.items():
            if layer_name in schema.get('layers', []):
                return schema_name

            prefix_match = schema.get('prefix_match')
            if prefix_match and layer_name.startswith(prefix_match):
                return schema_name

        return None

    def format_validation_message(
        self,
        validation_result: Dict[str, Any],
        include_present: bool = False
    ) -> str:
        """Форматирование результата валидации в читаемое сообщение

        Args:
            validation_result: Результат от validate_layer
            include_present: Включить список существующих полей

        Returns:
            str: Отформатированное сообщение
        """
        layer_name = validation_result.get('layer_name', 'Unknown')
        schema = validation_result.get('schema', 'Unknown')

        if validation_result.get('error'):
            return f"Ошибка валидации {layer_name}: {validation_result['error']}"

        if validation_result.get('valid'):
            return f"Слой {layer_name} соответствует схеме {schema}"

        missing = validation_result.get('missing_fields', [])
        msg = f"Слой {layer_name} не соответствует схеме {schema}.\n"
        msg += f"Отсутствуют обязательные поля: {', '.join(missing)}"

        if include_present:
            present = validation_result.get('present_fields', [])
            msg += f"\nСуществующие поля: {', '.join(present)}"

        return msg

    def ensure_required_fields(
        self,
        layer: QgsVectorLayer,
        schema_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Добавление недостающих обязательных полей в слой

        Проверяет наличие обязательных полей по схеме и создаёт
        отсутствующие поля как пустые (NULL значения).
        Существующие поля НЕ модифицируются.

        Используется при импорте DXF/TAB для слоёв ЗПР, чтобы
        обеспечить совместимость с F_2_1 (нарезка).

        Args:
            layer: Слой для дополнения полей
            schema_name: Имя схемы (если None - определяется автоматически)

        Returns:
            Dict: {
                'success': bool,
                'layer_name': str,
                'schema': str или None,
                'fields_added': List[str],
                'error': str или None
            }
        """
        from qgis.PyQt.QtCore import QMetaType
        from qgis.core import QgsField

        result = {
            'success': False,
            'layer_name': layer.name() if layer else 'Unknown',
            'schema': schema_name,
            'fields_added': [],
            'error': None
        }

        if not layer or not layer.isValid():
            result['error'] = 'Слой невалиден или не существует'
            return result

        layer_name = layer.name()

        # Определяем схему если не указана
        if not schema_name:
            schema_name = self._get_schema_for_layer(layer_name)
            result['schema'] = schema_name

        # Если схема не найдена - слой не требует дополнения полей
        if not schema_name:
            result['success'] = True
            log_info(f"M_28: Слой {layer_name} не имеет схемы, дополнение полей не требуется")
            return result

        schema = self.LAYER_SCHEMAS.get(schema_name)
        if not schema:
            result['success'] = True
            log_info(f"M_28: Схема {schema_name} не существует, дополнение полей не требуется")
            return result

        # Получаем текущие поля слоя
        existing_fields = [f.name() for f in layer.fields()]

        # Проверяем наличие динамического провайдера (типизированные поля)
        typed_fields = self._get_typed_fields(schema_name)

        if typed_fields is not None:
            # Динамический провайдер: поля с типами
            # Проверка конфликта типов: имя совпало, тип отличается
            # Case-insensitive: GeoPackage (SQLite) не различает регистр имён полей
            existing_field_map = {f.name().lower(): f for f in layer.fields()}
            missing_typed = []
            for field_def in typed_fields:
                name = field_def["name"]
                if name.lower() not in existing_field_map:
                    missing_typed.append(field_def)
                else:
                    existing_field = existing_field_map[name.lower()]
                    if existing_field.type() != field_def["type"]:
                        log_warning(
                            f"M_28: Поле '{name}' в слое {layer_name} имеет тип "
                            f"{existing_field.typeName()}, ожидается "
                            f"{'Int' if field_def['type'] == QMetaType.Type.Int else 'String'}"
                        )

            if not missing_typed:
                result['success'] = True
                log_info(f"M_28: Слой {layer_name} имеет все обязательные поля")
                return result

            missing_names = [f["name"] for f in missing_typed]
            log_info(f"M_28: Слой {layer_name} - добавляем поля: {', '.join(missing_names)}")

            try:
                layer.startEditing()

                for field_def in missing_typed:
                    field = QgsField(field_def["name"], field_def["type"], len=field_def["length"])
                    layer.addAttribute(field)
                    result['fields_added'].append(field_def["name"])
                    log_info(f"M_28: Добавлено поле '{field_def['name']}' в слой {layer_name}")

                layer.commitChanges()
                result['success'] = True
                log_info(f"M_28: Слой {layer_name} дополнен полями: {', '.join(result['fields_added'])}")

            except Exception as e:
                layer.rollBack()
                result['error'] = str(e)
                log_error(f"M_28: Ошибка добавления полей в слой {layer_name}: {e}")

        else:
            # Статическая схема (ZPR): все поля String(254)
            # Case-insensitive: GeoPackage (SQLite) не различает регистр имён полей
            required_fields = schema.get('required_fields', [])
            existing_lower = {f.lower() for f in existing_fields}
            missing_fields = [f for f in required_fields if f.lower() not in existing_lower]

            if not missing_fields:
                result['success'] = True
                log_info(f"M_28: Слой {layer_name} имеет все обязательные поля")
                return result

            log_info(f"M_28: Слой {layer_name} - добавляем поля: {', '.join(missing_fields)}")

            try:
                layer.startEditing()

                for field_name in missing_fields:
                    field = QgsField(field_name, QMetaType.Type.QString, len=254)
                    layer.addAttribute(field)
                    result['fields_added'].append(field_name)
                    log_info(f"M_28: Добавлено поле '{field_name}' в слой {layer_name}")

                layer.commitChanges()
                result['success'] = True
                log_info(f"M_28: Слой {layer_name} дополнен полями: {', '.join(result['fields_added'])}")

            except Exception as e:
                layer.rollBack()
                result['error'] = str(e)
                log_error(f"M_28: Ошибка добавления полей в слой {layer_name}: {e}")

        return result

    def _get_typed_fields(self, schema_name: str) -> Optional[List[Dict[str, Any]]]:
        """Получить типизированные поля из динамического провайдера.

        Для FOREST_VYDELY: загружает из ForestVydelySchemaProvider.
        Для остальных: возвращает None (используется стандартная логика String 254).

        Args:
            schema_name: Имя схемы

        Returns:
            Список [{"name": str, "type": QMetaType.Type, "length": int}]
            или None если провайдер не задан
        """
        schema = self.LAYER_SCHEMAS.get(schema_name)
        if not schema:
            return None

        provider_key = schema.get('dynamic_provider')
        if not provider_key:
            return None

        if provider_key == 'forest_vydely':
            try:
                from Daman_QGIS.managers.validation.submodules.Msm_28_1_forest_vydely_schema import (
                    ForestVydelySchemaProvider,
                )
                provider = ForestVydelySchemaProvider()
                return provider.get_required_fields()
            except Exception as e:
                log_error(f"M_28: Ошибка загрузки провайдера forest_vydely: {e}")
                return None

        if provider_key == 'cutting':
            try:
                from Daman_QGIS.managers.validation.submodules.Msm_28_2_cutting_schema import (
                    CuttingSchemaProvider,
                )
                provider = CuttingSchemaProvider()
                return provider.get_required_fields()
            except Exception as e:
                log_error(f"M_28: Ошибка загрузки провайдера cutting: {e}")
                return None

        return None

    def is_layer_in_schema(self, layer_name: str, schema_name: str) -> bool:
        """Проверить, принадлежит ли слой к схеме

        Поддерживает точное совпадение по layers и prefix_match.

        Args:
            layer_name: Имя слоя
            schema_name: Имя схемы

        Returns:
            bool: True если слой принадлежит схеме
        """
        schema = self.LAYER_SCHEMAS.get(schema_name)
        if not schema:
            return False

        if layer_name in schema.get('layers', []):
            return True

        prefix_match = schema.get('prefix_match')
        if prefix_match and layer_name.startswith(prefix_match):
            return True

        return False
