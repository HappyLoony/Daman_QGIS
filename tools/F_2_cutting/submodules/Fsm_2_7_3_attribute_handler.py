# -*- coding: utf-8 -*-
"""
Fsm_2_7_3_AttributeHandler - Генерация атрибутов объединённого контура

Формирует атрибуты для объединённого земельного участка:
- Услов_КН = "КН:ЗУ{N}" (N = max+1 с учётом Раздел + НГС)
- Вид_Работ = "Образование ЗУ путем объединения ... с условными номерами X, Y"
- Площадь_ОЗУ = площадь объединённой геометрии

Правила наследования атрибутов:
- КН, ЕЗ, Права, Обременение = комбинация всех (через "; ")
- Адрес = первый непустой
- Категория, ВРИ = первый непустой
- ЗПР = из первого контура (все должны быть одинаковы)
"""

import re
from typing import List, Optional, Dict, Any

from qgis.core import QgsFeature, QgsFields

from Daman_QGIS.utils import log_info, log_warning

# Импорт менеджера Вид_Работ
from Daman_QGIS.managers.validation import WorkTypeAssignmentManager


class Fsm_2_7_3_AttributeHandler:
    """Обработчик атрибутов для объединения контуров"""

    # Поля, которые комбинируются из всех контуров
    COMBINE_FIELDS = [
        'КН', 'ЕЗ', 'Права', 'Обременения', 'Собственники', 'Арендаторы'
    ]

    # Поля, которые берутся из первого непустого
    FIRST_NON_EMPTY_FIELDS = [
        'Адрес_Местоположения', 'Категория', 'ВРИ', 'Тип_объекта',
        'План_категория', 'План_ВРИ'
    ]

    # Поля, которые должны быть одинаковыми у всех контуров
    SAME_VALUE_FIELDS = ['ЗПР']

    def __init__(self, plugin_dir: str) -> None:
        """Инициализация обработчика

        Args:
            plugin_dir: Путь к папке плагина
        """
        self.plugin_dir = plugin_dir
        self._work_type_manager = WorkTypeAssignmentManager()

    def generate_merged_attributes(
        self,
        features: List[QgsFeature],
        fields: QgsFields,
        new_area: float,
        existing_uslov_kns: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """Генерация атрибутов для объединённого контура

        Args:
            features: Список исходных features для объединения
            fields: Структура полей слоя
            new_area: Площадь объединённой геометрии
            existing_uslov_kns: Существующие Услов_КН в слое и НГС
                (для корректной нумерации :ЗУ{N})

        Returns:
            Словарь {field_name: value} или None при ошибке
        """
        if not features or len(features) < 2:
            log_warning("Fsm_2_7_3: Недостаточно контуров для объединения")
            return None

        try:
            attrs: Dict[str, Any] = {}

            # 1. Генерируем новый Услов_КН (формат :ЗУ{N})
            new_uslov_kn = self._generate_uslov_kn(
                features, existing_uslov_kns or []
            )
            attrs['Услов_КН'] = new_uslov_kn

            # Состав объединённых контуров не сохраняется: F_2_7 работает только
            # по слоям нарезки, а их схема (Base_cutting) такого поля не несёт.
            # Поле «Состав_контуров» существует у слоёв 2 этапа и Итога, которые
            # создаёт писатель этапности (Fsm_2_4_1, add_merged_field=True).

            # 2. Генерируем Вид_Работ
            uslov_kn_list = [self._get_value(f, 'Услов_КН') for f in features]
            uslov_kn_list = [uk for uk in uslov_kn_list if uk]
            vid_rabot = self._generate_vid_rabot(uslov_kn_list)
            attrs['Вид_Работ'] = vid_rabot

            # 4. Площадь_ОЗУ (поле объявлено целым в Base_cutting)
            attrs['Площадь_ОЗУ'] = int(round(new_area))

            # Поля исходного ЗУ при объединении контуров РАЗНЫХ участков
            # неизвестны: наследование от первого контура дало бы пару
            # «два КН — характеристики одного из них». Комбинируемый КН
            # остаётся, остальное чистится (санитайзер поставит «-»).
            source_kns = {
                str(self._get_value(f, 'КН')).strip()
                for f in features
                if self._get_value(f, 'КН') and str(self._get_value(f, 'КН')).strip() != '-'
            }
            merges_different_zu = len(source_kns) > 1

            # Поля «Многоконтурный» нет: multipart отвергается гардом
            # процессора до генерации атрибутов, и в схеме Base_cutting его нет

            # 5. ID = 0 (будет перенумерован)
            attrs['ID'] = 0

            # 7. Комбинируемые поля
            for field_name in self.COMBINE_FIELDS:
                if fields.indexOf(field_name) >= 0:
                    combined = self._combine_values(features, field_name)
                    attrs[field_name] = combined

            # 8. Первый непустой
            for field_name in self.FIRST_NON_EMPTY_FIELDS:
                if fields.indexOf(field_name) >= 0:
                    value = self._get_first_non_empty(features, field_name)
                    attrs[field_name] = value

            # 9. Одинаковые значения
            for field_name in self.SAME_VALUE_FIELDS:
                if fields.indexOf(field_name) >= 0:
                    value = self._get_same_value(features, field_name)
                    attrs[field_name] = value

            # 10. Копируем остальные поля из первого контура.
            # Служебный `fid` пропускается: это первичный ключ GeoPackage,
            # его присваивает провайдер, а копия чужого значения даёт коллизию
            first_feature = features[0]
            for i in range(fields.count()):
                field_name = fields.at(i).name()
                if field_name.lower() == 'fid':
                    continue
                if field_name not in attrs:
                    value = self._get_value(first_feature, field_name)
                    attrs[field_name] = value

            # 11. Очищаем поле Точки (будет заполнено позже)
            attrs['Точки'] = ''

            # 12. Характеристики исходных ЗУ при объединении разных участков
            if merges_different_zu:
                for field_name in ('Категория', 'ВРИ', 'Площадь',
                                   'Права', 'Обременения', 'Собственники',
                                   'Арендаторы', 'Адрес_Местоположения'):
                    if field_name in attrs:
                        attrs[field_name] = None
                log_info(
                    f"Fsm_2_7_3: объединены контуры разных ЗУ ({len(source_kns)} КН) — "
                    f"характеристики исходных участков очищены"
                )

            log_info(f"Fsm_2_7_3: Сгенерированы атрибуты для объединённого контура, "
                    f"Услов_КН={new_uslov_kn}")

            return attrs

        except Exception as e:
            log_warning(f"Fsm_2_7_3: Ошибка генерации атрибутов: {e}")
            return None

    def _generate_uslov_kn(
        self,
        features: List[QgsFeature],
        existing_uslov_kns: List[str]
    ) -> str:
        """Генерация нового условного КН

        Формат: КН:ЗУ{N} где N - следующий свободный номер.
        Учитывает существующие Услов_КН в слоях Раздел и НГС.

        Args:
            features: Список контуров для объединения
            existing_uslov_kns: Существующие Услов_КН в проекте

        Returns:
            Новый Услов_КН
        """
        # Получаем базовый КН (первый непустой из объединяемых)
        base_kn = None
        for f in features:
            kn = self._get_value(f, 'КН')
            if kn and kn != '-':
                base_kn = str(kn).strip()
                break

        if not base_kn:
            base_kn = '00:00:000000:0000'

        # Собираем все существующие номера :ЗУ{N} для этого base_kn
        # Ищем и в existing_uslov_kns, и в самих объединяемых features
        all_uslov_kns = list(existing_uslov_kns)
        for f in features:
            uk = self._get_value(f, 'Услов_КН')
            if uk:
                all_uslov_kns.append(str(uk))

        # Паттерн: base_kn:ЗУ{число}
        pattern = re.escape(base_kn) + r':ЗУ(\d+)$'
        max_n = 0
        for uk in all_uslov_kns:
            match = re.search(pattern, str(uk))
            if match:
                n = int(match.group(1))
                if n > max_n:
                    max_n = n

        next_n = max_n + 1
        result = f"{base_kn}:ЗУ{next_n}"
        log_info(f"Fsm_2_7_3: Сгенерирован Услов_КН={result} "
                f"(max существующий :ЗУ{max_n})")
        return result

    def _generate_vid_rabot(self, uslov_kn_list: List[str]) -> str:
        """Генерация поля Вид_Работ для объединения

        Формат: "Образование ЗУ путем объединения земельных участков
                 с условными номерами X, Y, Z"

        Args:
            uslov_kn_list: Список условных КН объединяемых контуров

        Returns:
            Строка Вид_Работ
        """
        # Формулировку даёт M_22 — единственный источник: собственная копия
        # строки расходилась с ним в одной букве («путём» против «путем»), и
        # сопоставление со справочником Work_types проваливалось молча
        return self._work_type_manager.get_merge_work_type(uslov_kn_list)

    def _get_value(self, feature: QgsFeature, field_name: str) -> Any:
        """Безопасное получение значения атрибута

        Args:
            feature: Feature
            field_name: Имя поля

        Returns:
            Значение или None
        """
        try:
            value = feature[field_name]
            if value is None or value == '':
                return None
            return value
        except (KeyError, IndexError):
            return None

    def _combine_values(
        self,
        features: List[QgsFeature],
        field_name: str,
        separator: str = '; '
    ) -> str:
        """Комбинировать значения из всех контуров

        Args:
            features: Список контуров
            field_name: Имя поля
            separator: Разделитель

        Returns:
            Комбинированная строка
        """
        values = []
        seen = set()

        for f in features:
            value = self._get_value(f, field_name)
            if value and value not in seen:
                values.append(str(value))
                seen.add(value)

        return separator.join(values) if values else ''

    def _get_first_non_empty(
        self,
        features: List[QgsFeature],
        field_name: str
    ) -> Any:
        """Получить первое непустое значение

        Args:
            features: Список контуров
            field_name: Имя поля

        Returns:
            Первое непустое значение или None
        """
        for f in features:
            value = self._get_value(f, field_name)
            if value:
                return value
        return None

    def _get_same_value(
        self,
        features: List[QgsFeature],
        field_name: str
    ) -> Any:
        """Получить значение, которое должно быть одинаковым у всех

        Если значения разные - возвращает первое с предупреждением

        Args:
            features: Список контуров
            field_name: Имя поля

        Returns:
            Значение поля
        """
        values = set()

        for f in features:
            value = self._get_value(f, field_name)
            if value:
                values.add(str(value))

        if len(values) > 1:
            log_warning(f"Fsm_2_7_3: Поле {field_name} имеет разные значения: {values}")

        # Возвращаем первое непустое
        return self._get_first_non_empty(features, field_name)
