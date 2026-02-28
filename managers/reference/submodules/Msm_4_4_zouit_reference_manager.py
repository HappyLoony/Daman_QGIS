# -*- coding: utf-8 -*-
"""Менеджер справочных данных ЗОУИТ (Зоны с особыми условиями использования территорий)"""

from typing import List, Dict, Optional
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader


class ZOUITReferenceManager(BaseReferenceLoader):
    """Менеджер для работы с классификатором ЗОУИТ из Base_layers.json"""

    FILE_NAME = 'Base_layers.json'

    def get_zouit(self) -> List[Dict]:
        """
        Получить список ЗОУИТ из Base_layers.json

        Возвращает слои с кодами ЗОУИТ (key_key_object)

        Returns:
            Список зон ЗОУИТ
        """
        # Загружаем все слои из Base_layers.json
        all_layers = self._load_json(self.FILE_NAME) or []

        # Фильтруем только слои ЗОУИТ (у которых есть key_key_object)
        zouit_layers = []
        for layer in all_layers:
            key_code = layer.get('key_key_object')
            # Проверяем что key_key_object не пустой и не "-"
            if key_code and key_code != '-':
                zouit_layers.append({
                    'code': str(key_code),
                    'name': layer.get('description', ''),
                    'full_name': layer.get('full_name', ''),
                    'category_id': layer.get('key_key_xml', '-'),
                    'layer': layer  # Сохраняем полную информацию о слое
                })

        return zouit_layers

    def get_zouit_by_code(self, code: str) -> Optional[Dict]:
        """
        Получить ЗОУИТ по коду

        Args:
            code: Код ЗОУИТ

        Returns:
            Словарь с данными ЗОУИТ или None
        """
        return self._get_by_key(
            data_getter=self.get_zouit,
            index_key='zouit_by_code',
            field_name='code',
            value=code
        )

    def search_zouit(self, query: str) -> List[Dict]:
        """
        Поиск ЗОУИТ по части названия

        Args:
            query: Строка для поиска в названии

        Returns:
            Список найденных зон ЗОУИТ
        """
        query_lower = query.lower() if query else ''
        zones = self.get_zouit()
        results = []

        for zone in zones:
            if query_lower in zone['name'].lower():
                results.append(zone)

        return results

    def get_zouit_info(self) -> Dict:
        """
        Получить информацию о базе ЗОУИТ

        Returns:
            Словарь с метаинформацией о базе
        """
        zouit_layers = self.get_zouit()
        return {
            'total': len(zouit_layers),
            'source': 'Base_layers.json',
            'description': 'ЗОУИТ данные из справочника слоев (key_key_object)'
        }
