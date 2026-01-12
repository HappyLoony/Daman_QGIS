# -*- coding: utf-8 -*-
"""
Менеджер стилей экспорта координат в Excel.

Отвечает за:
- Получение стилей экспорта для слоев
- Форматирование текста с подстановкой переменных
- Поддержку шаблонов с метаданными проекта
"""

import re
from typing import List, Dict, Optional
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader


class ExcelExportStyleManager(BaseReferenceLoader):
    """Менеджер стилей экспорта координат в Excel"""

    FILE_NAME = 'Base_excel_export_styles.json'

    def get_excel_export_styles(self) -> List[Dict]:
        """
        Получить все стили экспорта в Excel

        Returns:
            Список стилей экспорта, каждый содержит:
            - layer: название слоя или 'Other' для универсального стиля
            - title: заголовок документа (может содержать переменные {variable})
            - contour_title: заголовок контура (может содержать переменные {variable})
        """
        return self._load_json(self.FILE_NAME) or []

    def get_excel_export_style_for_layer(self, layer_name: str) -> Optional[Dict]:
        """
        Получить стиль экспорта для конкретного слоя

        Ищет стиль для указанного слоя. Если не найден, возвращает универсальный
        стиль 'Other' (если существует).

        Args:
            layer_name: Имя слоя (например '3_2_1_ГПМТ')

        Returns:
            Словарь с настройками экспорта:
            {
                'layer': str,
                'title': str,
                'contour_title': str
            }
            Или None если слой не найден и нет стиля 'Other'
        """
        styles = self.get_excel_export_styles()
        other_style = None

        # Ищем точное соответствие или стиль 'Other'
        for style in styles:
            # Проверяем оба возможных ключа: 'layer' и 'style_name'
            layer_pattern = style.get('layer') or style.get('style_name')
            if not layer_pattern:
                continue

            # Точное соответствие
            if layer_pattern == layer_name:
                # Нормализуем ключи для единообразия
                if 'style_name' in style and 'layer' not in style:
                    style['layer'] = style['style_name']
                # Маппинг старых ключей на правильные
                if 'title' not in style and 'font_name' in style:
                    style['title'] = style['font_name']
                if 'contour_title' not in style and 'font_size' in style:
                    style['contour_title'] = style['font_size']
                return style

            # Запоминаем стиль 'Other' как запасной
            if layer_pattern == 'Other':
                other_style = style

        # Нормализуем ключи для стиля 'Other'
        if other_style:
            if 'style_name' in other_style and 'layer' not in other_style:
                other_style['layer'] = other_style['style_name']
            if 'title' not in other_style and 'font_name' in other_style:
                other_style['title'] = other_style['font_name']
            if 'contour_title' not in other_style and 'font_size' in other_style:
                other_style['contour_title'] = other_style['font_size']

        # Возвращаем стиль 'Other' если ничего не найдено
        return other_style

    def format_excel_export_text(
        self,
        text: Optional[str],
        metadata: Optional[Dict] = None,
        layer_info: Optional[Dict] = None
    ) -> str:
        """
        Форматировать текст с подстановкой переменных

        Переменные в тексте должны быть в фигурных скобках: {variable_name}

        Доступные переменные:
        - Все поля из метаданных проекта (metadata)
        - Дополнительная информация о слое (layer_info)
        - Автоматические переменные:
          - {crs_name}: форматированное название СК (СК_63_5 -> СК 63 зона 5)
          - {area_formatted}: площадь с пробелами (1 234 567)
          - {area_ha}: площадь в гектарах
          - {object_type}: тип объекта из метаданных
          - {hole_number}: номер внутреннего контура

        Args:
            text: Текст с переменными в фигурных скобках
            metadata: Словарь с метаданными проекта
            layer_info: Дополнительная информация о слое (опционально)

        Returns:
            Отформатированный текст с подставленными значениями

        Example:
            >>> text = "Координаты в {crs_name}, площадь {area_formatted} м²"
            >>> metadata = {'1_4_crs_short': 'СК_63_5'}
            >>> layer_info = {'area': 1234567}
            >>> format_excel_export_text(text, metadata, layer_info)
            'Координаты в СК 63 зона 5, площадь 1 234 567 м²'
        """
        if not text:
            return ""

        # Создаем словарь всех доступных переменных
        variables = {}

        # Добавляем метаданные проекта
        if metadata:
            variables.update(metadata)

        # Добавляем информацию о слое если есть
        if layer_info:
            variables.update(layer_info)

        # === Специальные переменные ===

        # Преобразуем crs_short в читаемый формат
        if '1_4_crs_short' in variables:
            crs_short = variables['1_4_crs_short']
            if '_' in crs_short:
                parts = crs_short.split('_')
                if len(parts) == 3 and 'СК' in parts[0]:  # СК_63_5
                    variables['crs_name'] = f"{parts[0]} {parts[1]} зона {parts[2]}"
                elif len(parts) == 2:  # МСК_50
                    variables['crs_name'] = f"{parts[0]}-{parts[1]}"
                else:
                    variables['crs_name'] = crs_short.replace('_', ' ')
            else:
                variables['crs_name'] = crs_short

        # Добавляем object_type из метаданных
        if '1_3_object_type' in variables:
            variables['object_type'] = variables['1_3_object_type']

        # Форматируем площадь с пробелами если передана
        if 'area' in variables:
            area = variables['area']
            if isinstance(area, (int, float)):
                # Округляем площадь до целого (избегаем артефактов float: 1234.0000000000002)
                area_int = int(round(area))

                # Перезаписываем area округлённым значением для использования в шаблонах
                variables['area'] = area_int

                area_str = str(area_int)

                # Разбиваем на группы по 3 цифры справа налево
                groups = []
                for i in range(len(area_str), 0, -3):
                    start = max(0, i - 3)
                    groups.append(area_str[start:i])

                variables['area_formatted'] = ' '.join(reversed(groups))
                variables['area_ha'] = f"{area / 10000:.4f}"

        # Добавляем номер внутреннего контура если передан
        if 'hole_number' in variables:
            variables['hole_number'] = str(variables['hole_number'])

        # Заменяем переменные в тексте
        def replace_var(match):
            """Замена переменной из словаря variables."""
            var_name = match.group(1)
            # Сначала ищем точное совпадение
            if var_name in variables:
                return str(variables[var_name])
            # Если не найдено, оставляем как есть
            return match.group(0)

        # Ищем все переменные в фигурных скобках и заменяем
        formatted_text = re.sub(r'\{([^}]+)\}', replace_var, text)

        return formatted_text
