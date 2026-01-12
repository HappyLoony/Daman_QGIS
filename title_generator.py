# -*- coding: utf-8 -*-
"""
Генератор названий схем и слоев на основе метаданных проекта.

Формирует названия согласно шаблонам:
- Заголовки схем (для компоновок)
- Названия слоев границ работ
- Другие текстовые элементы чертежей

Используемые метаданные:
- 1_1_full_name: Полное наименование объекта
- 1_2_object_type: Тип объекта (Линейный/Площадной)
- 1_2_1_object_type_value: Значение линейного объекта (Федеральный/Региональный/Местный)
- 1_5_doc_type: Тип документации (ДПТ/Мастер-план)
- 1_6_stage: Этап разработки (Первичная/Внесение изменений)
"""

from typing import Dict, Any, Optional


class TitleGenerator:
    """Генератор названий на основе метаданных проекта"""

    # Словари маппинга значений метаданных на текстовые фрагменты
    STAGE_MAP = {
        "Первичная": "разработка",
        "Внесение изменений": "внесение изменений в"
    }

    # Маппинг для СХЕМ (родительный падеж)
    DOC_TYPE_MAP_SCHEME = {
        "ДПТ": {
            "Первичная": "документации по планировке территории",
            "Внесение изменений": "документации по планировке территории"
        },
        "Мастер-план": {
            "Первичная": "мастер-план(а)",
            "Внесение изменений": "мастер-план"
        }
    }

    # Маппинг для СЛОЕВ ГРАНИЦ (именительный падеж)
    DOC_TYPE_MAP_LAYER = {
        "ДПТ": {
            "Первичная": "документация по планировке территории",
            "Внесение изменений": "документация по планировке территории"
        },
        "Мастер-план": {
            "Первичная": "мастер-план",
            "Внесение изменений": "мастер-план"
        }
    }

    OBJECT_TYPE_MAP = {
        "Линейный": "для размещения линейного объекта",
        "Площадной": "с целью размещения объекта"
    }

    OBJECT_VALUE_MAP = {
        "Федеральный": "федерального",
        "Региональный": "регионального",
        "Местный": "местного"
    }

    def __init__(self):
        """Инициализация генератора"""
        pass

    def generate_scheme_title(self, metadata: Dict[str, Any]) -> str:
        """
        Сгенерировать название схемы для компоновки

        Шаблон:
        Схема границ территории, применительно к которой осуществляется
        {stage_text} {doc_text} {object_text} {object_value_text} {full_name}

        Args:
            metadata: Словарь метаданных проекта с ключами:
                - 1_1_full_name: Полное название объекта
                - 1_2_object_type: "Линейный" или "Площадной"
                - 1_2_1_object_type_value: "Федеральный"/"Региональный"/"Местный" (только для линейных)
                - 1_5_doc_type: "ДПТ" или "Мастер-план"
                - 1_6_stage: "Первичная" или "Внесение изменений"

        Returns:
            Полное название схемы

        Examples:
            >>> metadata = {
            ...     "1_1_full_name": '"Эльбрус благоустройство"',
            ...     "1_2_object_type": "Площадной",
            ...     "1_2_1_object_type_value": "-",
            ...     "1_5_doc_type": "ДПТ",
            ...     "1_6_stage": "Первичная"
            ... }
            >>> generator = TitleGenerator()
            >>> generator.generate_scheme_title(metadata)
            'Схема границ территории, применительно к которой осуществляется разработка документации по планировке территории с целью размещения объекта "Эльбрус благоустройство"'
        """
        # Извлекаем значения из метаданных
        full_name = metadata.get("1_1_full_name", "")
        object_type = metadata.get("1_2_object_type", "Площадной")
        object_type_value = metadata.get("1_2_1_object_type_value", "-")
        doc_type = metadata.get("1_5_doc_type", "ДПТ")
        stage = metadata.get("1_6_stage", "Первичная")

        # Формируем части заголовка

        # 1. Стадия
        stage_text = self.STAGE_MAP.get(stage, "разработка")

        # 2. Тип документа (зависит от стадии) - СХЕМА использует родительный падеж
        doc_map = self.DOC_TYPE_MAP_SCHEME.get(doc_type, self.DOC_TYPE_MAP_SCHEME["ДПТ"])
        doc_text = doc_map.get(stage, doc_map["Первичная"])

        # 3. Тип объекта
        object_text = self.OBJECT_TYPE_MAP.get(object_type, self.OBJECT_TYPE_MAP["Площадной"])

        # 4. Для линейных добавляем значение (федерального/регионального/местного значения)
        if object_type == "Линейный" and object_type_value and object_type_value != "-":
            value_text = self.OBJECT_VALUE_MAP.get(object_type_value, object_type_value.lower())
            object_text += f" {value_text} значения"

        # Формируем полный текст
        # ВАЖНО: full_name НЕ оборачиваем в кавычки - они уже включены в значение от пользователя
        title = (
            f"Схема границ территории, применительно к которой осуществляется "
            f"{stage_text} {doc_text} {object_text} "
            f"{full_name}"
        )

        return title

    def generate_boundary_layer_title(self, metadata: Dict[str, Any]) -> str:
        """
        Сгенерировать название слоя границ работ

        Шаблон:
        Границы территории, применительно к которой осуществляется
        {stage_text} {doc_text}

        Args:
            metadata: Словарь метаданных проекта с ключами:
                - 1_5_doc_type: "ДПТ" или "Мастер-план"
                - 1_6_stage: "Первичная" или "Внесение изменений"

        Returns:
            Название слоя границ работ

        Examples:
            >>> metadata = {
            ...     "1_5_doc_type": "ДПТ",
            ...     "1_6_stage": "Первичная"
            ... }
            >>> generator = TitleGenerator()
            >>> generator.generate_boundary_layer_title(metadata)
            'Границы территории, применительно к которой осуществляется разработка документации по планировке территории'

            >>> metadata = {
            ...     "1_5_doc_type": "Мастер-план",
            ...     "1_6_stage": "Внесение изменений"
            ... }
            >>> generator.generate_boundary_layer_title(metadata)
            'Границы территории, применительно к которой осуществляется внесение изменения в мастер-план'
        """
        # Извлекаем значения из метаданных
        doc_type = metadata.get("1_5_doc_type", "ДПТ")
        stage = metadata.get("1_6_stage", "Первичная")

        # Формируем части заголовка

        # 1. Стадия
        stage_text = self.STAGE_MAP.get(stage, "разработка")

        # 2. Тип документа (зависит от стадии) - СЛОЙ использует именительный падеж
        doc_map = self.DOC_TYPE_MAP_LAYER.get(doc_type, self.DOC_TYPE_MAP_LAYER["ДПТ"])
        doc_text = doc_map.get(stage, doc_map["Первичная"])

        # ВАЖНО: для "Внесение изменений" + "Мастер-план" используем единственное число
        # "внесение изменения в мастер-план" (не "изменений")
        if stage == "Внесение изменений" and doc_type == "Мастер-план":
            stage_text = "внесение изменения в"

        # Формируем полный текст
        title = (
            f"Границы территории, применительно к которой осуществляется "
            f"{stage_text} {doc_text}"
        )

        return title

    def get_stage_text(self, stage: str) -> str:
        """
        Получить текстовое представление стадии

        Args:
            stage: Значение метаданных 1_6_stage

        Returns:
            Текстовая форма стадии
        """
        return self.STAGE_MAP.get(stage, "разработка")

    def get_doc_type_text(self, doc_type: str, stage: str, for_layer: bool = False) -> str:
        """
        Получить текстовое представление типа документа

        Args:
            doc_type: Значение метаданных 1_5_doc_type
            stage: Значение метаданных 1_6_stage
            for_layer: True для слоя границ (именительный падеж), False для схемы (родительный падеж)

        Returns:
            Текстовая форма типа документа
        """
        doc_map_source = self.DOC_TYPE_MAP_LAYER if for_layer else self.DOC_TYPE_MAP_SCHEME
        doc_map = doc_map_source.get(doc_type, doc_map_source["ДПТ"])
        return doc_map.get(stage, doc_map["Первичная"])

    def get_object_type_text(self, object_type: str, object_type_value: Optional[str] = None) -> str:
        """
        Получить текстовое представление типа объекта

        Args:
            object_type: Значение метаданных 1_2_object_type
            object_type_value: Значение метаданных 1_2_1_object_type_value (для линейных)

        Returns:
            Текстовая форма типа объекта
        """
        object_text = self.OBJECT_TYPE_MAP.get(object_type, self.OBJECT_TYPE_MAP["Площадной"])

        # Для линейных добавляем значение
        if object_type == "Линейный" and object_type_value and object_type_value != "-":
            value_text = self.OBJECT_VALUE_MAP.get(object_type_value, object_type_value.lower())
            object_text += f" {value_text} значения"

        return object_text
