# -*- coding: utf-8 -*-
"""Менеджер правил классификации прав ЗУ по слоям L_1_11 (Base_rights_classification.json)"""

from typing import List, Dict
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader


class RightsClassificationManager(BaseReferenceLoader):
    """Менеджер правил классификации прав ЗУ из Base_rights_classification.json.

    Три класса правил различаются полем record_kind:
    - 'right'           — класс A (основной слой L_1_11_1..6 по паре право+форма)
    - 'semi_right' /
      'encumbrance'     — класс B (доп-слой L_1_11_7..17 по полу-праву/обременению)
    - 'form_derivation' — класс C (деривация __Форма_тех по названию юрлица, импорт)

    Потребители: Msm_25_2 (классы A, B) и Fsm_1_1_4_8 (класс C).
    Приоритет несёт rule_id (меньше = раньше), как в Base_zouit_classification
    (образец Msm_4_18). Загрузка/кэш — общий контур BaseReferenceLoader.
    """

    FILE_NAME = 'Base_rights_classification.json'

    def get_rules(self) -> List[Dict]:
        """Получить все правила, отсортированные по rule_id (приоритет применения)."""
        rules = self._load_json(self.FILE_NAME) or []
        return sorted(rules, key=lambda r: r.get('rule_id', 999))

    def get_rules_by_kind(self, *kinds: str) -> List[Dict]:
        """Получить правила заданных record_kind, в порядке rule_id.

        Args:
            *kinds: одно или несколько значений record_kind
                    ('right' / 'semi_right' / 'encumbrance' / 'form_derivation')

        Returns:
            Список правил указанных классов, отсортированный по rule_id
        """
        allowed = set(kinds)
        return [r for r in self.get_rules() if r.get('record_kind') in allowed]
