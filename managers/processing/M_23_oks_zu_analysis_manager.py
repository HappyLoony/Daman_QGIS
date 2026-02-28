# -*- coding: utf-8 -*-
"""
M_23 - OksZuAnalysisManager: Менеджер анализа связей ОКС-ЗУ

Назначение:
    Автоматический анализ и заполнение полей связей между ОКС и ЗУ:
    - ОКС_на_ЗУ_выписка: данные из выписок ЕГРН (поле "Связанные_ЗУ")
    - ОКС_на_ЗУ_факт: геометрический анализ пересечения ОКС с ЗУ

Ключевая особенность:
    Автоматически определяет какие данные доступны и заполняет
    соответствующие поля. Вызывается из F_2_1 и F_2_2.

Сценарии:
    1. Загрузка выписок (без выборки) -> ничего (некуда записать)
    2. Выборка F_2_1 (без выписок) -> заполняет ОКС_на_ЗУ_факт
    3. Выборка после загрузки выписок -> заполняет оба поля
    4. F_2_2 синхронизация -> заполняет оба поля (пересчёт)

Зависимости:
    - Msm_23_1_geometry_analyzer: геометрический анализ пересечений
    - Msm_23_2_relation_mapper: маппинг связей и обратный маппинг
    - Msm_23_3_cutting_sync: синхронизация с нарезкой

Использование:
    from Daman_QGIS.managers import OksZuAnalysisManager

    manager = OksZuAnalysisManager()
    result = manager.auto_analyze()
"""

from typing import Dict, List, Any, Optional, Tuple
from qgis.core import QgsProject, QgsVectorLayer, QgsGeometry

from Daman_QGIS.constants import (
    LAYER_SELECTION_OKS, LAYER_SELECTION_ZU,
    LAYER_VYPISKA_OKS_PREFIX, LAYER_VYPISKA_ZU_PREFIX
)
from Daman_QGIS.utils import log_info, log_warning, log_error, log_success

from .submodules.Msm_23_1_geometry_analyzer import GeometryAnalyzer
from .submodules.Msm_23_2_relation_mapper import RelationMapper
from .submodules.Msm_23_3_cutting_sync import CuttingSync
from .submodules.Msm_23_4_zu_extract_analyzer import ZuExtractAnalyzer

__all__ = ['OksZuAnalysisManager']


class OksZuAnalysisManager:
    """Менеджер анализа связей ОКС-ЗУ

    Автоматически определяет доступные данные и заполняет поля.
    """

    # Имена слоёв
    OKS_LAYER_NAME = LAYER_SELECTION_OKS
    ZU_LAYER_NAME = LAYER_SELECTION_ZU

    # Префиксы слоёв выписок
    VYPISKA_OKS_PREFIX = LAYER_VYPISKA_OKS_PREFIX + '_'
    VYPISKA_ZU_PREFIX = LAYER_VYPISKA_ZU_PREFIX + '_'

    # Поле с данными из выписки ОКС
    VYPISKA_FIELD = 'Связанные_ЗУ'

    # Поле с данными из выписки ЗУ (включённые объекты - ОКС)
    INCLUDED_OBJECTS_FIELD = 'Включенные_объекты'

    # Минимальная площадь пересечения (м2)
    MIN_INTERSECTION_AREA = 1.0

    def __init__(self):
        """Инициализация менеджера"""
        # Инициализация субменеджеров
        self._geometry_analyzer = GeometryAnalyzer(
            min_intersection_area=self.MIN_INTERSECTION_AREA
        )
        self._relation_mapper = RelationMapper()
        self._cutting_sync = CuttingSync()
        self._zu_extract_analyzer = ZuExtractAnalyzer()

    # ==================== ГЛАВНЫЙ МЕТОД ====================

    def auto_analyze(self) -> Dict[str, Any]:
        """
        ГЛАВНЫЙ МЕТОД - автоматический анализ и заполнение полей

        Логика:
        1. Проверяет наличие слоёв выборки (L_2_1_1, L_2_1_2)
        2. Проверяет наличие слоёв выписок (Le_1_6_1_*, Le_1_6_2_*)
        3. Автоматически определяет что можно заполнить
        4. Заполняет доступные поля

        Returns:
            {
                'selection_exists': bool,      # Есть ли слои выборки
                'vypiska_exists': bool,        # Есть ли выписки ОКС
                'vypiska_zu_exists': bool,     # Есть ли выписки ЗУ
                'geometry_filled': bool,       # Заполнено ли ОКС_на_ЗУ_факт
                'vypiska_filled': bool,        # Заполнено ли ОКС_на_ЗУ_выписка
                'zu_vypiska_filled': bool,     # Заполнено ли из выписок ЗУ
                'oks_updated': int,            # Кол-во обновлённых ОКС
                'zu_updated': int,             # Кол-во обновлённых ЗУ
                'cutting_synced': int          # Кол-во синхр. в нарезке
            }
        """
        result = {
            'selection_exists': False,
            'vypiska_exists': False,
            'vypiska_zu_exists': False,
            'geometry_filled': False,
            'vypiska_filled': False,
            'zu_vypiska_filled': False,
            'oks_updated': 0,
            'zu_updated': 0,
            'cutting_synced': 0
        }

        log_info("M_23: Запуск автоматического анализа ОКС-ЗУ")

        # 1. Проверяем доступность данных
        availability = self.check_data_availability()
        result['selection_exists'] = availability['selection_zu'] and availability['selection_oks']
        result['vypiska_exists'] = availability['vypiska_oks']
        result['vypiska_zu_exists'] = availability['vypiska_zu']

        # 2. Получаем слой ЗУ (нужен для обработки выписок ЗУ даже без выборки ОКС)
        zu_layer = self._get_zu_selection_layer()

        # 3. Обработка выписок ЗУ (независимо от наличия выборки ОКС)
        # Это основной источник для поля "ОКС_на_ЗУ_выписка" в слое ЗУ
        if availability['can_fill_zu_vypiska'] and zu_layer is not None:
            log_info("M_23: Извлекаем данные из выписок ЗУ (поле 'Включенные_объекты')")
            zu_oks_data = self._zu_extract_analyzer.extract_oks_from_zu_extracts()
            if zu_oks_data:
                zu_updated = self._zu_extract_analyzer.update_zu_selection_layer(
                    zu_layer, zu_oks_data
                )
                result['zu_vypiska_filled'] = zu_updated > 0
                result['zu_updated'] = zu_updated
                log_info(f"M_23: Из выписок ЗУ обновлено {zu_updated} объектов")

        # 4. Если нет обоих слоёв выборки - выходим (дальнейший анализ невозможен)
        if not result['selection_exists']:
            log_info("M_23: Слои выборки ОКС не найдены или пусты, геометрический анализ пропущен")
            return result

        # 5. Получаем слой ОКС
        oks_layer = self._get_oks_selection_layer()

        if oks_layer is None:
            log_warning("M_23: Не удалось получить слой выборки ОКС")
            return result

        # 6. Собираем данные
        geometry_data: Optional[Dict[str, List[str]]] = None
        vypiska_data: Optional[Dict[str, List[str]]] = None

        # Геометрический анализ (всегда доступен если есть выборка)
        if availability['can_fill_geometry']:
            log_info("M_23: Выполняем геометрический анализ пересечений")
            geometry_data = self._geometry_analyzer.analyze(oks_layer, zu_layer)
            result['geometry_filled'] = True
            non_empty_geom = {k: v for k, v in geometry_data.items() if v}
            log_info(f"M_23: Геометрический анализ завершён для {len(geometry_data)} ОКС, с пересечениями: {len(non_empty_geom)}")

        # Данные из выписок ОКС (только если выписки загружены)
        if availability['can_fill_vypiska']:
            log_info("M_23: Извлекаем данные из выписок ОКС")
            vypiska_data = self.extract_vypiska_relations(oks_layer)
            result['vypiska_filled'] = True
            non_empty_vyp = {k: v for k, v in vypiska_data.items() if v}
            log_info(f"M_23: Извлечено данных из выписок для {len(non_empty_vyp)} ОКС из {len(vypiska_data)}")

        # 7. Обновляем слои выборки (ОКС и обратный маппинг для ЗУ)
        update_stats = self._relation_mapper.update_selection_layers(
            oks_layer, zu_layer, vypiska_data, geometry_data
        )
        result['oks_updated'] = update_stats.get('oks_updated', 0)
        # Добавляем к уже обновлённым ЗУ (из выписок ЗУ)
        result['zu_updated'] += update_stats.get('zu_updated', 0)

        # 8. Синхронизируем с нарезкой (если есть)
        sync_stats = self._cutting_sync.sync_cutting_layers(zu_layer)
        result['cutting_synced'] = sync_stats.get('features_synced', 0)

        # Итоговый лог
        log_success(
            f"M_23: Анализ завершён. "
            f"ОКС: {result['oks_updated']}, ЗУ: {result['zu_updated']}, "
            f"нарезка: {result['cutting_synced']}"
        )

        return result

    def check_data_availability(self) -> Dict[str, bool]:
        """
        Проверка доступности данных для анализа

        Returns:
            {
                'selection_zu': bool,        # Есть L_2_1_1 или Le_2_1_1_1
                'selection_oks': bool,       # Есть L_2_1_2
                'vypiska_oks': bool,         # Есть Le_1_6_2_* с полем Связанные_ЗУ
                'vypiska_zu': bool,          # Есть Le_1_6_1_* с полем Включенные_объекты
                'can_fill_geometry': bool,   # Можно заполнить ОКС_на_ЗУ_факт
                'can_fill_vypiska': bool,    # Можно заполнить ОКС_на_ЗУ_выписка (из выписок ОКС)
                'can_fill_zu_vypiska': bool  # Можно заполнить ОКС_на_ЗУ_выписка (из выписок ЗУ)
            }
        """
        result = {
            'selection_zu': False,
            'selection_oks': False,
            'vypiska_oks': False,
            'vypiska_zu': False,
            'can_fill_geometry': False,
            'can_fill_vypiska': False,
            'can_fill_zu_vypiska': False
        }

        project = QgsProject.instance()

        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue

            layer_name = layer.name()

            # Проверяем слой ЗУ выборки
            if self.ZU_LAYER_NAME in layer_name:
                if layer.featureCount() > 0:
                    result['selection_zu'] = True

            # Проверяем слой ОКС выборки
            if self.OKS_LAYER_NAME in layer_name:
                if layer.featureCount() > 0:
                    result['selection_oks'] = True

            # Проверяем слои выписок ОКС
            if layer_name.startswith(self.VYPISKA_OKS_PREFIX):
                # Проверяем наличие поля Связанные_ЗУ
                if layer.fields().indexOf(self.VYPISKA_FIELD) != -1:
                    if layer.featureCount() > 0:
                        result['vypiska_oks'] = True

            # Проверяем слои выписок ЗУ
            if layer_name.startswith(self.VYPISKA_ZU_PREFIX):
                # Проверяем наличие поля Включенные_объекты
                if layer.fields().indexOf(self.INCLUDED_OBJECTS_FIELD) != -1:
                    if layer.featureCount() > 0:
                        result['vypiska_zu'] = True

        # Определяем что можно заполнить
        # Геометрию можно заполнить если есть оба слоя выборки
        result['can_fill_geometry'] = result['selection_zu'] and result['selection_oks']

        # Выписку из ОКС можно заполнить если есть выборка ОКС И выписки ОКС
        result['can_fill_vypiska'] = (
            result['selection_zu'] and
            result['selection_oks'] and
            result['vypiska_oks']
        )

        # Выписку из ЗУ можно заполнить если есть выборка ЗУ И выписки ЗУ
        # (не требует наличия выборки ОКС!)
        result['can_fill_zu_vypiska'] = (
            result['selection_zu'] and
            result['vypiska_zu']
        )

        log_info(
            f"M_23: Доступность данных - "
            f"ЗУ: {result['selection_zu']}, ОКС: {result['selection_oks']}, "
            f"выписки_ОКС: {result['vypiska_oks']}, выписки_ЗУ: {result['vypiska_zu']}"
        )

        return result

    # ==================== НИЗКОУРОВНЕВЫЕ МЕТОДЫ ====================

    def analyze_geometry(
        self,
        oks_layer: QgsVectorLayer,
        zu_layer: QgsVectorLayer,
        min_intersection_area: float = 1.0
    ) -> Dict[str, List[str]]:
        """
        Геометрический анализ пересечений ОКС с ЗУ

        Args:
            oks_layer: Слой ОКС
            zu_layer: Слой ЗУ
            min_intersection_area: Минимальная площадь пересечения (м2)

        Returns:
            {КН_ОКС: [список_КН_ЗУ]}
        """
        return self._geometry_analyzer.analyze(
            oks_layer, zu_layer, min_intersection_area
        )

    def extract_vypiska_relations(
        self,
        oks_layer: QgsVectorLayer
    ) -> Dict[str, List[str]]:
        """
        Извлечение связей из выписок ОКС (поле "Связанные_ЗУ")

        Ищет в слоях Le_1_6_2_* по кадастровому номеру.

        Args:
            oks_layer: Слой ОКС (для получения списка КН)

        Returns:
            {КН_ОКС: [список_КН_ЗУ]}
        """
        result: Dict[str, List[str]] = {}

        # Собираем КН из слоя ОКС
        kn_idx = oks_layer.fields().indexOf('КН')
        for feature in oks_layer.getFeatures():
            kn = feature[kn_idx] if kn_idx >= 0 else None
            if kn:
                result[str(kn).strip()] = []  # Инициализируем пустым списком

        # Ищем слои выписок ОКС (Le_1_6_2_*)
        vypiska_layers = [
            layer for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsVectorLayer) and layer.name().startswith(self.VYPISKA_OKS_PREFIX)
        ]

        if not vypiska_layers:
            log_warning("M_23: Слои выписок ОКС (Le_1_6_2_*) не найдены")
            return result

        log_info(f"M_23: Найдено {len(vypiska_layers)} слоёв выписок ОКС")

        # Извлекаем данные из всех слоёв выписок
        for vypiska_layer in vypiska_layers:
            field_idx = vypiska_layer.fields().indexOf(self.VYPISKA_FIELD)
            if field_idx == -1:
                continue

            kn_field_idx = vypiska_layer.fields().indexOf('КН')
            if kn_field_idx == -1:
                continue

            for feature in vypiska_layer.getFeatures():
                kn = feature[kn_field_idx]
                if not kn:
                    continue

                kn = str(kn).strip()

                # Проверяем что этот КН есть в нашем списке ОКС
                if kn not in result:
                    continue

                vypiska_value = feature[field_idx]

                # Парсим значение (разделители: "; " или ", ")
                if vypiska_value and str(vypiska_value).strip() not in ('-', '', 'NULL'):
                    value_str = str(vypiska_value)
                    if ';' in value_str:
                        zu_list = [zu.strip() for zu in value_str.split(';')]
                    else:
                        zu_list = [zu.strip() for zu in value_str.split(',')]

                    # Фильтруем пустые и некорректные
                    zu_list = [
                        zu for zu in zu_list
                        if zu and zu not in ('-', 'NULL', '')
                    ]

                    if zu_list:
                        result[kn] = zu_list

        return result

    def update_selection_layers(
        self,
        oks_layer: QgsVectorLayer,
        zu_layer: QgsVectorLayer,
        vypiska_data: Optional[Dict[str, List[str]]],
        geometry_data: Optional[Dict[str, List[str]]]
    ) -> Dict[str, int]:
        """
        Обновление полей ОКС_на_ЗУ_* в слоях выборки

        Заполняет только те поля, для которых переданы данные (не None).

        Args:
            oks_layer: Слой ОКС
            zu_layer: Слой ЗУ
            vypiska_data: {КН_ОКС: [список_КН_ЗУ]} или None
            geometry_data: {КН_ОКС: [список_КН_ЗУ]} или None

        Returns:
            {'oks_updated': N, 'zu_updated': N}
        """
        return self._relation_mapper.update_selection_layers(
            oks_layer, zu_layer, vypiska_data, geometry_data
        )

    def sync_cutting_layers(
        self,
        zu_layer: QgsVectorLayer
    ) -> Dict[str, int]:
        """
        Синхронизация со слоями нарезки (Le_2_1_*, Le_2_7_*)

        Args:
            zu_layer: Слой выборки ЗУ

        Returns:
            {'layers_synced': N, 'features_synced': N}
        """
        return self._cutting_sync.sync_cutting_layers(zu_layer)

    def create_reverse_mapping(
        self,
        oks_to_zu: Dict[str, List[str]],
        oks_addresses: Optional[Dict[str, str]] = None
    ) -> Dict[str, List[str]]:
        """
        Создание обратного маппинга ЗУ -> ОКС

        Args:
            oks_to_zu: {КН_ОКС: [список_КН_ЗУ]}
            oks_addresses: {КН_ОКС: Адрес} (опционально)

        Returns:
            {КН_ЗУ: [список_КН_ОКС]} или {КН_ЗУ: ["КН - Адрес"]}
        """
        return self._relation_mapper.create_reverse_mapping(oks_to_zu, oks_addresses)

    # ==================== МЕТОДЫ ДЛЯ НАРЕЗКИ/КОРРЕКЦИИ ====================

    def analyze_cutting_geometry(
        self,
        geometry: 'QgsGeometry',
        source_kn: Optional[str] = None,
        oks_layer: Optional[QgsVectorLayer] = None
    ) -> Dict[str, str]:
        """
        Анализ ОКС для одной геометрии нарезки/коррекции.

        Определяет:
        - ОКС_на_ЗУ_выписка: копируется из исходного ЗУ, если НЕ НГС и есть выписка
        - ОКС_на_ЗУ_факт: геометрический анализ пересечения с ОКС

        Args:
            geometry: Геометрия нарезанного контура
            source_kn: КН исходного ЗУ (для определения НГС и поиска выписки)
            oks_layer: Слой ОКС (если None - ищет L_2_1_2_Выборка_ОКС)

        Returns:
            {'ОКС_на_ЗУ_выписка': str, 'ОКС_на_ЗУ_факт': str}
        """
        result = {
            'ОКС_на_ЗУ_выписка': '-',
            'ОКС_на_ЗУ_факт': '-'
        }

        if geometry is None or geometry.isEmpty():
            return result

        # Получаем слой ОКС
        if oks_layer is None:
            oks_layer = self._get_oks_selection_layer()

        if oks_layer is None or oks_layer.featureCount() == 0:
            log_info("M_23: Слой ОКС не найден или пуст, анализ пропущен")
            return result

        # 1. ОКС_на_ЗУ_выписка - только если НЕ НГС и есть выписка
        if source_kn and not self.is_ngs_land(source_kn):
            vypiska_relations = self._get_vypiska_for_kn(source_kn)
            if vypiska_relations:
                result['ОКС_на_ЗУ_выписка'] = '; '.join(sorted(vypiska_relations))

        # 2. ОКС_на_ЗУ_факт - геометрический анализ
        intersecting_oks = self._geometry_analyzer.analyze_single_geometry(
            geometry, oks_layer
        )
        if intersecting_oks:
            result['ОКС_на_ЗУ_факт'] = '; '.join(sorted(intersecting_oks))
            log_info(f"M_23 [debug]: КН={source_kn}, факт={result['ОКС_на_ЗУ_факт']}")

        return result

    def is_ngs_land(self, kn: Optional[str]) -> bool:
        """
        Проверка является ли земельный участок НГС (неразграниченные гос. земли).

        НГС определяется если:
        - КН пустой, None или "-"
        - КН = номер кадастрового квартала (без номера участка, заканчивается на :0)
        - КН имеет формат XX:XX:XXXXXXX (только 3 части вместо 4)

        Args:
            kn: Кадастровый номер

        Returns:
            True если НГС, False если обычный ЗУ с КН
        """
        if not kn or str(kn).strip() in ('', '-', 'NULL', 'None'):
            return True

        kn_str = str(kn).strip()

        # Формат КН: XX:XX:XXXXXXX:XXXX (4 части через двоеточие)
        parts = kn_str.split(':')

        # Если меньше 4 частей - это квартал, а не участок
        if len(parts) < 4:
            return True

        # Если 4-я часть = "0" - это тоже НГС (привязка к кварталу)
        if len(parts) == 4 and parts[3] in ('0', ''):
            return True

        return False

    def has_vypiska_for_kn(self, kn: str) -> bool:
        """
        Проверка наличия выписки ОКС для данного КН ЗУ.

        Ищет в выписках ОКС (Le_1_6_2_*) связь с этим КН ЗУ.

        Args:
            kn: Кадастровый номер ЗУ

        Returns:
            True если найдена выписка с этим КН в поле Связанные_ЗУ
        """
        if not kn or self.is_ngs_land(kn):
            return False

        kn_str = str(kn).strip()

        # Ищем слои выписок ОКС
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not layer.name().startswith(self.VYPISKA_OKS_PREFIX):
                continue

            field_idx = layer.fields().indexOf(self.VYPISKA_FIELD)
            if field_idx == -1:
                continue

            for feature in layer.getFeatures():
                vypiska_value = feature[field_idx]
                if not vypiska_value:
                    continue

                # Парсим список КН и проверяем точное вхождение
                value_str = str(vypiska_value)
                zu_list = [zu.strip() for zu in value_str.replace(';', ',').split(',')]
                if kn_str in zu_list:
                    return True

        return False

    def _get_vypiska_for_kn(self, kn: str) -> List[str]:
        """
        Получить список КН ОКС из выписок для данного КН ЗУ.

        Ищет в выписках ОКС (Le_1_6_2_*) все ОКС, которые связаны с этим КН ЗУ.

        Args:
            kn: Кадастровый номер ЗУ

        Returns:
            Список КН ОКС, связанных с этим ЗУ по выписке
        """
        result: List[str] = []

        if not kn or self.is_ngs_land(kn):
            return result

        kn_str = str(kn).strip()

        # Ищем слои выписок ОКС
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not layer.name().startswith(self.VYPISKA_OKS_PREFIX):
                continue

            field_idx = layer.fields().indexOf(self.VYPISKA_FIELD)
            kn_oks_idx = layer.fields().indexOf('КН')

            if field_idx == -1 or kn_oks_idx == -1:
                continue

            for feature in layer.getFeatures():
                vypiska_value = feature[field_idx]
                oks_kn = feature[kn_oks_idx]

                if not vypiska_value or not oks_kn:
                    continue

                # Парсим список КН и проверяем точное вхождение
                value_str = str(vypiska_value)
                zu_list = [zu.strip() for zu in value_str.replace(';', ',').split(',')]
                if kn_str in zu_list:
                    result.append(str(oks_kn).strip())

        return list(set(result))  # Убираем дубли

    # ==================== ПРИВАТНЫЕ МЕТОДЫ ====================

    def _get_zu_selection_layer(self) -> Optional[QgsVectorLayer]:
        """Получить слой выборки ЗУ"""
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            layer_name = layer.name()
            if self.ZU_LAYER_NAME in layer_name:
                return layer
        return None

    def _get_oks_selection_layer(self) -> Optional[QgsVectorLayer]:
        """Получить слой выборки ОКС"""
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if self.OKS_LAYER_NAME in layer.name():
                log_info(f"M_23 [debug]: Слой ОКС найден: '{layer.name()}', "
                        f"features={layer.featureCount()}")
                return layer
        # Диагностика: перечислить векторные слои для отладки
        vector_names = [l.name() for l in QgsProject.instance().mapLayers().values()
                       if isinstance(l, QgsVectorLayer)]
        log_info(f"M_23 [debug]: Слой '{self.OKS_LAYER_NAME}' не найден. "
                f"Векторных слоёв в проекте: {len(vector_names)}")
        return None

    # ==================== ПАКЕТНЫЙ АНАЛИЗ ДЛЯ НАРЕЗКИ ====================

    def analyze_features_batch(
        self,
        features_data: List[Dict[str, Any]],
        is_ngs: bool = False,
        attribute_setter: Optional[callable] = None,
        module_id: str = "M_23"
    ) -> List[Dict[str, Any]]:
        """
        Пакетный анализ ОКС_на_ЗУ для списка объектов нарезки.

        Единый метод для Msm_26_4_CuttingEngine.

        Для каждого объекта:
        - Определяет ОКС_на_ЗУ_выписка (из выписки, если есть КН и не НГС)
        - Пересчитывает ОКС_на_ЗУ_факт геометрически

        Args:
            features_data: Список данных объектов с 'geometry' и 'attributes'
            is_ngs: True если это НГС (неразграниченные гос. земли)
            attribute_setter: Функция установки значений в атрибуты
                              (attrs, oks_vypiska, oks_fact) -> attrs
                              Если None - устанавливает напрямую
            module_id: ID модуля для логирования (например, Msm_26_4)

        Returns:
            List[Dict]: Обновлённые данные с заполненными полями ОКС
        """
        if not features_data:
            return features_data

        # Получаем слой ОКС один раз для всех объектов
        oks_layer = self._get_oks_selection_layer()

        if oks_layer is None or oks_layer.featureCount() == 0:
            reason = "не найден" if oks_layer is None else "пуст (0 features)"
            log_info(f"{module_id}: Слой ОКС {reason}, анализ ОКС_на_ЗУ_факт пропущен "
                    f"({len(features_data)} объектов)")
            return features_data

        log_info(f"{module_id} [debug]: Начало анализа ОКС_на_ЗУ: {len(features_data)} объектов, "
                f"НГС={is_ngs}, слой ОКС={oks_layer.name()} ({oks_layer.featureCount()} ОКС)")

        analyzed_count = 0
        fact_filled = 0
        vypiska_filled = 0

        for item in features_data:
            geom = item.get('geometry')
            attrs = item.get('attributes', {})

            if not geom or geom.isEmpty():
                continue

            # Для НГС: выписка = "-" (нет КН), факт = пересчитать
            # Для обычных ЗУ: выписка = из выписки если есть, факт = пересчитать
            source_kn = None if is_ngs else attrs.get('КН')

            # Анализ через M_23
            oks_values = self.analyze_cutting_geometry(
                geometry=geom,
                source_kn=source_kn,
                oks_layer=oks_layer
            )

            # Подсчёт заполненных значений
            if oks_values.get('ОКС_на_ЗУ_факт', '-') != '-':
                fact_filled += 1
            if oks_values.get('ОКС_на_ЗУ_выписка', '-') != '-':
                vypiska_filled += 1

            # Установка значений в атрибуты
            if attribute_setter:
                attrs = attribute_setter(
                    attrs,
                    oks_vypiska=oks_values.get('ОКС_на_ЗУ_выписка'),
                    oks_fact=oks_values.get('ОКС_на_ЗУ_факт')
                )
            else:
                # Установка напрямую
                attrs['ОКС_на_ЗУ_выписка'] = oks_values.get('ОКС_на_ЗУ_выписка', '-')
                attrs['ОКС_на_ЗУ_факт'] = oks_values.get('ОКС_на_ЗУ_факт', '-')

            item['attributes'] = attrs
            analyzed_count += 1

        log_info(f"{module_id}: Анализ ОКС_на_ЗУ: обработано {analyzed_count} объектов "
                f"(НГС={is_ngs}), факт заполнен: {fact_filled}, выписка заполнена: {vypiska_filled}")

        return features_data
