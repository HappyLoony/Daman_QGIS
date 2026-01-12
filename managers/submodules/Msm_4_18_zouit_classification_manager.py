# -*- coding: utf-8 -*-
"""Менеджер правил классификации ЗОУИТ (автоматическое распределение по слоям)"""

from typing import List, Dict, Optional, Union
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader


class ZOUITClassificationManager(BaseReferenceLoader):
    """Менеджер для работы с правилами классификации ЗОУИТ из Base_zouit_classification.json"""

    FILE_NAME = 'Base_zouit_classification.json'

    def get_rules(self) -> List[Dict]:
        """
        Получить список правил классификации ЗОУИТ

        Правила отсортированы по rule_id (приоритет применения)

        Returns:
            Список правил классификации
        """
        rules = self._load_json(self.FILE_NAME) or []

        # Сортируем по rule_id (приоритет)
        rules_sorted = sorted(rules, key=lambda r: r.get('rule_id', 999))

        return rules_sorted

    def get_rule_by_id(self, rule_id: int) -> Optional[Dict]:
        """
        Получить правило по ID

        Args:
            rule_id: ID правила

        Returns:
            Словарь с данными правила или None
        """
        rules = self.get_rules()
        for rule in rules:
            if rule.get('rule_id') == rule_id:
                return rule
        return None

    def get_rules_by_layer(self, target_layer: str) -> List[Dict]:
        """
        Получить все правила для конкретного слоя

        Args:
            target_layer: Полное имя слоя (full_name)

        Returns:
            Список правил для данного слоя
        """
        rules = self.get_rules()
        return [rule for rule in rules if rule.get('target_layer') == target_layer]

    def get_rules_by_field(self, search_field: str) -> List[Dict]:
        """
        Получить все правила для конкретного поля поиска

        Args:
            search_field: Поле для поиска (type_zone, name_by_doc, doc_name)

        Returns:
            Список правил для данного поля
        """
        rules = self.get_rules()
        results = []

        for rule in rules:
            # search_field может содержать несколько полей через ";"
            fields = [f.strip() for f in rule.get('search_field', '').split(';')]
            if search_field in fields:
                results.append(rule)

        return results

    def validate_rules(self) -> Dict[str, Union[List, int]]:
        """
        Валидация правил классификации

        Проверяет:
        - Все target_layer существуют в Base_layers.json
        - Все search_field корректны
        - rule_id уникальны

        Returns:
            Словарь с результатами валидации:
            {
                'errors': [список ошибок],
                'warnings': [список предупреждений],
                'total_rules': количество правил
            }
        """
        rules = self.get_rules()
        errors = []
        warnings = []
        seen_rule_ids = set()

        # Загружаем список допустимых слоев из Base_layers.json
        valid_layers = set()
        try:
            layers_data = self._load_json('Base_layers.json') or []
            for layer in layers_data:
                full_name = layer.get('full_name')
                if full_name:
                    valid_layers.add(full_name)
        except Exception as e:
            errors.append(f"Не удалось загрузить Base_layers.json: {e}")

        # Допустимые поля для поиска
        valid_search_fields = {'type_zone', 'name_by_doc', 'doc_name', 'type_boundary_value'}

        for rule in rules:
            rule_id = rule.get('rule_id')
            target_layer = rule.get('target_layer', '').strip()
            search_field = rule.get('search_field', '').strip()
            keywords = rule.get('keywords', '').strip()

            # Проверка уникальности rule_id
            if rule_id in seen_rule_ids:
                errors.append(f"Rule {rule_id}: дубликат rule_id")
            seen_rule_ids.add(rule_id)

            # Проверка target_layer
            if not target_layer:
                errors.append(f"Rule {rule_id}: target_layer пустой")
            elif target_layer not in valid_layers:
                warnings.append(f"Rule {rule_id}: target_layer '{target_layer}' не найден в Base_layers.json")

            # Проверка search_field
            if not search_field:
                errors.append(f"Rule {rule_id}: search_field пустой")
            else:
                fields = [f.strip() for f in search_field.split(';')]
                for field in fields:
                    if field not in valid_search_fields:
                        warnings.append(f"Rule {rule_id}: search_field '{field}' не входит в допустимые поля")

            # Проверка keywords
            if not keywords:
                errors.append(f"Rule {rule_id}: keywords пустой")
            else:
                keywords_list = [k.strip() for k in keywords.split(';')]
                # Если несколько полей, количество keywords должно совпадать
                if search_field and ';' in search_field:
                    fields = [f.strip() for f in search_field.split(';')]
                    if len(fields) != len(keywords_list):
                        errors.append(
                            f"Rule {rule_id}: количество полей в search_field ({len(fields)}) "
                            f"!= количество keywords ({len(keywords_list)})"
                        )

        return {
            'errors': errors,
            'warnings': warnings,
            'total_rules': len(rules)
        }

    def get_classification_info(self) -> Dict:
        """
        Получить информацию о базе правил классификации

        Returns:
            Словарь с метаинформацией о базе
        """
        rules = self.get_rules()

        # Подсчитываем статистику
        layers = set()
        fields = set()

        for rule in rules:
            target_layer = rule.get('target_layer', '').strip()
            if target_layer:
                layers.add(target_layer)

            search_field = rule.get('search_field', '').strip()
            if search_field:
                for field in search_field.split(';'):
                    fields.add(field.strip())

        return {
            'total_rules': len(rules),
            'unique_layers': len(layers),
            'used_fields': sorted(list(fields)),
            'source': 'Base_zouit_classification.json',
            'description': 'Правила автоматической классификации ЗОУИТ по ключевым словам'
        }
