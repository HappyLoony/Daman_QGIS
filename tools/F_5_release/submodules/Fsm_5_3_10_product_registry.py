# -*- coding: utf-8 -*-
"""
Fsm_5_3_10 - Реестр продуктов экспорта

Слой продуктов поверх слоя шаблонов (Fsm_5_3_8). Пользователь выбирает ЧТО
нужно (продукт), а состав слоёв и файлов определяется динамически.

Продукты:
- vedomost_ozu  - Ведомость ОЗУ (1 файл на ЗПР, merged-ведомость)
- coord_ozu     - Перечни координат ОЗУ (1 файл на ЗПР; при этапности 3 файла)
- coord_ps      - Перечни координат ПС (per-layer items с существующими template_id)
- coord_gpmt    - Перечень координат ГПМТ (выбор шаблона COORD_GPMT / COORD_GPMT_IZM)

Два публичных метода интроспекции/раскрытия:
- describe(product_id) - NON-MUTATING интроспекция для GUI (доступность, состав,
  искомые паттерны), БЕЗ создания items.
- expand(product_id)   - раскрытие продукта в items {layer, template, extra_context}
  для экспортного цикла F_5_3.

Оба метода используют ОБЩИЙ внутренний helper _resolve_groups для детекции —
одна логика обнаружения, два потребителя (запрет рассинхрона describe/expand).

Инварианты обнаружения слоёв (§4.1 плана):
- Состав продукта (явный перечень типов слоёв per продукт per режим) — единственный
  источник перечня для ОБОИХ потребителей. Фильтрация по СОСТАВУ ПРОДУКТА, не по
  наличию слоёв в проекте (Le_2_7_3_3_Без_Меж_Итог существует/непуст, но вне состава).
- Полные имена слоёв резолвятся через константы constants.py (LAYER_CUTTING_*,
  LAYER_STAGING_*, LAYER_GPMT*). Glob-обнаружение запрещено.
- Слой в составе = существует в проекте (mapLayersByName по точному имени) И
  featureCount() > 0.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional

from qgis.core import QgsProject, QgsVectorLayer

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS import constants

from .Fsm_5_3_8_template_registry import (
    DocumentTemplate,
    TemplateRegistry,
    COORD_GPMT,
)

# COORD_GPMT_IZM создаётся параллельной Фазой 4. Импортируем по имени; при
# отсутствии (Фаза 4 ещё не выполнена) оставляем None — coord_gpmt при непустом
# Изм-слое деградирует к COORD_GPMT с log_warning, экспорт не падает.
try:
    from .Fsm_5_3_8_template_registry import COORD_GPMT_IZM  # type: ignore
except ImportError:
    COORD_GPMT_IZM = None  # type: ignore
    log_warning(
        "Fsm_5_3_10: COORD_GPMT_IZM не найден в Fsm_5_3_8 "
        "(параллельная Фаза 4 ещё не выполнена); coord_gpmt при непустом Изм-слое "
        "будет использовать COORD_GPMT"
    )


@dataclass
class ExportProduct:
    """Продукт экспорта (единица выбора в GUI)"""

    product_id: str          # 'vedomost_ozu' | 'coord_ozu' | 'coord_ps' | 'coord_gpmt'
    name: str
    description: str         # tooltip


# Реестр продуктов (порядок = порядок отрисовки в GUI)
EXPORT_PRODUCTS: List[ExportProduct] = [
    ExportProduct(
        product_id='vedomost_ozu',
        name='Ведомость ОЗУ',
        description='Ведомость образуемых земельных участков по каждой ЗПР '
                    '(Раздел, НГС, Без_Меж, Изм). Один файл на ЗПР. '
                    'При этапности ОКС — единый файл: Этап 1 и Этап 2 '
                    '(Раздел, НГС) + Без_Меж.',
    ),
    ExportProduct(
        product_id='coord_ozu',
        name='Перечни координат ОЗУ',
        description='Перечни координат характерных точек образуемых земельных '
                    'участков (Раздел, НГС) по каждой ЗПР. Один файл на ЗПР; '
                    'при этапности ОКС — единый файл: Этап 1 и Этап 2.',
    ),
    ExportProduct(
        product_id='coord_ps',
        name='Перечни координат ПС',
        description='Перечни координат характерных точек контуров публичных '
                    'сервитутов по всем ЗПР с непустыми ПС-слоями.',
    ),
    ExportProduct(
        product_id='coord_gpmt',
        name='Перечень координат ГПМТ',
        description='Перечень координат характерных точек границ территории '
                    'проекта межевания. При наличии слоя внесения изменений — '
                    'приоритет варианта Изм.',
    ),
]


# === Описание ЗПР-групп (нарезка, без этапности) ===
# Каждая группа = один ЗПР. layer_types — упорядоченный словарь типов работ:
# тип -> полное имя слоя (константа constants.py). Порядок ключей задаёт порядок
# в merged_layers (для перечней: Раздел, НГС; для ведомости: Раздел, НГС,
# Без_Меж, Изм). Group_key = стабильный ключ группы для маркеров.

# Группы нарезки (Le_2_1_*, Le_2_2_*). Изм существует только у ОКС/ПО/ВО.
_CUTTING_GROUPS: List[Dict[str, Any]] = [
    {
        'group_key': 'oks',
        'group_name': 'ОКС',
        'razdel': constants.LAYER_CUTTING_OKS_RAZDEL,
        'ngs': constants.LAYER_CUTTING_OKS_NGS,
        'bez_mezh': constants.LAYER_CUTTING_OKS_BEZ_MEZH,
        'ps': constants.LAYER_CUTTING_OKS_PS,
        'izm': constants.LAYER_CUTTING_OKS_IZM,
        'template_razdel': 'coord_cutting_oks_razdel',
        'template_ngs': 'coord_cutting_oks_ngs',
        'template_ps': 'coord_cutting_oks_ps',
    },
    {
        'group_key': 'po',
        'group_name': 'ПО',
        'razdel': constants.LAYER_CUTTING_PO_RAZDEL,
        'ngs': constants.LAYER_CUTTING_PO_NGS,
        'bez_mezh': constants.LAYER_CUTTING_PO_BEZ_MEZH,
        'ps': constants.LAYER_CUTTING_PO_PS,
        'izm': constants.LAYER_CUTTING_PO_IZM,
        'template_razdel': 'coord_cutting_lo',
        'template_ngs': 'coord_cutting_lo',
        'template_ps': 'coord_cutting_lo',
    },
    {
        'group_key': 'vo',
        'group_name': 'ВО',
        'razdel': constants.LAYER_CUTTING_VO_RAZDEL,
        'ngs': constants.LAYER_CUTTING_VO_NGS,
        'bez_mezh': constants.LAYER_CUTTING_VO_BEZ_MEZH,
        'ps': constants.LAYER_CUTTING_VO_PS,
        'izm': constants.LAYER_CUTTING_VO_IZM,
        'template_razdel': 'coord_cutting_vo',
        'template_ngs': 'coord_cutting_vo',
        'template_ps': 'coord_cutting_vo',
    },
    {
        'group_key': 'rek_ad',
        'group_name': 'РЕК АД',
        'razdel': constants.LAYER_CUTTING_REK_AD_RAZDEL,
        'ngs': constants.LAYER_CUTTING_REK_AD_NGS,
        'bez_mezh': constants.LAYER_CUTTING_REK_AD_BEZ_MEZH,
        'ps': constants.LAYER_CUTTING_REK_AD_PS,
        'izm': None,
        'template_razdel': 'coord_cutting_rek_ad',
        'template_ngs': 'coord_cutting_rek_ad',
        'template_ps': 'coord_cutting_rek_ad',
    },
    {
        'group_key': 'seti_po',
        'group_name': 'СЕТИ ПО',
        'razdel': constants.LAYER_CUTTING_SETI_PO_RAZDEL,
        'ngs': constants.LAYER_CUTTING_SETI_PO_NGS,
        'bez_mezh': constants.LAYER_CUTTING_SETI_PO_BEZ_MEZH,
        'ps': constants.LAYER_CUTTING_SETI_PO_PS,
        'izm': None,
        'template_razdel': 'coord_cutting_seti_po',
        'template_ngs': 'coord_cutting_seti_po',
        'template_ps': 'coord_cutting_seti_po',
    },
    {
        'group_key': 'seti_vo',
        'group_name': 'СЕТИ ВО',
        'razdel': constants.LAYER_CUTTING_SETI_VO_RAZDEL,
        'ngs': constants.LAYER_CUTTING_SETI_VO_NGS,
        'bez_mezh': constants.LAYER_CUTTING_SETI_VO_BEZ_MEZH,
        'ps': constants.LAYER_CUTTING_SETI_VO_PS,
        'izm': None,
        'template_razdel': 'coord_cutting_seti_vo',
        'template_ngs': 'coord_cutting_seti_vo',
        'template_ps': 'coord_cutting_seti_vo',
    },
    {
        'group_key': 'ne',
        'group_name': 'НЭ',
        'razdel': constants.LAYER_CUTTING_NE_RAZDEL,
        'ngs': constants.LAYER_CUTTING_NE_NGS,
        'bez_mezh': constants.LAYER_CUTTING_NE_BEZ_MEZH,
        'ps': constants.LAYER_CUTTING_NE_PS,
        'izm': None,
        'template_razdel': 'coord_cutting_ne',
        'template_ngs': 'coord_cutting_ne',
        'template_ps': 'coord_cutting_ne',
    },
]


# Группы этапности ОКС (Le_2_7_*). После рефактора F_2_4 (план
# _PLAN_F_2_4_final_layer_cleanup, §4.4) этот список используется ТОЛЬКО для
# детекции активной этапности (_is_staging_active по Раздел/НГС каждого этапа) и
# для карты _GROUP_KEY_TO_NAME. Составы продуктов при этапности собираются
# явными единими 'oks'-группами прямо в _resolve_groups (перечень: Этап-1+Этап-2
# Раздел/НГС; ведомость: то же + Без_Меж_Итог), НЕ из этого списка per-stage.
# ПС/Изм-слоёв этапности F_2_4 не создаёт вообще (§3 «Факты о слоях этапности»).
_STAGING_GROUPS: List[Dict[str, Any]] = [
    {
        'group_key': 'oks_stage_1',
        'group_name': 'ОКС_Этап_1',
        'stage_label': 'Этап 1',
        'razdel': constants.LAYER_STAGING_1_RAZDEL,
        'ngs': constants.LAYER_STAGING_1_NGS,
        'template_coord': 'coord_stage_1',
    },
    {
        'group_key': 'oks_stage_2',
        'group_name': 'ОКС_Этап_2',
        'stage_label': 'Этап 2',
        'razdel': constants.LAYER_STAGING_2_RAZDEL,
        'ngs': constants.LAYER_STAGING_2_NGS,
        'template_coord': 'coord_stage_2',
    },
    {
        'group_key': 'oks_stage_final',
        'group_name': 'ОКС_Итог',
        'stage_label': 'Итог',
        'razdel': constants.LAYER_STAGING_FINAL_RAZDEL,
        'ngs': constants.LAYER_STAGING_FINAL_NGS,
        'template_coord': 'coord_stage_final',
    },
]


class ProductRegistry:
    """Реестр продуктов экспорта (статический)"""

    @staticmethod
    def get_products() -> List[ExportProduct]:
        """
        Получить список всех продуктов экспорта.

        Returns:
            Список ExportProduct в порядке отрисовки GUI.
        """
        return EXPORT_PRODUCTS

    @staticmethod
    def describe(product_id: str) -> Dict[str, Any]:
        """
        NON-MUTATING интроспекция продукта для GUI.

        НЕ создаёт items — только сообщает доступность, состав найденных групп
        (имена/этапы) и искомые паттерны слоёв. GUI рисует доступность/tooltip/
        подтекст ТОЛЬКО через этот метод (expand() для отрисовки НЕ вызывается).

        Использует общий helper _resolve_groups (та же детекция, что expand).

        Args:
            product_id: Идентификатор продукта.

        Returns:
            {
                available: bool,
                groups: [{name: str, layers_found: [str], stages: [str]}],
                searched_patterns: [str],
            }
        """
        try:
            groups, searched_patterns = ProductRegistry._resolve_groups(product_id)
        except Exception as e:
            log_error(f"Fsm_5_3_10 (describe): ошибка детекции '{product_id}': {e}")
            return {'available': False, 'groups': [], 'searched_patterns': []}

        groups_info: List[Dict[str, Any]] = []
        for grp in groups:
            stages = [grp['stage_label']] if grp.get('stage_label') else []
            groups_info.append({
                'name': grp['group_name'],
                'layers_found': [lyr.name() for lyr in grp['layers']],
                'stages': stages,
            })

        result = {
            'available': len(groups_info) > 0,
            'groups': groups_info,
            'searched_patterns': searched_patterns,
        }
        log_info(
            f"Fsm_5_3_10 (describe): продукт '{product_id}' "
            f"available={result['available']}, групп={len(groups_info)}"
        )
        return result

    @staticmethod
    def expand(product_id: str) -> List[Dict[str, Any]]:
        """
        Раскрыть продукт в items для экспортного цикла F_5_3.

        Вызывается ТОЛЬКО при экспорте (не для отрисовки GUI).

        Контракт item: {layer, template, extra_context}.
        - layer: QgsVectorLayer или None (для merged-ведомости).
        - template: DocumentTemplate.
        - extra_context: маркеры продукта (product_id, group_key) и (для merged)
          merged_layers / group_name / filename_override / vedomost_merged.

        Args:
            product_id: Идентификатор продукта.

        Returns:
            Список items. Пустой список если продукт недоступен.
        """
        try:
            if product_id == 'vedomost_ozu':
                return ProductRegistry._expand_vedomost_ozu()
            if product_id == 'coord_ozu':
                return ProductRegistry._expand_coord_ozu()
            if product_id == 'coord_ps':
                return ProductRegistry._expand_coord_ps()
            if product_id == 'coord_gpmt':
                return ProductRegistry._expand_coord_gpmt()

            log_warning(f"Fsm_5_3_10 (expand): неизвестный продукт '{product_id}'")
            return []
        except Exception as e:
            log_error(f"Fsm_5_3_10 (expand): ошибка раскрытия '{product_id}': {e}")
            return []

    # === Внутренние helpers ===

    @staticmethod
    def _find_layer(layer_name: str) -> Optional[QgsVectorLayer]:
        """
        Найти слой проекта по точному имени; вернуть только если он валиден,
        является векторным и непуст (featureCount > 0).

        Args:
            layer_name: Точное имя слоя.

        Returns:
            QgsVectorLayer или None.
        """
        try:
            matches = QgsProject.instance().mapLayersByName(layer_name)
        except Exception as e:
            log_warning(f"Fsm_5_3_10 (_find_layer): ошибка поиска '{layer_name}': {e}")
            return None

        for layer in matches:
            if not isinstance(layer, QgsVectorLayer):
                continue
            try:
                if not layer.isValid():
                    continue
                if layer.featureCount() > 0:
                    return layer
            except Exception as e:
                log_warning(
                    f"Fsm_5_3_10 (_find_layer): ошибка проверки слоя '{layer_name}': {e}"
                )
                continue
        return None

    @staticmethod
    def _is_staging_active() -> bool:
        """
        Триггер этапности: в проекте есть непустые слои Раздел/НГС этапов
        (детекция по явным именам, НЕ по glob). Этапность только для ОКС.

        Returns:
            True если хотя бы один этапный Раздел/НГС-слой непуст.
        """
        for grp in _STAGING_GROUPS:
            if (ProductRegistry._find_layer(grp['razdel']) is not None
                    or ProductRegistry._find_layer(grp['ngs']) is not None):
                return True
        return False

    @staticmethod
    def _conditional_numbers(layer: QgsVectorLayer) -> set:
        """
        Множество непустых условных номеров ЗУ (поле Услов_КН) слоя.

        Args:
            layer: Слой нарезки или этапности.

        Returns:
            Множество строк; пустое, если поля нет либо все значения пусты.
        """
        if layer.fields().indexOf('Услов_КН') < 0:
            return set()

        numbers = set()
        try:
            for feature in layer.getFeatures():
                value = feature.attribute('Услов_КН')
                if value in (None, '', '-'):
                    continue
                numbers.add(str(value).strip())
        except Exception as e:
            log_warning(
                f"Fsm_5_3_10 (_conditional_numbers): слой '{layer.name()}': {e}"
            )
            return set()
        return numbers

    @staticmethod
    def _staging_mismatch_message(
        cutting_name: str,
        stage1_name: str,
        cutting_numbers: set,
        stage1_numbers: set
    ) -> Optional[str]:
        """
        Текст расхождения нарезки и 1 этапа либо None, если расхождения нет.

        Чистая функция (множества строк на входе, строка на выходе) — вынесена
        отдельно, чтобы её можно было проверить без QGIS
        (`scripts/check_staging_sync.py`).

        Args:
            cutting_name: Имя слоя нарезки.
            stage1_name: Имя слоя 1 этапа.
            cutting_numbers: Условные номера нарезки.
            stage1_numbers: Условные номера 1 этапа.

        Returns:
            Сообщение для log_error либо None.
        """
        if not cutting_numbers or not stage1_numbers:
            return None  # нет субъекта сверки: сторона пуста или без Услов_КН
        if cutting_numbers == stage1_numbers:
            return None

        only_cutting = sorted(cutting_numbers - stage1_numbers)
        only_stage1 = sorted(stage1_numbers - cutting_numbers)
        parts = [
            f"Fsm_5_3_10: этапность не соответствует нарезке — "
            f"'{cutting_name}' ({len(cutting_numbers)} ЗУ) и "
            f"'{stage1_name}' ({len(stage1_numbers)} ЗУ) содержат разные "
            f"условные номера. Слой 1 этапа — копия нарезки, значит нарезку "
            f"перестроили после F_2_4; экспорт отдаст устаревшие контуры. "
            f"Перезапустите F_2_4"
        ]
        if only_cutting:
            parts.append(
                f"; только в нарезке ({len(only_cutting)}): "
                f"{', '.join(only_cutting[:5])}"
            )
        if only_stage1:
            parts.append(
                f"; только в 1 этапе ({len(only_stage1)}): "
                f"{', '.join(only_stage1[:5])}"
            )
        return ''.join(parts)

    @staticmethod
    def _check_staging_matches_cutting() -> None:
        """
        Инвариант актуальности этапности: слой 1 этапа — копия нарезки, поэтому
        составы условных номеров обязаны совпадать.

        Расхождение = нарезку перестроили (F_2_1 / F_2_3) уже ПОСЛЕ F_2_4, а слои
        этапности остались прежними: экспорт молча отдал бы устаревшие контуры.
        Сигнал через log_error (НЕ assert — плагин не крашить); control-flow НЕ
        меняется, решение за владельцем (перезапустить F_2_4 либо выгрузить как
        есть).

        Непустая нарезка при активной этапности — НОРМА, не аномалия: F_2_4 читает
        её как источник (Fsm_2_4_6) и не удаляет, её же читают F_2_7, F_2_5, F_3_1,
        F_2_3. Прежняя редакция инварианта (до 2026-08-19) считала это нарушением и
        давала log_error на каждом обращении к продуктам.
        """
        pairs = (
            (constants.LAYER_CUTTING_OKS_RAZDEL, constants.LAYER_STAGING_1_RAZDEL),
            (constants.LAYER_CUTTING_OKS_NGS, constants.LAYER_STAGING_1_NGS),
        )

        for cutting_name, stage1_name in pairs:
            cutting = ProductRegistry._find_layer(cutting_name)
            stage1 = ProductRegistry._find_layer(stage1_name)
            if cutting is None or stage1 is None:
                # Одной стороны нет — сверять нечего (законно: F_2_3 удаляет
                # пустой НГС, F_2_4 не строит этап по отсутствующей ветке)
                continue

            message = ProductRegistry._staging_mismatch_message(
                cutting_name, stage1_name,
                ProductRegistry._conditional_numbers(cutting),
                ProductRegistry._conditional_numbers(stage1)
            )
            if message:
                log_error(message)

    @staticmethod
    def _resolve_groups(product_id: str):
        """
        ОБЩИЙ helper детекции для describe() и expand().

        Возвращает группы продукта с непустыми слоями состава + список искомых
        паттернов (полных имён слоёв). Фильтрация по СОСТАВУ ПРОДУКТА, не по
        наличию любых слоёв группы (запрет рассинхрона describe/expand).

        Для каждой группы поле 'layers' — список найденных непустых QgsVectorLayer
        по составу продукта; поле 'resolved' — словарь {тип: QgsVectorLayer} для
        точечного доступа в expanders. Группа включается, только если найден хотя
        бы один слой её состава.

        КЛАСС ДЕФЕКТА (прецедент 2026-07-09, отклонение 2 плана F_2_4): 'resolved'
        НЕНАДЁЖЕН при ДУБЛЯХ ТИПОВ в composition. Единая этапная ОКС-группа несёт
        [razdel, ngs, razdel, ngs] (Этап-1 и Этап-2): одинаковый ключ типа
        перезаписывается, в resolved останется ПОСЛЕДНИЙ слой типа (Этап-2), Этап-1
        теряется. Expander над мульти-слойной группой ОБЯЗАН итерировать
        'layers'/'layer_types' (сохраняют дубли), НЕ resolved[type]. resolved
        корректен ТОЛЬКО для групп с уникальными типами (нарезные ЗПР, ПС, GPMT).
        При добавлении этапности к ПС/иному продукту — перепроверить его expander.

        Args:
            product_id: Идентификатор продукта.

        Returns:
            (groups, searched_patterns):
              groups - список dict с ключами исходной группы + 'layers' + 'resolved'.
              searched_patterns - список полных имён слоёв, по которым шёл поиск.
        """
        groups: List[Dict[str, Any]] = []
        searched_patterns: List[str] = []

        if product_id == 'coord_gpmt':
            # ГПМТ — не ЗПР-группы; обрабатывается отдельно в expand/describe.
            searched_patterns = [
                constants.LAYER_GPMT,
                constants.LAYER_GPMT_VNES_IZM,
            ]
            resolved: Dict[str, QgsVectorLayer] = {}
            found_layers: List[QgsVectorLayer] = []
            gpmt_base = ProductRegistry._find_layer(constants.LAYER_GPMT)
            gpmt_izm = ProductRegistry._find_layer(constants.LAYER_GPMT_VNES_IZM)
            if gpmt_base is not None:
                resolved['gpmt'] = gpmt_base
                found_layers.append(gpmt_base)
            if gpmt_izm is not None:
                resolved['izm'] = gpmt_izm
                found_layers.append(gpmt_izm)
            if found_layers:
                groups.append({
                    'group_key': 'gpmt',
                    'group_name': 'ГПМТ',
                    'layers': found_layers,
                    'resolved': resolved,
                })
            return groups, searched_patterns

        staging_active = ProductRegistry._is_staging_active()

        # Перечни координат ОЗУ: Раздел + НГС. При этапности ОКС — ОДНА этапная
        # группа (group_key='oks') из слоёв Этап-1 и Этап-2 (§4.4). post-grouping
        # F_5_3 сольёт per-layer items в ОДИН файл на ЗПР ОКС. Без_Меж НЕ включается
        # (у Без_Меж нет точечного слоя — Fsm_5_3_1 искал бы несуществующий Т-слой).
        if product_id == 'coord_ozu':
            for cgrp in _CUTTING_GROUPS:
                if cgrp['group_key'] == 'oks' and staging_active:
                    continue  # ОКС из нарезки заменяется единой этапной группой
                composition = [
                    ('razdel', cgrp['razdel']),
                    ('ngs', cgrp['ngs']),
                ]
                searched_patterns.extend(name for _t, name in composition)
                grp = ProductRegistry._build_group(cgrp, composition)
                if grp is not None:
                    groups.append(grp)
            if staging_active:
                ProductRegistry._check_staging_matches_cutting()
                # Единая группа 'oks': [Этап-1 Раздел/НГС, Этап-2 Раздел/НГС].
                # Порядок по этапу (читабельнее). Шаблон coord_stage_final (title
                # generic, filename overridden post-grouping'ом на '..._ОКС').
                composition = [
                    ('razdel', constants.LAYER_STAGING_1_RAZDEL),
                    ('ngs', constants.LAYER_STAGING_1_NGS),
                    ('razdel', constants.LAYER_STAGING_2_RAZDEL),
                    ('ngs', constants.LAYER_STAGING_2_NGS),
                ]
                searched_patterns.extend(name for _t, name in composition)
                oks_stage_grp = {
                    'group_key': 'oks',
                    'group_name': 'ОКС',
                    'template_coord': 'coord_stage_final',
                }
                grp = ProductRegistry._build_group(oks_stage_grp, composition)
                if grp is not None:
                    groups.append(grp)
            return groups, searched_patterns

        # Перечни координат ПС: ПС-слой каждой ЗПР-группы (этапных ПС не существует).
        if product_id == 'coord_ps':
            for cgrp in _CUTTING_GROUPS:
                composition = [('ps', cgrp['ps'])]
                searched_patterns.extend(name for _t, name in composition)
                grp = ProductRegistry._build_group(cgrp, composition)
                if grp is not None:
                    groups.append(grp)
            return groups, searched_patterns

        # Ведомость ОЗУ: Раздел + НГС + Без_Меж + Изм. При этапности ОКС (v5,
        # снятие решения #13) — единый файл: Этап-1+Этап-2 Раздел/НГС + Без_Меж_Итог.
        if product_id == 'vedomost_ozu':
            for cgrp in _CUTTING_GROUPS:
                if cgrp['group_key'] == 'oks' and staging_active:
                    continue  # ОКС-ведомость берётся из Итога этапности
                composition = [
                    ('razdel', cgrp['razdel']),
                    ('ngs', cgrp['ngs']),
                    ('bez_mezh', cgrp['bez_mezh']),
                ]
                if cgrp.get('izm') is not None:
                    composition.append(('izm', cgrp['izm']))
                searched_patterns.extend(name for _t, name in composition)
                grp = ProductRegistry._build_group(cgrp, composition)
                if grp is not None:
                    groups.append(grp)
            if staging_active:
                ProductRegistry._check_staging_matches_cutting()
                # v5 (снятие решения #13): единый файл-ведомость на ЗПР ОКС из 5
                # слоёв — Этап-1 Раздел/НГС, Этап-2 Раздел/НГС, Без_Меж_Итог.
                # Источник Раздел/НГС = Этап-1+Этап-2 (НЕ Итог): Итог после §4.2
                # чистится от временных, а ведомость по требованию содержит и
                # основные, и временные → дубли территории (100/101 + ID=ЗПР)
                # НАМЕРЕННЫ, консистентны с перечнем [Р1,НГС1,Р2,НГС2]. Без_Меж
                # берётся из LAYER_STAGING_FINAL_BEZ_MEZH (единый непустой final —
                # у Без_Меж нет этапного деления). Порядок: Раздел/НГС по этапу,
                # Без_Меж последним (конвенция Раздел->НГС->Без_Меж).
                # СЦЕПКА С §4.1: Общая_земля объединённых (строки Этап-2)
                # наследуется из слоя Этап-2, который получает Общая_земля ТОЛЬКО
                # через §4.1 (assign_vri_to_features на stage2_data).
                composition = [
                    ('razdel', constants.LAYER_STAGING_1_RAZDEL),
                    ('ngs', constants.LAYER_STAGING_1_NGS),
                    ('razdel', constants.LAYER_STAGING_2_RAZDEL),
                    ('ngs', constants.LAYER_STAGING_2_NGS),
                    ('bez_mezh', constants.LAYER_STAGING_FINAL_BEZ_MEZH),
                ]
                searched_patterns.extend(name for _t, name in composition)
                # Итог-ведомость использует имя группы 'ОКС' (один файл на ЗПР ОКС)
                vedomost_oks_grp = {
                    'group_key': 'oks',
                    'group_name': 'ОКС',
                }
                grp = ProductRegistry._build_group(vedomost_oks_grp, composition)
                if grp is not None:
                    groups.append(grp)
            return groups, searched_patterns

        log_warning(f"Fsm_5_3_10 (_resolve_groups): неизвестный продукт '{product_id}'")
        return groups, searched_patterns

    @staticmethod
    def _build_group(
        source_group: Dict[str, Any],
        composition: List[tuple]
    ) -> Optional[Dict[str, Any]]:
        """
        Построить группу с найденными непустыми слоями по составу.

        Args:
            source_group: Исходная dict-группа (_CUTTING_GROUPS / _STAGING_GROUPS).
            composition: Упорядоченный список (тип, полное_имя_слоя) состава.

        Returns:
            Копия source_group с добавленными 'layers' (упорядоченный список
            найденных слоёв), 'layer_types' (параллельный список типов, СОХРАНЯЕТ
            дубли типов — например [razdel, ngs, razdel, ngs] для единой этапной
            ОКС-группы) и 'resolved' ({тип: QgsVectorLayer}, дубли перезаписываются
            — потребители дублей типов читают layers/layer_types, не resolved).
            None если ни один слой состава не найден.
        """
        resolved: Dict[str, QgsVectorLayer] = {}
        layers: List[QgsVectorLayer] = []
        layer_types: List[str] = []
        for layer_type, layer_name in composition:
            layer = ProductRegistry._find_layer(layer_name)
            if layer is not None:
                resolved[layer_type] = layer
                layers.append(layer)
                layer_types.append(layer_type)

        if not layers:
            return None

        grp = dict(source_group)
        grp['layers'] = layers
        grp['layer_types'] = layer_types
        grp['resolved'] = resolved
        return grp

    @staticmethod
    def _select_coord_template(
        layer: QgsVectorLayer,
        preferred_template_id: str
    ) -> Optional[DocumentTemplate]:
        """
        Выбрать шаблон для слоя так же, как старый GUI: тот же набор кандидатов
        TemplateRegistry.get_templates_for_layer, отфильтрованный по
        doc_type == 'coordinate_list', и из него — шаблон с нужным template_id.

        Разделение по типу работы (Раздел/НГС/ПС) делает expander по ЯВНОМУ
        перечню слоёв, а не по шаблону: generic-шаблон не-ОКС групп
        (coord_cutting_lo и т.п.) тип работы не различает. Поэтому шаблон ищется
        строго по preferred_template_id среди coordinate_list-кандидатов слоя.

        Args:
            layer: Слой-источник.
            preferred_template_id: Ожидаемый template_id (тот же, что назначил бы
                старый GUI этому слою).

        Returns:
            DocumentTemplate или None если не найден среди кандидатов слоя.
        """
        candidates = TemplateRegistry.get_templates_for_layer(layer.name())
        coord_candidates = [
            t for t in candidates if t.doc_type == 'coordinate_list'
        ]
        for template in coord_candidates:
            if template.template_id == preferred_template_id:
                return template

        # Fallback (rev-impl P-1, вариант "в"): суффиксные паттерны ОКС-шаблонов
        # (Le_2_1_1_*_Раздел) НЕ матчат реальные имена слоёв с хвостом _ЗПР_ОКС —
        # латентный баг matches_layer (якорный regex). Берём шаблон напрямую по
        # template_id: продукт сам гарантирует соответствие слоя группе через
        # явный перечень слоёв (matches_layer для этого пути избыточен).
        # Решение пользователя 2026-06-04: ОКС Раздел/НГС включаются в 78-split
        # (конфиг Msm_37_1 изначально содержит их template_id); наследование ID
        # контуров сохранено — SplitByFeatureModifier именует per-feature файлы
        # по полю ID фичи, а не порядковым номером.
        template = TemplateRegistry.get_template_by_id(preferred_template_id)
        if template is not None:
            log_info(
                f"Fsm_5_3_10 (_select_coord_template): шаблон "
                f"'{preferred_template_id}' для слоя '{layer.name()}' взят по "
                f"template_id (суффиксный паттерн source_layers не матчит имя)"
            )
            return template

        log_warning(
            f"Fsm_5_3_10 (_select_coord_template): для слоя '{layer.name()}' "
            f"шаблон '{preferred_template_id}' не найден ни среди "
            f"{len(coord_candidates)} coordinate_list-кандидатов, ни по id"
        )
        return None

    # === Expanders ===

    @staticmethod
    def _expand_vedomost_ozu() -> List[Dict[str, Any]]:
        """
        Ведомость ОЗУ: один merged-item на ЗПР-группу.

        item: {layer: None, template: VEDOMOST_OZU, extra_context: {
            vedomost_merged: True, merged_layers: [QgsVectorLayer...],
            group_name, product_id, group_key,
            filename_override: 'Ведомость_ОЗУ_{group_name}'
        }}.

        filename_override ОБЯЗАТЕЛЕН (debate-3 B): шаблон VEDOMOST_OZU статичен,
        без override merged-ведомости всех ЗПР получили бы одно имя и перезаписали
        бы друг друга (silent data loss, нарушение решения #1). Override резолвится
        экспортёром (_export_vedomost_merged).
        """
        items: List[Dict[str, Any]] = []

        template = TemplateRegistry.get_template_by_id('vedomost_ozu')
        if template is None:
            log_warning(
                "Fsm_5_3_10 (_expand_vedomost_ozu): шаблон 'vedomost_ozu' не найден "
                "в Fsm_5_3_8 (создаётся Фазой 3); ведомость не раскрыта"
            )
            return items

        groups, _patterns = ProductRegistry._resolve_groups('vedomost_ozu')
        for grp in groups:
            # Нарезка: Раздел -> НГС -> Без_Меж -> Изм.
            # Этапность (v5): Этап-1 Раздел/НГС -> Этап-2 Раздел/НГС -> Без_Меж_Итог.
            merged_layers = grp['layers']
            group_name = grp['group_name']
            items.append({
                'layer': None,
                'template': template,
                'extra_context': {
                    'vedomost_merged': True,
                    'merged_layers': merged_layers,
                    'group_name': group_name,
                    'product_id': 'vedomost_ozu',
                    'group_key': grp['group_key'],
                    'filename_override': f"Ведомость_ОЗУ_{group_name}",
                },
            })

        log_info(
            f"Fsm_5_3_10 (_expand_vedomost_ozu): раскрыто {len(items)} "
            f"merged-ведомостей"
        )
        return items

    @staticmethod
    def _expand_coord_ozu() -> List[Dict[str, Any]]:
        """
        Перечни координат ОЗУ: per-layer items (Раздел, НГС) с существующими
        template_id. Слияние «один файл на ЗПР» — ПОСЛЕ модификаторов
        (post-grouping Фазы 5). Маркеры {product_id: 'coord_ozu', group_key}.

        Этапность ОКС: ОКС-группа из нарезки не выдаётся (решено в _resolve_groups),
        вместо неё этапные группы (template_id coord_stage_1/2/final).
        """
        items: List[Dict[str, Any]] = []

        groups, _patterns = ProductRegistry._resolve_groups('coord_ozu')
        for grp in groups:
            # template_id зависит от режима: нарезка -> per-work-type шаблон,
            # этапность -> единый этапный шаблон группы.
            stage_template_id = grp.get('template_coord')

            # Итерируем по УПОРЯДОЧЕННОМУ списку (layers/layer_types), а не по
            # resolved: единая этапная ОКС-группа несёт дубли типов
            # [razdel, ngs, razdel, ngs] (Этап-1 + Этап-2) — resolved.get(type)
            # потерял бы Этап-1 (перезапись). Каждый слой -> отдельный item;
            # post-grouping F_5_3 сольёт их в один файл по group_key.
            for layer, layer_type in zip(grp['layers'], grp['layer_types']):
                if layer is None:
                    continue

                if stage_template_id is not None:
                    template_id = stage_template_id
                elif layer_type == 'razdel':
                    template_id = grp['template_razdel']
                elif layer_type == 'ngs':
                    template_id = grp['template_ngs']
                else:
                    continue

                template = ProductRegistry._select_coord_template(layer, template_id)
                if template is None:
                    continue

                items.append({
                    'layer': layer,
                    'template': template,
                    'extra_context': {
                        'product_id': 'coord_ozu',
                        'group_key': grp['group_key'],
                    },
                })

        log_info(
            f"Fsm_5_3_10 (_expand_coord_ozu): раскрыто {len(items)} per-layer items"
        )
        return items

    @staticmethod
    def _expand_coord_ps() -> List[Dict[str, Any]]:
        """
        Перечни координат ПС: per-layer items для непустых ПС-слоёв.

        Контракт template_id (debate-2 STAB-A): item получает РОВНО тот же
        template_id, который TemplateRegistry.get_templates_for_layer назначил бы
        слою в старом GUI (coord_cutting_oks_ps для ОКС-ПС; coord_cutting_lo/vo/
        rek_ad/seti_*/ne для остальных групп). Все они входят в
        _REGION_78_CUTTING_TEMPLATE_IDS -> для региона 78 весь продукт уходит в
        78-цепочку байт-в-байт. Маркеры {product_id: 'coord_ps', group_key}.

        title_override generic merged-ПС назначается post-grouping Фазы 5, не здесь.
        """
        items: List[Dict[str, Any]] = []

        groups, _patterns = ProductRegistry._resolve_groups('coord_ps')
        for grp in groups:
            layer = grp['resolved'].get('ps')
            if layer is None:
                continue

            template = ProductRegistry._select_coord_template(
                layer, grp['template_ps']
            )
            if template is None:
                continue

            items.append({
                'layer': layer,
                'template': template,
                'extra_context': {
                    'product_id': 'coord_ps',
                    'group_key': grp['group_key'],
                },
            })

        log_info(
            f"Fsm_5_3_10 (_expand_coord_ps): раскрыто {len(items)} ПС-items"
        )
        return items

    @staticmethod
    def _expand_coord_gpmt() -> List[Dict[str, Any]]:
        """
        Перечень координат ГПМТ: один item; выбор ШАБЛОНА (не слоя).

        Непустой L_1_14_2_ГПМТ_ВНЕС_ИЗМ -> COORD_GPMT_IZM (приоритет Изм,
        решение #5), иначе COORD_GPMT. Имена файлов без номера приложения
        (решение #12) — appendix в gpmt-путь не пробрасывается (Fsm_5_3_7).

        Если COORD_GPMT_IZM ещё не создан (параллельная Фаза 4) — деградация к
        COORD_GPMT с log_warning.
        """
        items: List[Dict[str, Any]] = []

        izm_layer = ProductRegistry._find_layer(constants.LAYER_GPMT_VNES_IZM)
        base_layer = ProductRegistry._find_layer(constants.LAYER_GPMT)

        template: Optional[DocumentTemplate]
        if izm_layer is not None:
            if COORD_GPMT_IZM is not None:
                template = COORD_GPMT_IZM
            else:
                template = COORD_GPMT
                log_warning(
                    "Fsm_5_3_10 (_expand_coord_gpmt): непустой слой Изм найден, но "
                    "COORD_GPMT_IZM отсутствует (Фаза 4 не выполнена) — "
                    "используется COORD_GPMT"
                )
        elif base_layer is not None:
            template = COORD_GPMT
        else:
            log_info(
                "Fsm_5_3_10 (_expand_coord_gpmt): слои ГПМТ не найдены/пусты — "
                "продукт не раскрыт"
            )
            return items

        items.append({
            'layer': None,
            'template': template,
            'extra_context': {
                'product_id': 'coord_gpmt',
                'group_key': 'gpmt',
            },
        })

        log_info(
            f"Fsm_5_3_10 (_expand_coord_gpmt): раскрыт ГПМТ-item "
            f"(шаблон '{template.template_id}')"
        )
        return items
