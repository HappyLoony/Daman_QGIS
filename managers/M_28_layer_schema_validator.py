# -*- coding: utf-8 -*-
"""
M_28_LayerSchemaValidator - Валидатор структуры слоёв

Проверяет наличие обязательных полей в критически важных слоях.
Валидирует только СТРУКТУРУ (наличие полей), НЕ значения.

Текущая реализация: хардкод схем для ЗПР слоёв.

TODO: При увеличении количества схем (5+ групп слоёв) целесообразно:
1. Создать Base_layer_schemas.json в data/reference/
2. Перенести схемы из LAYER_SCHEMAS в JSON
3. Добавить метод _load_schemas() для загрузки JSON

Структура JSON:
{
  "schemas": {
    "ZPR": {
      "description": "Схема для слоёв ЗПР",
      "layers": ["L_2_4_1_ЗПР_ОКС", ...],
      "required_fields": ["ID", "ID_KV", "VRI", "MIN_AREA_VRI"]
    }
  }
}

НЕ добавлять:
- Типы полей (QGIS сам знает типы, валидируем только наличие)
- optional_fields (опциональные поля не валидируются)
- layer_pattern (сложно реализовать, явный список проще)

Используется в:
- F_3_1 (нарезка) - перед нарезкой проверить структуру ЗПР
- F_2_3 (импорт DXF) - после импорта проверить структуру
"""

from typing import Dict, List, Optional, Tuple, Any

from qgis.core import QgsProject, QgsVectorLayer

from Daman_QGIS.utils import log_info, log_warning, log_error


class LayerSchemaValidator:
    """Валидатор структуры слоёв"""

    # Схемы слоёв (хардкод)
    # TODO: При 5+ схемах перенести в Base_layer_schemas.json
    LAYER_SCHEMAS: Dict[str, Dict[str, Any]] = {
        'ZPR': {
            'description': 'Схема для слоёв ЗПР (зоны планируемого размещения)',
            'layers': [
                # Основные ЗПР (L_2_4_*)
                'L_2_4_1_ЗПР_ОКС',
                'L_2_4_2_ЗПР_ПО',
                'L_2_4_3_ЗПР_ВО',
                # Рекреационные ЗПР (L_2_5_*)
                'L_2_5_1_ЗПР_РЕК_АД',
                'L_2_5_2_ЗПР_СЕТИ_ПО',
                'L_2_5_3_ЗПР_СЕТИ_ВО',
                'L_2_5_4_ЗПР_НЭ',
            ],
            'required_fields': ['ID', 'ID_KV', 'VRI', 'MIN_AREA_VRI'],
        },
        # TODO: Добавить другие схемы при необходимости
        # 'CUTTING_RAZDEL': {...},
        # 'EGRN': {...},
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
        required_fields = schema.get('required_fields', [])
        missing = [f for f in required_fields if f not in field_names]
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
        schema = self.LAYER_SCHEMAS.get(schema_name)
        if not schema:
            return []
        return schema.get('required_fields', [])

    def _get_schema_for_layer(self, layer_name: str) -> Optional[str]:
        """Определить схему по имени слоя

        Args:
            layer_name: Имя слоя

        Returns:
            str: Имя схемы или None
        """
        for schema_name, schema in self.LAYER_SCHEMAS.items():
            if layer_name in schema.get('layers', []):
                return schema_name

        # Проверка по паттерну (для будущего расширения)
        # TODO: Добавить поддержку layer_pattern при переходе на JSON

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
