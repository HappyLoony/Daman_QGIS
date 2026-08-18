# -*- coding: utf-8 -*-
"""
Fsm_2_4_2_ValueConverter - Приведение значений атрибутов к типам OGR

НАЗНАЧЕНИЕ:
    OGR SetField принимает ограниченный набор типов. Конвертер приводит значение
    Python (в том числе QVariant из PyQGIS) к типу целевого поля: OFTInteger,
    OFTReal либо строка.

ОСОБЕННОСТИ:
    - Сентинел "-" и пустая строка для числовых полей дают None (поле не пишется).
    - Непреобразуемое значение логируется и для строкового поля пишется как str().

ИСПОЛЬЗОВАНИЕ:
    Используется писателями слоёв этапности при записи атрибутов фичи.
"""

from typing import Any

from Daman_QGIS.utils import log_warning


class Fsm_2_4_2_ValueConverter:
    """Приведение значений атрибутов к типам полей OGR"""

    def convert(self, value: Any, field_type: int) -> Any:
        """Конвертирует значение Python в совместимый тип для OGR SetField

        OGR SetField принимает только определённые типы:
        - OFTInteger: int или str
        - OFTReal: float или str
        - OFTString: str

        Args:
            value: Исходное значение
            field_type: Тип поля OGR (ogr.OFTInteger, ogr.OFTReal, ogr.OFTString)

        Returns:
            Конвертированное значение или None если конвертация невозможна
        """
        from osgeo import ogr

        if value is None:
            return None

        # Обработка QVariant (может прийти из PyQGIS)
        # QVariant.isNull() возвращает True для NULL значений
        try:
            from qgis.PyQt.QtCore import QVariant
            if isinstance(value, QVariant):
                if value.isNull():
                    return None
                value = value.value()
        except (ImportError, AttributeError):
            pass

        # Конвертация в зависимости от типа поля OGR
        try:
            if field_type == ogr.OFTInteger:
                # Целое число
                if isinstance(value, bool):
                    return 1 if value else 0
                if isinstance(value, (int, float)):
                    return int(value)
                if isinstance(value, str):
                    if value.strip() == '' or value.strip() == '-':
                        return None
                    return int(float(value))
                return int(value)

            elif field_type == ogr.OFTReal:
                # Вещественное число
                if isinstance(value, bool):
                    return 1.0 if value else 0.0
                if isinstance(value, (int, float)):
                    return float(value)
                if isinstance(value, str):
                    if value.strip() == '' or value.strip() == '-':
                        return None
                    return float(value)
                return float(value)

            else:
                # OFTString и все остальные - конвертируем в строку
                if isinstance(value, bool):
                    return "Да" if value else "Нет"
                if isinstance(value, (list, tuple)):
                    return "; ".join(str(v) for v in value if v is not None)
                if isinstance(value, dict):
                    return str(value)
                return str(value)

        except (ValueError, TypeError) as e:
            # Если конвертация не удалась - возвращаем строковое представление
            log_warning(f"Fsm_2_4_2: Не удалось конвертировать значение '{value}' "
                       f"(тип {type(value).__name__}) для OGR: {e}")
            return str(value) if field_type == ogr.OFTString else None
