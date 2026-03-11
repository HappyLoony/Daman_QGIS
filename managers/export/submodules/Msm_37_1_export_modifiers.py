# -*- coding: utf-8 -*-
"""
Msm_37_1 - Модификаторы экспорта

Базовый класс ExportModifier и конкретные реализации.
Модификаторы трансформируют список экспортных задач ДО выполнения экспорта.

Паттерн: Modifier Chain — каждый модификатор получает список items
и возвращает (возможно расширенный/изменённый) список items.

Регистрация модификаторов: REGION_EXPORT_MODIFIERS[код_региона] = [модификаторы]
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional

from qgis.core import QgsVectorLayer, QgsFeature, QgsWkbTypes

from Daman_QGIS.utils import log_info, log_warning, log_error


class ExportModifier(ABC):
    """
    Базовый класс модификатора экспорта.

    Каждый модификатор получает список экспортных задач (items) и метаданные проекта,
    и возвращает трансформированный список. Модификатор может:
    - Расширить список (split: 1 item -> N items)
    - Изменить параметры items (filename, context)
    - Отфильтровать items
    - Оставить без изменений
    """

    @abstractmethod
    def modify_export_items(
        self,
        items: List[Dict[str, Any]],
        metadata: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Трансформировать список экспортных задач.

        Args:
            items: Список задач [{layer, template, extra_context?}, ...]
            metadata: Метаданные проекта из _metadata таблицы

        Returns:
            Трансформированный список задач
        """
        pass


class SplitByFeatureModifier(ExportModifier):
    """
    Разделяет экспорт на отдельные файлы по feature.

    Для указанных template_ids каждый feature слоя экспортируется
    в отдельный файл. Именование: ЗУ_1, ЗУ_2, ...

    Создаёт memory layer с одной feature для каждого элемента.
    Memory layer не добавляется в проект QGIS.
    """

    def __init__(self, template_ids: List[str]):
        """
        Args:
            template_ids: ID шаблонов, к которым применяется разделение
        """
        self.template_ids = template_ids

    def modify_export_items(
        self,
        items: List[Dict[str, Any]],
        metadata: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Разделить items с matching template_ids на per-feature items."""
        result: List[Dict[str, Any]] = []

        for item in items:
            template = item['template']

            if template.template_id not in self.template_ids:
                result.append(item)
                continue

            layer = item['layer']
            feature_count = layer.featureCount()

            if feature_count <= 0:
                log_warning(
                    f"Msm_37_1: Слой {layer.name()} пуст, пропуск split"
                )
                result.append(item)
                continue

            log_info(
                f"Msm_37_1: Split по feature для '{layer.name()}' "
                f"({feature_count} features, template={template.template_id})"
            )

            for idx, feature in enumerate(layer.getFeatures(), 1):
                mem_layer = self._create_single_feature_layer(layer, feature)
                if mem_layer is None:
                    log_warning(
                        f"Msm_37_1: Не удалось создать memory layer "
                        f"для feature {idx} слоя {layer.name()}"
                    )
                    continue

                # ID из атрибутов (привязан к документации)
                feature_id = feature.attribute('ID')
                if not feature_id:
                    log_error(
                        f"Msm_37_1: Пустое поле ID у feature {idx} "
                        f"слоя {layer.name()}, пропуск"
                    )
                    continue

                feature_name = f"ЗУ_{feature_id}"

                result.append({
                    'layer': mem_layer,
                    'template': template,
                    'extra_context': {
                        'feature_name': feature_name,
                        'feature_index': feature_id,
                        'split_by_feature': True,
                        'source_layer_name': layer.name(),
                    }
                })

            log_info(
                f"Msm_37_1: Слой '{layer.name()}' разделён "
                f"на {feature_count} экспортных задач"
            )

        return result

    def _create_single_feature_layer(
        self,
        source_layer: QgsVectorLayer,
        feature: QgsFeature
    ) -> Optional[QgsVectorLayer]:
        """
        Создать memory layer с одной feature.

        Args:
            source_layer: Исходный слой (для CRS и полей)
            feature: Feature для копирования

        Returns:
            Memory layer с одной feature или None при ошибке
        """
        try:
            geom_type_str = QgsWkbTypes.displayString(source_layer.wkbType())
            crs_id = source_layer.crs().authid()

            uri = f"{geom_type_str}?crs={crs_id}"
            mem_layer = QgsVectorLayer(uri, "split_feature", "memory")

            if not mem_layer.isValid():
                log_error("Msm_37_1: Не удалось создать memory layer")
                return None

            provider = mem_layer.dataProvider()
            if provider is None:
                return None

            # Копируем структуру полей
            provider.addAttributes(source_layer.fields().toList())
            mem_layer.updateFields()

            # Добавляем feature
            success = provider.addFeature(feature)
            if not success:
                log_error("Msm_37_1: Не удалось добавить feature в memory layer")
                return None

            return mem_layer

        except Exception as e:
            log_error(f"Msm_37_1: Ошибка создания memory layer: {e}")
            return None


class Region78FormatModifier(ExportModifier):
    """
    Формат перечней координат для региона 78 (СПб).

    Применяется ПОСЛЕ SplitByFeatureModifier в цепочке модификаторов.
    Устанавливает в extra_context флаги для SPB-формата Excel:
    - spb_format: True -- 3-колоночный формат без приложения/CRS
    - close_contours: False -- не замыкать контуры
    - title_override: готовая строка шапки документа
    - show_area: True -- показывать S= в конце
    """

    # Маппинг template_id -> описание объекта в шапке (для специфичных шаблонов).
    # Для generic шаблонов (coord_cutting_lo, coord_cutting_vo, ...)
    # дескриптор определяется по имени слоя через _get_descriptor().
    OBJECT_DESCRIPTOR_MAP: Dict[str, str] = {
        'coord_cutting_oks_razdel': 'границ земельного участка',
        'coord_cutting_oks_ngs': 'границ земельного участка',
        'coord_cutting_oks_ps': 'контура публичного сервитута',
    }

    # Дескриптор по умолчанию (ОЗУ = образуемый земельный участок)
    DEFAULT_DESCRIPTOR = 'границ земельного участка'

    # Дескриптор для ПС (публичный сервитут)
    PS_DESCRIPTOR = 'контура публичного сервитута'

    # Тип объекта -> фраза размещения (множественное число)
    PLACEMENT_PHRASE_MAP: Dict[str, str] = {
        'Линейный': 'линейных объектов',
        'Площадной': 'объектов капитального строительства',
    }

    # Тип объекта -> фраза размещения (единственное число)
    PLACEMENT_PHRASE_MAP_SINGULAR: Dict[str, str] = {
        'Линейный': 'линейного объекта',
        'Площадной': 'объекта капитального строительства',
    }

    # Значение -> склонение для "...ого значения"
    SIGNIFICANCE_MAP: Dict[str, str] = {
        'Федеральный': 'федерального',
        'Региональный': 'регионального',
        'Местный': 'местного',
    }

    def __init__(self, template_ids: List[str]):
        """
        Args:
            template_ids: ID шаблонов, к которым применяется SPB формат
        """
        self.template_ids = template_ids

    def modify_export_items(
        self,
        items: List[Dict[str, Any]],
        metadata: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Установить SPB-формат для matching items."""
        result: List[Dict[str, Any]] = []
        # Счётчики по слоям для summary лога
        layer_counts: Dict[str, int] = {}

        for item in items:
            template = item['template']

            if template.template_id not in self.template_ids:
                result.append(item)
                continue

            extra_context = dict(item.get('extra_context', {}))
            feature_index = extra_context.get('feature_index', 1)
            # source_layer_name от SplitByFeature, иначе текущий слой
            layer_name = extra_context.get(
                'source_layer_name',
                item['layer'].name() if item.get('layer') else ''
            )

            title = self._build_title(
                template.template_id, feature_index, metadata, layer_name
            )

            extra_context['spb_format'] = True
            extra_context['close_contours'] = False
            extra_context['show_area'] = True
            extra_context['title_override'] = title
            extra_context['filename_override'] = self._build_filename(
                template.template_id, feature_index, layer_name
            )
            extra_context['subfolder'] = (
                'Публичные сервитуты'
                if self._is_ps(template.template_id, layer_name)
                else 'Земельные участки'
            )

            result.append({
                'layer': item['layer'],
                'template': template,
                'extra_context': extra_context,
            })

            layer_counts[layer_name] = layer_counts.get(layer_name, 0) + 1

        # Summary лог вместо per-item
        if layer_counts:
            parts = [f"{count} из {name}" for name, count in layer_counts.items()]
            log_info(f"Msm_37_1: SPB формат применён: {', '.join(parts)}")

        return result

    def _get_descriptor(self, template_id: str, layer_name: str) -> str:
        """
        Определить дескриптор объекта для заголовка.

        Приоритет:
        1. OBJECT_DESCRIPTOR_MAP по template_id (для специфичных шаблонов OKS)
        2. Имя слоя содержит 'ПС' -> контура публичного сервитута
        3. По умолчанию -> границ земельного участка

        Args:
            template_id: ID шаблона
            layer_name: Имя слоя (для generic шаблонов)

        Returns:
            Строка дескриптора
        """
        # Специфичный шаблон (OKS с суффиксом razdel/ngs/ps)
        if template_id in self.OBJECT_DESCRIPTOR_MAP:
            return self.OBJECT_DESCRIPTOR_MAP[template_id]

        # Generic шаблон — определяем по имени слоя
        if '_ПС' in layer_name or layer_name.endswith('_ПС'):
            return self.PS_DESCRIPTOR

        return self.DEFAULT_DESCRIPTOR

    def _build_title(
        self,
        template_id: str,
        feature_index: int,
        metadata: Dict[str, Any],
        layer_name: str = ''
    ) -> str:
        """
        Сформировать заголовок документа для SPB формата.

        Формат:
          ПЕРЕЧЕНЬ
          координат характерных точек {descriptor} N {N}
          территории для размещения {placement} {significance} значения
          «{full_name}»

        Args:
            template_id: ID шаблона (для определения типа объекта)
            feature_index: Номер объекта (от SplitByFeature)
            metadata: Метаданные проекта из _metadata таблицы
            layer_name: Имя слоя (для определения дескриптора в generic шаблонах)

        Returns:
            Строка заголовка с переносами строк
        """
        descriptor = self._get_descriptor(template_id, layer_name)

        full_name = metadata.get('1_1_full_name', '')

        # Единственное/множественное число из метаданных
        is_single = metadata.get('1_7_is_single_object', 'Да') == 'Да'
        phrase_map = self.PLACEMENT_PHRASE_MAP_SINGULAR if is_single else self.PLACEMENT_PHRASE_MAP

        # _name ключи содержат русские наименования (Линейный/Площадной)
        object_type_name = metadata.get('1_2_object_type_name', '')
        placement = phrase_map.get(object_type_name, '')

        significance_name = metadata.get('1_2_1_object_type_value_name', '')
        significance = self.SIGNIFICANCE_MAP.get(significance_name, '')

        # Собираем фразу размещения
        placement_parts = []
        if placement:
            placement_parts.append(placement)
        if significance:
            placement_parts.append(f"{significance} значения")
        placement_phrase = ' '.join(placement_parts)

        title = (
            f"ПЕРЕЧЕНЬ\n"
            f"координат характерных точек {descriptor} "
            f"\u2116 {feature_index} "
            f"территории для размещения {placement_phrase} "
            f"\u00ab{full_name}\u00bb"
        )

        return title

    def _is_ps(self, template_id: str, layer_name: str) -> bool:
        """Проверить, является ли объект публичным сервитутом."""
        if template_id == 'coord_cutting_oks_ps':
            return True
        if '_ПС' in layer_name or layer_name.endswith('_ПС'):
            return True
        return False

    def _build_filename(
        self,
        template_id: str,
        feature_index: int,
        layer_name: str
    ) -> str:
        """
        Сформировать имя файла для SPB формата.

        Args:
            template_id: ID шаблона
            feature_index: Номер объекта
            layer_name: Имя исходного слоя

        Returns:
            Имя файла без расширения
        """
        if self._is_ps(template_id, layer_name):
            return f"Перечень_координат_{feature_index}_публичного_сервитута"
        return f"Перечень_координат_{feature_index}_участка_зу"


# === Конфигурация модификаторов по регионам ===

# Все шаблоны нарезок (Le_2_1_* и Le_2_2_*) для региона 78.
# coord_cutting_oks_izm ИСКЛЮЧЁН — не координируется (только атрибутивные изменения).
_REGION_78_CUTTING_TEMPLATE_IDS = [
    # OKS (Le_2_1_1_*)
    'coord_cutting_oks_razdel',
    'coord_cutting_oks_ngs',
    'coord_cutting_oks_ps',
    # ЗПР подтипы (Le_2_1_2_*, Le_2_1_3_*)
    'coord_cutting_lo',       # Le_2_1_2_* (ПО)
    'coord_cutting_vo',       # Le_2_1_3_* (ВО)
    # Сети и прочие (Le_2_2_*)
    'coord_cutting_rek_ad',   # Le_2_2_1_* (РЕК АД)
    'coord_cutting_seti_po',  # Le_2_2_2_* (СЕТИ ПО)
    'coord_cutting_seti_vo',  # Le_2_2_3_* (СЕТИ ВО)
    'coord_cutting_ne',       # Le_2_2_4_* (НЭ)
]

REGION_EXPORT_MODIFIERS: Dict[str, List[ExportModifier]] = {
    '78': [
        SplitByFeatureModifier(
            template_ids=_REGION_78_CUTTING_TEMPLATE_IDS,
        ),
        Region78FormatModifier(
            template_ids=_REGION_78_CUTTING_TEMPLATE_IDS,
        ),
    ],
}
