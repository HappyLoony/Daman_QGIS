# -*- coding: utf-8 -*-
"""
Msm_33_1_HLU_DataProcessor - Процессор данных для документа ХЛУ.

Отвечает за:
- Извлечение данных из слоёв ЗПР (7 типов)
- Группировку по муниципальным округам (Le_1_2_3_12_АТД_МО_poly)
- Подготовку контекста для всех 6 таблиц ХЛУ
- Расчёт промежуточных итогов и подытогов
- Форматирование данных (площади с запятой, 4 знака)

Типы ЗПР (7 штук):
- L_1_12_1_ЗПР_ОКС - Зона планируемого размещения ОКС
- L_1_12_2_ЗПР_ПО - ЗПР линейного объекта (на период строительства)
- L_1_12_3_ЗПР_ВО - ЗПР линейного объекта (на период эксплуатации)
- L_1_13_1_ЗПР_РЕК_АД - ЗПР реконструкции автодорог
- L_1_13_2_ЗПР_СЕТИ_ПО - ЗПР реконструкции сетей (период строительства)
- L_1_13_3_ЗПР_СЕТИ_ВО - ЗПР реконструкции сетей (период эксплуатации)
- L_1_13_4_ЗПР_НЭ - ЗПР реконструкции наземных элементов

Использование:
    from managers.submodules import HLU_DataProcessor

    processor = HLU_DataProcessor(project_manager, layer_manager)
    context = processor.prepare_full_context()
    # Затем передать context в WordExportManager.render()
"""

from itertools import groupby
from typing import Dict, Any, List, Optional, Tuple

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsSpatialIndex
)

from Daman_QGIS.utils import log_info, log_error, log_warning
from Daman_QGIS.constants import (
    LAYERS_ZPR_ALL,
    LAYER_ZPR_OKS, LAYER_ZPR_PO, LAYER_ZPR_VO,
    LAYER_ZPR_REK_AD, LAYER_ZPR_SETI_PO, LAYER_ZPR_SETI_VO, LAYER_ZPR_NE,
)


# Слои ЗПР (из constants.py)
ZPR_LAYERS = list(LAYERS_ZPR_ALL)

# Полные названия типов ЗПР
ZPR_FULL_NAMES = {
    LAYER_ZPR_OKS: "Зона планируемого размещения объектов капитального строительства",
    LAYER_ZPR_PO: "Зона планируемого размещения линейного объекта (на период строительства)",
    LAYER_ZPR_VO: "Зона планируемого размещения линейного объекта (на период эксплуатации)",
    LAYER_ZPR_REK_AD: "Зона планируемого размещения линейных объектов транспортной инфраструктуры, подлежащих реконструкции",
    LAYER_ZPR_SETI_PO: "Зона планируемого размещения линейных объектов (инженерных сетей), подлежащих реконструкции (период строительства)",
    LAYER_ZPR_SETI_VO: "Зона планируемого размещения линейных объектов (инженерных сетей), подлежащих реконструкции (период эксплуатации)",
    LAYER_ZPR_NE: "Зона планируемого размещения наземных элементов инженерных сетей, подлежащих реконструкции"
}

# Слой муниципальных округов
MO_LAYER_NAME = "Le_1_2_3_12_АТД_МО_poly"

# Константы слоёв Le_3_* (результат F_3_1)
LE4_LAYERS = [
    # Le_3_2_* - стандартные ЗПР (ОКС/ПО/ВО)
    "Le_3_2_1_1_Раздел_ЗПР_ОКС",
    "Le_3_2_1_2_НГС_ЗПР_ОКС",
    "Le_3_2_1_3_Без_меж_ЗПР_ОКС",
    "Le_3_2_1_4_ПС_ЗПР_ОКС",
    "Le_3_2_2_1_Раздел_ЗПР_ПО",
    "Le_3_2_2_2_НГС_ЗПР_ПО",
    "Le_3_2_2_3_Без_меж_ЗПР_ПО",
    "Le_3_2_2_4_ПС_ЗПР_ПО",
    "Le_3_2_3_1_Раздел_ЗПР_ВО",
    "Le_3_2_3_2_НГС_ЗПР_ВО",
    "Le_3_2_3_3_Без_меж_ЗПР_ВО",
    "Le_3_2_3_4_ПС_ЗПР_ВО",
    # Le_3_3_* - РЕК ЗПР (РЕК_АД/СЕТИ_ПО/СЕТИ_ВО/НЭ)
    "Le_3_3_1_1_Раздел_ЗПР_РЕК_АД",
    "Le_3_3_1_2_НГС_ЗПР_РЕК_АД",
    "Le_3_3_1_3_Без_меж_ЗПР_РЕК_АД",
    "Le_3_3_1_4_ПС_ЗПР_РЕК_АД",
    "Le_3_3_2_1_Раздел_ЗПР_СЕТИ_ПО",
    "Le_3_3_2_2_НГС_ЗПР_СЕТИ_ПО",
    "Le_3_3_2_3_Без_меж_ЗПР_СЕТИ_ПО",
    "Le_3_3_2_4_ПС_ЗПР_СЕТИ_ПО",
    "Le_3_3_3_1_Раздел_ЗПР_СЕТИ_ВО",
    "Le_3_3_3_2_НГС_ЗПР_СЕТИ_ВО",
    "Le_3_3_3_3_Без_меж_ЗПР_СЕТИ_ВО",
    "Le_3_3_3_4_ПС_ЗПР_СЕТИ_ВО",
    "Le_3_3_4_1_Раздел_ЗПР_НЭ",
    "Le_3_3_4_2_НГС_ЗПР_НЭ",
    "Le_3_3_4_3_Без_меж_ЗПР_НЭ",
    "Le_3_3_4_4_ПС_ЗПР_НЭ",
]

# Определение типа ЗПР по имени слоя Le_3_*
LE4_ZPR_TYPES = {
    "ОКС": "Зона планируемого размещения объектов капитального строительства",
    "ПО": "Зона планируемого размещения линейного объекта (на период строительства)",
    "ВО": "Зона планируемого размещения линейного объекта (на период эксплуатации)",
    "РЕК_АД": "Зона планируемого размещения линейных объектов транспортной инфраструктуры, подлежащих реконструкции",
    "СЕТИ_ПО": "Зона планируемого размещения линейных объектов (инженерных сетей), подлежащих реконструкции (период строительства)",
    "СЕТИ_ВО": "Зона планируемого размещения линейных объектов (инженерных сетей), подлежащих реконструкции (период эксплуатации)",
    "НЭ": "Зона планируемого размещения наземных элементов инженерных сетей, подлежащих реконструкции",
}

# Виды разрешенного использования лесов (16 видов)
VIDY_RAZRESHENNOGO_ISPOLZOVANIYA = [
    (1, "Заготовка древесины"),
    (2, "Заготовка живицы"),
    (3, "Заготовка и сбор недревесных лесных ресурсов"),
    (4, "Заготовка пищевых лесных ресурсов и сбор лекарственных растений"),
    (5, "Осуществление видов деятельности в сфере охотничьего хозяйства"),
    (6, "Ведение сельского хозяйства"),
    (7, "Осуществление научно-исследовательской деятельности, образовательной деятельности"),
    (8, "Осуществление рекреационной деятельности"),
    (9, "Создание лесных плантаций и их эксплуатация"),
    (10, "Выращивание лесных плодовых, ягодных, декоративных растений, лекарственных растений"),
    (11, "Выращивание посадочного материала лесных растений (саженцев, сеянцев)"),
    (12, "Выполнение работ по геологическому изучению недр, разработка месторождений полезных ископаемых"),
    (13, "Строительство и эксплуатация водохранилищ и иных искусственных водных объектов"),
    (14, "Строительство, реконструкция, эксплуатация линейных объектов"),
    (15, "Переработка древесины и иных лесных ресурсов"),
    (16, "Осуществление религиозной деятельности"),
]


class HLU_DataProcessor:
    """
    Процессор данных для документа ХЛУ (Характеристика лесных участков).

    Извлекает данные из слоёв ЗПР, группирует по МО и формирует
    контекст для Word-шаблонов.
    """

    def __init__(self, project_manager=None, layer_manager=None):
        """
        Инициализация процессора.

        Args:
            project_manager: M_1_ProjectManager (опционально)
            layer_manager: M_2_LayerManager (опционально)
        """
        self.project_manager = project_manager
        self.layer_manager = layer_manager
        self._qgs_project = QgsProject.instance()

        log_info("Msm_33_1: HLU_DataProcessor инициализирован")

    def get_layer(self, layer_name: str) -> Optional[QgsVectorLayer]:
        """
        Получить слой по имени.

        Args:
            layer_name: Имя слоя

        Returns:
            QgsVectorLayer или None
        """
        if self.layer_manager:
            return self.layer_manager.get_layer(layer_name)

        # Fallback - поиск в проекте напрямую
        layers = self._qgs_project.mapLayersByName(layer_name)
        return layers[0] if layers else None

    def get_zpr_layers(self) -> List[Tuple[str, QgsVectorLayer]]:
        """
        Получить все слои ЗПР с данными.

        Returns:
            List[Tuple[str, QgsVectorLayer]]: Список (имя_слоя, слой)
        """
        result = []
        for layer_name in ZPR_LAYERS:
            layer = self.get_layer(layer_name)
            if layer and layer.isValid() and layer.featureCount() > 0:
                result.append((layer_name, layer))
                log_info(f"Msm_33_1: Найден слой {layer_name} с {layer.featureCount()} объектами")
        return result

    def get_mo_layer(self) -> Optional[QgsVectorLayer]:
        """
        Получить слой муниципальных округов.

        Returns:
            QgsVectorLayer или None
        """
        layer = self.get_layer(MO_LAYER_NAME)
        if not layer or not layer.isValid():
            log_error(f"Msm_33_1: Слой МО не найден: {MO_LAYER_NAME}")
            return None
        return layer

    def extract_forest_features(self, zpr_layers: List[Tuple[str, QgsVectorLayer]]) -> List[Dict]:
        """
        Извлечь все лесные объекты из слоёв ЗПР.

        Args:
            zpr_layers: Список (имя_слоя, слой)

        Returns:
            List[Dict]: Список объектов с атрибутами
        """
        features = []

        for layer_name, layer in zpr_layers:
            for feature in layer.getFeatures():
                attrs = {
                    'source_layer': layer_name,
                    'zpr_type': ZPR_FULL_NAMES.get(layer_name, layer_name),
                    'geometry': feature.geometry(),
                    'feature_id': feature.id()
                }

                # Копируем все атрибуты
                for field in layer.fields():
                    field_name = field.name()
                    value = feature[field_name]
                    attrs[field_name] = value

                features.append(attrs)

        log_info(f"Msm_33_1: Извлечено {len(features)} лесных объектов")
        return features

    def group_by_municipality(
        self,
        forest_features: List[Dict],
        mo_layer: QgsVectorLayer,
        mo_name_field: str = "name"
    ) -> Dict[str, List[Dict]]:
        """
        Группировка лесных участков по муниципальным округам.

        Использует пространственное пересечение для определения принадлежности.

        Args:
            forest_features: Список объектов
            mo_layer: Слой муниципальных округов
            mo_name_field: Имя поля с названием МО

        Returns:
            Dict[str, List[Dict]]: {название_МО: [features]}
        """
        result = {}

        # Создаём пространственный индекс для МО
        mo_index = QgsSpatialIndex(mo_layer.getFeatures())

        # Кэш объектов МО
        mo_features = {f.id(): f for f in mo_layer.getFeatures()}

        for feature in forest_features:
            geom = feature.get('geometry')
            if not geom or geom.isEmpty():
                continue

            # Найти пересекающиеся МО
            candidate_ids = mo_index.intersects(geom.boundingBox())

            for mo_id in candidate_ids:
                mo_feature = mo_features.get(mo_id)
                if not mo_feature:
                    continue

                mo_geom = mo_feature.geometry()
                if geom.intersects(mo_geom):
                    mo_name = mo_feature[mo_name_field]
                    if mo_name not in result:
                        result[mo_name] = []
                    result[mo_name].append(feature)
                    break  # Объект принадлежит только одному МО

        log_info(f"Msm_33_1: Объекты сгруппированы по {len(result)} МО")
        return result

    def prepare_full_context(
        self,
        vid_ispolzovaniya: str = "",
        cel_predostavleniya: str = ""
    ) -> Dict[str, Any]:
        """
        Сформировать полный контекст для шаблона ХЛУ.

        Args:
            vid_ispolzovaniya: Вид использования лесов
            cel_predostavleniya: Цель предоставления участка

        Returns:
            Dict: Полный контекст для Word-шаблона
        """
        # Базовая структура контекста (обязательные ключи)
        base_context = {
            "prilozhenie_nomer": "",
            "nazvanie_dokumenta": "Характеристика образуемых лесных участков",
            "vid_ispolzovaniya": vid_ispolzovaniya,
            "cel_predostavleniya": cel_predostavleniya,
            "rayony": []
        }

        # Получить слои
        zpr_layers = self.get_zpr_layers()
        if not zpr_layers:
            log_warning("Msm_33_1: Нет слоёв ЗПР с данными")
            return {**base_context, "error": "Нет данных в слоях ЗПР"}

        mo_layer = self.get_mo_layer()
        if not mo_layer:
            return {**base_context, "error": "Слой МО не найден"}

        # Извлечь данные
        forest_features = self.extract_forest_features(zpr_layers)
        if not forest_features:
            return {**base_context, "error": "Нет лесных объектов"}

        # Группировка по МО
        grouped = self.group_by_municipality(forest_features, mo_layer)

        # Формирование контекста для каждого района
        for mo_name, features in sorted(grouped.items()):
            rayon_context = self._prepare_rayon_context(mo_name, features)
            base_context["rayony"].append(rayon_context)

        return base_context

    def _prepare_rayon_context(self, mo_name: str, features: List[Dict]) -> Dict[str, Any]:
        """
        Подготовка контекста для одного района/МО.

        Args:
            mo_name: Название муниципального округа
            features: Объекты в этом МО

        Returns:
            Dict: Контекст для одного раздела документа
        """
        return {
            "nazvanie": mo_name,
            "oblast": self._get_oblast_from_features(features),
            "lesnichestvo_name": self._get_lesnichestvo_from_features(features),

            # Таблицы
            "table1_groups": self._prepare_table1(features),
            "table2_vidy": self._prepare_table2(features),
            "table3": self._prepare_table3(features),
            "table4_rows": self._prepare_table4(features),
            "table5_rows": self._prepare_table5(features),
            "table6_rows": self._prepare_table6(features),

            # Итоги для таблицы 6
            "table6_itogo_ploshad": self._format_area(
                sum(float(f.get('Ploshad', 0) or 0) for f in features)
            ),
            "table6_ed_izm": "-",
            "table6_itogo_obem": "-",

            # ОЗУ
            "ozu_est": self._check_ozu(features),
            "ozu_types": self._prepare_ozu(features) if self._check_ozu(features) else [],
            "ozu_istochnik": "государственного лесного реестра"
        }

    def _get_oblast_from_features(self, features: List[Dict]) -> str:
        """Получить область из атрибутов объектов."""
        for f in features:
            oblast = f.get('Oblast') or f.get('Область') or f.get('Region')
            if oblast:
                return str(oblast)
        return "Область не определена"

    def _get_lesnichestvo_from_features(self, features: List[Dict]) -> str:
        """Получить лесничество из атрибутов объектов."""
        for f in features:
            lesn = f.get('Lesnichestvo') or f.get('Лесничество')
            if lesn:
                return str(lesn)
        return "Лесничество не определено"

    def _prepare_table1(self, features: List[Dict]) -> List[Dict]:
        """
        Подготовка данных для Таблицы 1 (распределение по целевому назначению).

        Returns:
            List[Dict]: Группы с заголовками и строками
        """
        # Группировка по целевому назначению
        key_func = lambda f: f.get('Celevoe_naznachenie') or f.get('Целевое_назначение', 'Не определено')
        sorted_features = sorted(features, key=key_func)

        groups = []
        for celevoe, group_features in groupby(sorted_features, key=key_func):
            group_list = list(group_features)

            rows = []
            for i, f in enumerate(group_list):
                rows.append({
                    "mestopolozhenie": self._get_oblast_from_features([f]) + ", " + str(f.get('Rayon', '')) if i == 0 else "",
                    "lesnichestvo": f.get('Lesnichestvo', '') if i == 0 else "",
                    "uch_lesnichestvo": f.get('Uch_lesnichestvo', '') if i == 0 else "",
                    "kvartal": str(f.get('Kvartal', '')),
                    "vydel": str(f.get('Vydel', ''))
                })

            groups.append({
                "header": celevoe,
                "subheader": None,
                "rows": rows
            })

        return groups

    def _prepare_table2(self, features: List[Dict]) -> List[Dict]:
        """
        Подготовка данных для Таблицы 2 (виды разрешенного использования).

        Returns:
            List[Dict]: Виды использования с участковыми лесничествами
        """
        # Стандартные виды использования
        vidy = [
            {"number": "6", "name": "Ведение сельского хозяйства, строительство..."},
            {"number": "13", "name": "Строительство, реконструкция, эксплуатация линейных объектов"}
        ]

        for vid in vidy:
            # Группировка по участковым лесничествам
            uch_lesn_kvartaly = {}
            for f in features:
                uch = f.get('Uch_lesnichestvo', '')
                kvartal = str(f.get('Kvartal', ''))
                if uch not in uch_lesn_kvartaly:
                    uch_lesn_kvartaly[uch] = set()
                if kvartal:
                    uch_lesn_kvartaly[uch].add(kvartal)

            vid["rows"] = [
                {"uch_lesnichestvo": uch, "kvartaly": ", ".join(sorted(kvs, key=int))}
                for uch, kvs in sorted(uch_lesn_kvartaly.items())
                if kvs
            ]

        return vidy

    def _prepare_table3(self, features: List[Dict]) -> Dict[str, str]:
        """
        Подготовка данных для Таблицы 3 (распределение земель).

        Returns:
            Dict: Площади по категориям
        """
        total_area = sum(float(f.get('Ploshad', 0) or 0) for f in features)

        # Базовое распределение (упрощённое)
        return {
            "obshaya_ploshad": self._format_area(total_area),
            "zanyatye_nasazhdeniyami": self._format_area(total_area * 0.8),  # ~80%
            "pokrytye_kulturami": "-",
            "pitomniki": "-",
            "ne_zanyatye": self._format_area(total_area * 0.2),  # ~20%
            "lesnye_itogo": self._format_area(total_area),
            "dorogi": "-",
            "proseki": "-",
            "bolota": "-",
            "drugie": "-",
            "nelesnye_itogo": "-"
        }

    def _prepare_table4(self, features: List[Dict]) -> List[Dict]:
        """
        Подготовка данных для Таблицы 4 (характеристика лесного участка).

        Группировка: Целевое назначение -> Лесничество -> Уч. лесничество

        Returns:
            List[Dict]: Строки таблицы с {% vm %} объединением
        """
        rows = []

        # Сортировка для группировки
        def sort_key(f):
            return (
                f.get('Celevoe_naznachenie', ''),
                f.get('Lesnichestvo', ''),
                f.get('Uch_lesnichestvo', ''),
                int(f.get('Kvartal', 0) or 0),
                int(f.get('Vydel', 0) or 0)
            )

        sorted_features = sorted(features, key=sort_key)

        # Группировка по целевому назначению
        for celevoe, group_celevoe in groupby(sorted_features, key=lambda x: x.get('Celevoe_naznachenie', '')):
            group_celevoe_list = list(group_celevoe)
            first_celevoe = True

            # Группировка по лесничеству
            for lesn, group_lesn in groupby(group_celevoe_list, key=lambda x: x.get('Lesnichestvo', '')):
                group_lesn_list = list(group_lesn)
                first_lesn = True

                # Группировка по участковому лесничеству
                for uch_lesn, group_uch in groupby(group_lesn_list, key=lambda x: x.get('Uch_lesnichestvo', '')):
                    group_uch_list = list(group_uch)
                    first_uch = True
                    subtotal_area = 0.0
                    subtotal_zapas = 0

                    for f in group_uch_list:
                        area = float(f.get('Ploshad', 0) or 0)
                        zapas = int(f.get('Zapas', 0) or 0)
                        subtotal_area += area
                        subtotal_zapas += zapas

                        row = {
                            # Поля для {% vm %} - пустые для продолжения объединения
                            "nomer": f.get('Nomer_na_chertezhe', '') if first_uch else "",
                            "celevoe": celevoe if first_celevoe else "",
                            "lesnichestvo": lesn if first_lesn else "",
                            "uch_lesnichestvo": uch_lesn if first_uch else "",
                            # Обычные поля
                            "kvartal": str(f.get('Kvartal', '')),
                            "vydel": str(f.get('Vydel', '')),
                            "sostav": f.get('Sostav', '-'),
                            "ploshad_zapas": self._format_area_zapas(area, zapas),
                            "molodnyaki": self._format_age_group(f, 'Molodnyaki'),
                            "srednevozrastnye": self._format_age_group(f, 'Srednevozrastnye'),
                            "prispevayushie": self._format_age_group(f, 'Prispevayushie'),
                            "spelye": self._format_age_group(f, 'Spelye'),
                            "is_data_row": True
                        }
                        rows.append(row)

                        first_celevoe = False
                        first_lesn = False
                        first_uch = False

                    # Итого по участковому лесничеству
                    rows.append({
                        "nomer": "",
                        "celevoe": f"Всего по {celevoe.lower() if celevoe else ''} лесам {uch_lesn} уч. лесничества:",
                        "lesnichestvo": "",
                        "uch_lesnichestvo": "",
                        "kvartal": "",
                        "vydel": "",
                        "sostav": "",
                        "ploshad_zapas": self._format_area_zapas(subtotal_area, subtotal_zapas),
                        "molodnyaki": "-",
                        "srednevozrastnye": "-",
                        "prispevayushie": "-",
                        "spelye": "-",
                        "is_subtotal": True
                    })

        return rows

    def _prepare_table5(self, features: List[Dict]) -> List[Dict]:
        """
        Подготовка данных для Таблицы 5 (средние таксационные показатели).

        Returns:
            List[Dict]: Строки таблицы
        """
        rows = []
        for f in features:
            rows.append({
                "celevoe": f.get('Celevoe_naznachenie', ''),
                "lesn_uch": f"{f.get('Lesnichestvo', '')} / {f.get('Uch_lesnichestvo', '')}",
                "kvartal_vydel": f"{f.get('Kvartal', '')} / {f.get('Vydel', '')}",
                "hozyajstvo": f.get('Hozyajstvo', '-'),
                "sostav": f.get('Sostav', '-'),
                "vozrast": f.get('Vozrast', '-'),
                "bonitet": f.get('Bonitet', '-'),
                "polnota": f.get('Polnota', '-'),
                "zapas_molodnyaki": f.get('Zapas_molodnyaki', '-'),
                "zapas_srednevozr": f.get('Zapas_srednevozr', '-'),
                "zapas_prispev": f.get('Zapas_prispev', '-'),
                "zapas_spelye": f.get('Zapas_spelye', '-')
            })
        return rows

    def _prepare_table6(self, features: List[Dict]) -> List[Dict]:
        """
        Подготовка данных для Таблицы 6 (виды и объемы использования).

        Returns:
            List[Dict]: Строки таблицы
        """
        # Группировка по целевому назначению
        key_func = lambda f: f.get('Celevoe_naznachenie', '')
        sorted_features = sorted(features, key=key_func)

        rows = []
        for celevoe, group_features in groupby(sorted_features, key=key_func):
            group_list = list(group_features)
            total_area = sum(float(f.get('Ploshad', 0) or 0) for f in group_list)

            rows.append({
                "celevoe": celevoe,
                "hozyajstvo": "-",
                "ploshad": self._format_area(total_area),
                "ed_izm": "-",
                "obem": "-"
            })

        return rows

    def _check_ozu(self, features: List[Dict]) -> bool:
        """Проверить наличие ОЗУ в объектах."""
        for f in features:
            ozu = f.get('OZU') or f.get('ОЗУ')
            if ozu:
                return True
        return False

    def _prepare_ozu(self, features: List[Dict]) -> List[Dict]:
        """
        Подготовка данных об ОЗУ.

        Returns:
            List[Dict]: Типы ОЗУ с элементами
        """
        ozu_groups = {}

        for f in features:
            ozu_type = f.get('OZU') or f.get('ОЗУ')
            if not ozu_type:
                continue

            if ozu_type not in ozu_groups:
                ozu_groups[ozu_type] = []

            ozu_groups[ozu_type].append({
                "kvartal": str(f.get('Kvartal', '')),
                "vydely": str(f.get('Vydel', '')),
                "uch_lesnichestvo": f.get('Uch_lesnichestvo', ''),
                "lesnichestvo": f.get('Lesnichestvo', '')
            })

        return [
            {"name": ozu_type, "items": items}
            for ozu_type, items in sorted(ozu_groups.items())
        ]

    def _format_age_group(self, feature: Dict, field_prefix: str) -> str:
        """
        Форматирование группы возраста.

        Args:
            feature: Объект
            field_prefix: Префикс поля (Molodnyaki, Srednevozrastnye, etc.)

        Returns:
            str: "площадь / запас" или "-"
        """
        area = feature.get(f'{field_prefix}_area') or feature.get(f'{field_prefix}_Ploshad')
        zapas = feature.get(f'{field_prefix}_zapas') or feature.get(f'{field_prefix}_Zapas')

        if area and float(area) > 0:
            return self._format_area_zapas(float(area), int(zapas or 0))
        return "-"

    @staticmethod
    def _format_area(value: float, decimals: int = 4) -> str:
        """
        Форматирование площади с запятой.

        Args:
            value: Значение
            decimals: Знаков после запятой

        Returns:
            str: Форматированное значение (0,0231)
        """
        if value is None or value == 0:
            return "-"
        return f"{value:.{decimals}f}".replace(".", ",")

    @staticmethod
    def _format_area_zapas(area: float, zapas: int) -> str:
        """
        Форматирование площади/запаса.

        Args:
            area: Площадь
            zapas: Запас

        Returns:
            str: "0,0231 / 15" или "-"
        """
        if area is None or area == 0:
            return "-"
        area_str = f"{area:.4f}".replace(".", ",")
        return f"{area_str} / {zapas or 0}"

    # ========================================================================
    # МЕТОДЫ ДЛЯ Le_3_* СЛОЁВ (F_3_2)
    # ========================================================================

    @staticmethod
    def _determine_le4_zpr_type(layer_name: str) -> str:
        """Определение типа ЗПР по имени слоя Le_3_*

        Args:
            layer_name: Имя слоя Le_3_*

        Returns:
            str: Тип ЗПР (ОКС/ПО/ВО/РЕК_АД/СЕТИ_ПО/СЕТИ_ВО/НЭ)
        """
        # Le_3_3_* - РЕК (проверяем первым, т.к. суффиксы _ПО/_ВО пересекаются)
        if "Le_3_3_" in layer_name:
            if "_РЕК_АД" in layer_name:
                return "РЕК_АД"
            if "_СЕТИ_ПО" in layer_name:
                return "СЕТИ_ПО"
            if "_СЕТИ_ВО" in layer_name:
                return "СЕТИ_ВО"
            if "_НЭ" in layer_name:
                return "НЭ"
        # Le_3_2_* - стандартные ЗПР
        if layer_name.endswith("_ОКС"):
            return "ОКС"
        if layer_name.endswith("_ПО"):
            return "ПО"
        if layer_name.endswith("_ВО"):
            return "ВО"
        return "ОКС"

    def get_le4_layers(self) -> List[Tuple[str, str, QgsVectorLayer]]:
        """
        Получить все слои Le_3_* с данными.

        Returns:
            List[Tuple[str, str, QgsVectorLayer]]: Список (имя_слоя, тип_зпр, слой)
        """
        result = []
        for layer_name in LE4_LAYERS:
            layer = self.get_layer(layer_name)
            if layer and layer.isValid() and layer.featureCount() > 0:
                # Определяем тип ЗПР по имени слоя Le_3_*
                zpr_type = self._determine_le4_zpr_type(layer_name)

                result.append((layer_name, zpr_type, layer))
                log_info(f"Msm_33_1: Найден слой {layer_name} с {layer.featureCount()} объектами")

        return result

    def extract_le4_features(
        self,
        le4_layers: List[Tuple[str, str, QgsVectorLayer]]
    ) -> List[Dict]:
        """
        Извлечь все объекты из слоёв Le_3_*.

        Args:
            le4_layers: Список (имя_слоя, тип_зпр, слой)

        Returns:
            List[Dict]: Список объектов с атрибутами
        """
        features = []

        for layer_name, zpr_type, layer in le4_layers:
            for feature in layer.getFeatures():
                attrs = {
                    'source_layer': layer_name,
                    'zpr_type': zpr_type,
                    'zpr_full_name': LE4_ZPR_TYPES.get(zpr_type, zpr_type),
                    'geometry': feature.geometry(),
                    'feature_id': feature.id()
                }

                # Копируем все атрибуты
                for field in layer.fields():
                    field_name = field.name()
                    value = feature[field_name]
                    attrs[field_name] = value

                features.append(attrs)

        log_info(f"Msm_33_1: Извлечено {len(features)} объектов из Le_3_* слоёв")
        return features

    def group_by_mo_le4(
        self,
        forest_features: List[Dict],
        mo_layer: QgsVectorLayer,
        mo_name_field: str = "name"
    ) -> Dict[str, List[Dict]]:
        """
        Группировка лесных участков по муниципальным округам.

        Args:
            forest_features: Список объектов
            mo_layer: Слой муниципальных округов
            mo_name_field: Имя поля с названием МО

        Returns:
            Dict[str, List[Dict]]: {название_МО: [features]}
        """
        result = {}

        # Создаём пространственный индекс для МО
        mo_index = QgsSpatialIndex(mo_layer.getFeatures())

        # Кэш объектов МО
        mo_features = {f.id(): f for f in mo_layer.getFeatures()}

        for feature in forest_features:
            geom = feature.get('geometry')
            if not geom or geom.isEmpty():
                continue

            # Найти пересекающиеся МО
            candidate_ids = mo_index.intersects(geom.boundingBox())

            for mo_id in candidate_ids:
                mo_feature = mo_features.get(mo_id)
                if not mo_feature:
                    continue

                mo_geom = mo_feature.geometry()
                if geom.intersects(mo_geom):
                    mo_name = mo_feature[mo_name_field]
                    if mo_name not in result:
                        result[mo_name] = []
                    result[mo_name].append(feature)
                    break  # Объект принадлежит только одному МО

        log_info(f"Msm_33_1: Объекты сгруппированы по {len(result)} МО")
        return result

    def prepare_full_context_le4(
        self,
        vid_ispolzovaniya: str = "",
        cel_predostavleniya: str = ""
    ) -> Dict[str, Any]:
        """
        Сформировать полный контекст для шаблона ХЛУ на основе Le_3_*.

        Args:
            vid_ispolzovaniya: Вид использования лесов
            cel_predostavleniya: Цель предоставления участка

        Returns:
            Dict: Полный контекст для Word-шаблона
        """
        # Базовая структура контекста
        base_context = {
            "prilozhenie_nomer": "",
            "nazvanie_dokumenta": "Характеристика образуемых лесных участков",
            "vid_ispolzovaniya": vid_ispolzovaniya,
            "cel_predostavleniya": cel_predostavleniya,
            "rayony": []
        }

        # Получить слои
        le4_layers = self.get_le4_layers()
        if not le4_layers:
            log_warning("Msm_33_1: Нет слоёв Le_3_* с данными")
            return {**base_context, "error": "Нет данных в слоях Le_3_*"}

        mo_layer = self.get_mo_layer()
        if not mo_layer:
            return {**base_context, "error": "Слой МО не найден"}

        # Извлечь данные
        forest_features = self.extract_le4_features(le4_layers)
        if not forest_features:
            return {**base_context, "error": "Нет лесных объектов"}

        # Группировка по МО
        grouped = self.group_by_mo_le4(forest_features, mo_layer)

        # Формирование контекста для каждого района
        for mo_name, features in sorted(grouped.items()):
            rayon_context = self._prepare_rayon_context_le4(mo_name, features)
            base_context["rayony"].append(rayon_context)

        return base_context

    def _prepare_rayon_context_le4(
        self,
        mo_name: str,
        features: List[Dict]
    ) -> Dict[str, Any]:
        """
        Подготовка контекста для одного района/МО (Le_3_*).

        Args:
            mo_name: Название муниципального округа
            features: Объекты в этом МО

        Returns:
            Dict: Контекст для одного раздела документа
        """
        # Получить область из первого объекта
        oblast = self._get_oblast_from_le4(features)

        # Основное лесничество
        lesnichestvo = self._get_lesnichestvo_from_le4(features)

        return {
            "nazvanie": mo_name,
            "oblast": oblast,
            "lesnichestvo_name": lesnichestvo,

            # Таблицы
            "table1": self._prepare_table1_le4(features),
            "table2": self._prepare_table2_le4(features),
            "table3": self._prepare_table3_le4(features),
            "table4": self._prepare_table4_le4(features),
            "table5": self._prepare_table5_le4(features),
            "table6": self._prepare_table6_le4(features),

            # ОЗУ
            "ozu": self._prepare_ozu_le4(features),
        }

    def _get_oblast_from_le4(self, features: List[Dict]) -> str:
        """Получить область из атрибутов Le_3_*."""
        # В Le_3_* нет поля "Область", используем заглушку
        return "Область"

    def _get_lesnichestvo_from_le4(self, features: List[Dict]) -> str:
        """Получить лесничество из атрибутов Le_3_*."""
        for f in features:
            lesn = f.get('Лесничество')
            if lesn and str(lesn) != '-':
                return str(lesn)
        return "Лесничество не определено"

    def _prepare_table1_le4(self, features: List[Dict]) -> Dict[str, Any]:
        """
        Подготовка данных для Таблицы 1 (распределение по целевому назначению).

        Структура:
        - Защитные леса -> подкатегории
        - Эксплуатационные леса

        Returns:
            Dict: {zashitnye: [...], ekspluatacionnye: [...]}
        """
        zashitnye = []
        ekspluatacionnye = []

        # Группировка по целевому назначению
        celevoe_groups: Dict[str, List[Dict]] = {}
        for f in features:
            celevoe = f.get('Целевое_назначение', 'Не определено')
            if celevoe is None or str(celevoe) == '-':
                celevoe = 'Не определено'
            celevoe = str(celevoe)
            if celevoe not in celevoe_groups:
                celevoe_groups[celevoe] = []
            celevoe_groups[celevoe].append(f)

        # Обработка каждой категории
        for celevoe, group_features in sorted(celevoe_groups.items()):
            # Группировка выделов по кварталам
            kvartaly_vydely: Dict[str, Dict[str, set]] = {}
            for f in group_features:
                kvartal = str(f.get('Номер_квартала', ''))
                vydel = str(f.get('Номер_выдела', ''))
                uch_lesn = f.get('Уч_лесничество', '')
                lesn = f.get('Лесничество', '')
                key = f"{lesn}|{uch_lesn}"

                if key not in kvartaly_vydely:
                    kvartaly_vydely[key] = {}
                if kvartal not in kvartaly_vydely[key]:
                    kvartaly_vydely[key][kvartal] = set()
                if vydel:
                    kvartaly_vydely[key][kvartal].add(vydel)

            # Формирование строк
            rows = []
            for key, kvartaly in sorted(kvartaly_vydely.items()):
                parts = key.split('|')
                lesn = parts[0] if len(parts) > 0 else ''
                uch_lesn = parts[1] if len(parts) > 1 else ''

                for kvartal, vydely in sorted(kvartaly.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
                    vydely_str = ', '.join(sorted(vydely, key=lambda x: int(x) if x.isdigit() else 0))
                    rows.append({
                        "mestopolozhenie": "",  # Заполняется в шаблоне
                        "lesnichestvo": lesn,
                        "uch_lesnichestvo": uch_lesn,
                        "kvartal": kvartal,
                        "vydely": vydely_str
                    })

            kategoria_data = {
                "kategoriya": celevoe,
                "rows": rows
            }

            # Распределение по типу леса
            celevoe_lower = celevoe.lower()
            if 'защитн' in celevoe_lower or 'водоохран' in celevoe_lower or 'ценн' in celevoe_lower:
                zashitnye.append(kategoria_data)
            else:
                ekspluatacionnye.append(kategoria_data)

        return {
            "zashitnye": zashitnye,
            "ekspluatacionnye": ekspluatacionnye
        }

    def _prepare_table2_le4(self, features: List[Dict]) -> List[Dict]:
        """
        Подготовка данных для Таблицы 2 (виды разрешенного использования).

        Returns:
            List[Dict]: 16 видов с участковыми лесничествами и кварталами
        """
        result = []

        for nomer, vid_name in VIDY_RAZRESHENNOGO_ISPOLZOVANIYA:
            # Группировка по участковым лесничествам
            uch_lesn_kvartaly: Dict[str, set] = {}

            for f in features:
                uch = f.get('Уч_лесничество', '')
                if not uch or str(uch) == '-':
                    continue
                kvartal = str(f.get('Номер_квартала', ''))
                if uch not in uch_lesn_kvartaly:
                    uch_lesn_kvartaly[uch] = set()
                if kvartal and kvartal.isdigit():
                    uch_lesn_kvartaly[uch].add(kvartal)

            rows = []
            for uch, kvartaly in sorted(uch_lesn_kvartaly.items()):
                if kvartaly:
                    rows.append({
                        "uch_lesnichestvo": uch,
                        "kvartaly": ', '.join(sorted(kvartaly, key=int))
                    })

            result.append({
                "nomer": str(nomer),
                "vid": vid_name,
                "rows": rows
            })

        return result

    def _prepare_table3_le4(self, features: List[Dict]) -> Dict[str, str]:
        """
        Подготовка данных для Таблицы 3 (распределение земель).

        Returns:
            Dict: Площади по категориям
        """
        # Площадь_ОЗУ в Le_3_* хранится в м2
        total_area_m2 = sum(float(f.get('Площадь_ОЗУ', 0) or 0) for f in features)
        total_area_ga = total_area_m2 / 10000

        # Группировка по распределению земель
        raspredelenie_groups: Dict[str, float] = {}
        for f in features:
            raspr = f.get('Распределение_земель', '-')
            if raspr is None or str(raspr) == '-':
                raspr = 'Прочие'
            area = float(f.get('Площадь_ОЗУ', 0) or 0) / 10000
            if raspr not in raspredelenie_groups:
                raspredelenie_groups[raspr] = 0
            raspredelenie_groups[raspr] += area

        # Категории лесных земель
        lesnye_zanyatye = 0.0
        lesnye_ne_zanyatye = 0.0

        # Категории нелесных земель
        nelesnye_dorogi = 0.0
        nelesnye_proseki = 0.0
        nelesnye_bolota = 0.0
        nelesnye_drugie = 0.0

        for raspr, area in raspredelenie_groups.items():
            raspr_lower = str(raspr).lower()
            if 'дорог' in raspr_lower:
                nelesnye_dorogi += area
            elif 'просек' in raspr_lower or 'трасс' in raspr_lower:
                nelesnye_proseki += area
            elif 'болот' in raspr_lower:
                nelesnye_bolota += area
            elif 'вырубк' in raspr_lower or 'прогалин' in raspr_lower or 'погиб' in raspr_lower:
                lesnye_ne_zanyatye += area
            elif any(x in raspr_lower for x in ['лесн', 'насажден', 'культур', 'молодняк']):
                lesnye_zanyatye += area
            else:
                nelesnye_drugie += area

        lesnye_itogo = lesnye_zanyatye + lesnye_ne_zanyatye
        nelesnye_itogo = nelesnye_dorogi + nelesnye_proseki + nelesnye_bolota + nelesnye_drugie

        return {
            "obshaya_ploshad": self._format_area(total_area_ga),
            "lesnye_zanyatye": self._format_area(lesnye_zanyatye),
            "lesnye_kultury": "-",
            "lesnye_pitomniki": "-",
            "lesnye_ne_zanyatye": self._format_area(lesnye_ne_zanyatye),
            "lesnye_itogo": self._format_area(lesnye_itogo),
            "nelesnye_dorogi": self._format_area(nelesnye_dorogi),
            "nelesnye_proseki": self._format_area(nelesnye_proseki),
            "nelesnye_bolota": self._format_area(nelesnye_bolota),
            "nelesnye_drugie": self._format_area(nelesnye_drugie),
            "nelesnye_itogo": self._format_area(nelesnye_itogo),
        }

    def _prepare_table4_le4(self, features: List[Dict]) -> Dict[str, Any]:
        """
        Подготовка данных для Таблицы 4 (характеристика лесного участка).

        Группировка: Целевое назначение -> Лесничество -> Уч. лесничество

        Returns:
            Dict: {groups: [...], itogo: {...}}
        """
        groups = []
        total_area = 0.0
        total_zapas = 0
        total_by_age: Dict[str, Tuple[float, int]] = {
            'molodnyaki': (0.0, 0),
            'srednevozrastnye': (0.0, 0),
            'prispevayushie': (0.0, 0),
            'spelye': (0.0, 0),
        }

        # Сортировка для группировки
        def sort_key(f):
            return (
                f.get('Целевое_назначение', ''),
                f.get('Лесничество', ''),
                f.get('Уч_лесничество', ''),
                int(f.get('Номер_квартала', 0) or 0),
                int(f.get('Номер_выдела', 0) or 0)
            )

        sorted_features = sorted(features, key=sort_key)

        # Группировка по целевому назначению
        from itertools import groupby as iter_groupby
        for celevoe, group_celevoe in iter_groupby(
            sorted_features,
            key=lambda x: x.get('Целевое_назначение', '')
        ):
            group_celevoe_list = list(group_celevoe)

            celevoe_data = {
                "celevoe": celevoe or "Не определено",
                "lesnichestvo_groups": []
            }

            # Группировка по лесничеству
            for lesn, group_lesn in iter_groupby(
                group_celevoe_list,
                key=lambda x: x.get('Лесничество', '')
            ):
                group_lesn_list = list(group_lesn)

                lesn_data = {
                    "lesnichestvo": lesn or "-",
                    "uch_groups": []
                }

                # Группировка по участковому лесничеству
                for uch_lesn, group_uch in iter_groupby(
                    group_lesn_list,
                    key=lambda x: x.get('Уч_лесничество', '')
                ):
                    group_uch_list = list(group_uch)

                    subtotal_area = 0.0
                    subtotal_zapas = 0
                    subtotal_by_age: Dict[str, Tuple[float, int]] = {
                        'molodnyaki': (0.0, 0),
                        'srednevozrastnye': (0.0, 0),
                        'prispevayushie': (0.0, 0),
                        'spelye': (0.0, 0),
                    }

                    rows = []
                    for f in group_uch_list:
                        # Площадь в гектарах
                        area_m2 = float(f.get('Площадь_ОЗУ', 0) or 0)
                        area_ga = area_m2 / 10000

                        # Запас
                        zapas_na_ga = float(f.get('Запас_на_1_га', 0) or 0)
                        zapas = int(area_ga * zapas_na_ga)

                        subtotal_area += area_ga
                        subtotal_zapas += zapas
                        total_area += area_ga
                        total_zapas += zapas

                        # Распределение по возрастным группам
                        gruppa = f.get('Группа_возраста', '')
                        age_key = self._get_age_group_key(gruppa)
                        if age_key:
                            a, z = subtotal_by_age[age_key]
                            subtotal_by_age[age_key] = (a + area_ga, z + zapas)
                            ta, tz = total_by_age[age_key]
                            total_by_age[age_key] = (ta + area_ga, tz + zapas)

                        rows.append({
                            "nomer": str(f.get('ID', '')),
                            "kvartal": str(f.get('Номер_квартала', '')),
                            "vydel": str(f.get('Номер_выдела', '')),
                            "sostav": f.get('Состав', '-') or '-',
                            "ploshad_zapas": self._format_area_zapas(area_ga, zapas),
                            "molodnyaki": self._format_age_cell(f, 'Молодняки'),
                            "srednevozrastnye": self._format_age_cell(f, 'Средневозрастные'),
                            "prispevayushie": self._format_age_cell(f, 'Приспевающие'),
                            "spelye": self._format_age_cell(f, 'Спелые'),
                        })

                    uch_data = {
                        "uch_lesnichestvo": uch_lesn or "-",
                        "rows": rows,
                        "subtotal": {
                            "ploshad_zapas": self._format_area_zapas(subtotal_area, subtotal_zapas),
                            "molodnyaki": self._format_age_subtotal(subtotal_by_age, 'molodnyaki'),
                            "srednevozrastnye": self._format_age_subtotal(subtotal_by_age, 'srednevozrastnye'),
                            "prispevayushie": self._format_age_subtotal(subtotal_by_age, 'prispevayushie'),
                            "spelye": self._format_age_subtotal(subtotal_by_age, 'spelye'),
                        }
                    }
                    lesn_data["uch_groups"].append(uch_data)

                celevoe_data["lesnichestvo_groups"].append(lesn_data)

            groups.append(celevoe_data)

        return {
            "groups": groups,
            "itogo": {
                "ploshad_zapas": self._format_area_zapas(total_area, total_zapas),
                "molodnyaki": self._format_age_subtotal(total_by_age, 'molodnyaki'),
                "srednevozrastnye": self._format_age_subtotal(total_by_age, 'srednevozrastnye'),
                "prispevayushie": self._format_age_subtotal(total_by_age, 'prispevayushie'),
                "spelye": self._format_age_subtotal(total_by_age, 'spelye'),
            }
        }

    def _get_age_group_key(self, gruppa: Optional[str]) -> Optional[str]:
        """Преобразование группы возраста в ключ."""
        if not gruppa:
            return None
        gruppa_lower = str(gruppa).lower()
        if 'молодн' in gruppa_lower:
            return 'molodnyaki'
        elif 'средневозр' in gruppa_lower:
            return 'srednevozrastnye'
        elif 'приспев' in gruppa_lower:
            return 'prispevayushie'
        elif 'спел' in gruppa_lower or 'перестой' in gruppa_lower:
            return 'spelye'
        return None

    def _format_age_cell(self, feature: Dict, gruppa_name: str) -> str:
        """Форматирование ячейки возрастной группы для строки."""
        gruppa = feature.get('Группа_возраста', '')
        if gruppa and gruppa_name.lower() in str(gruppa).lower():
            area_m2 = float(feature.get('Площадь_ОЗУ', 0) or 0)
            area_ga = area_m2 / 10000
            zapas_na_ga = float(feature.get('Запас_на_1_га', 0) or 0)
            zapas = int(area_ga * zapas_na_ga)
            return self._format_area_zapas(area_ga, zapas)
        return "-"

    def _format_age_subtotal(
        self,
        age_totals: Dict[str, Tuple[float, int]],
        key: str
    ) -> str:
        """Форматирование подытога по возрастной группе."""
        area, zapas = age_totals.get(key, (0.0, 0))
        if area > 0:
            return self._format_area_zapas(area, zapas)
        return "-"

    def _prepare_table5_le4(self, features: List[Dict]) -> List[Dict]:
        """
        Подготовка данных для Таблицы 5 (средние таксационные показатели).

        Returns:
            List[Dict]: Строки таблицы
        """
        rows = []
        for f in features:
            area_m2 = float(f.get('Площадь_ОЗУ', 0) or 0)
            if area_m2 <= 0:
                continue

            rows.append({
                "celevoe": f.get('Целевое_назначение', '-') or '-',
                "lesn_uch": f"{f.get('Лесничество', '-')} / {f.get('Уч_лесничество', '-')}",
                "kvartal_vydel": f"{f.get('Номер_квартала', '-')} / {f.get('Номер_выдела', '-')}",
                "hozyajstvo": f.get('Хозяйство', '-') or '-',
                "sostav": f.get('Состав', '-') or '-',
                "vozrast": f.get('Возраст', '-') or '-',
                "bonitet": f.get('Бонитет', '-') or '-',
                "polnota": f.get('Полнота', '-') or '-',
                "zapas_molodnyaki": self._get_zapas_by_age(f, 'Молодняки'),
                "zapas_srednevozr": self._get_zapas_by_age(f, 'Средневозрастные'),
                "zapas_prispev": self._get_zapas_by_age(f, 'Приспевающие'),
                "zapas_spelye": self._get_zapas_by_age(f, 'Спелые'),
            })

        return rows

    def _get_zapas_by_age(self, feature: Dict, gruppa_name: str) -> str:
        """Получить запас для конкретной группы возраста."""
        gruppa = feature.get('Группа_возраста', '')
        if gruppa and gruppa_name.lower() in str(gruppa).lower():
            zapas = feature.get('Запас_на_1_га', '-')
            return str(zapas) if zapas else '-'
        return '-'

    def _prepare_table6_le4(self, features: List[Dict]) -> Dict[str, Any]:
        """
        Подготовка данных для Таблицы 6 (виды и объемы использования).

        Returns:
            Dict: {rows: [...], itogo_ploshad: str}
        """
        # Группировка по целевому назначению и хозяйству
        groups: Dict[Tuple[str, str], float] = {}

        for f in features:
            celevoe = f.get('Целевое_назначение', '-') or '-'
            hozyajstvo = f.get('Хозяйство', '-') or '-'

            # Определяем категорию хозяйства
            hozyajstvo_cat = self._categorize_hozyajstvo(hozyajstvo, f)

            key = (celevoe, hozyajstvo_cat)
            area_m2 = float(f.get('Площадь_ОЗУ', 0) or 0)
            area_ga = area_m2 / 10000

            if key not in groups:
                groups[key] = 0.0
            groups[key] += area_ga

        # Формирование строк
        rows = []
        total_area = 0.0

        # Сначала защитные
        for (celevoe, hozyajstvo), area in sorted(groups.items()):
            if 'защитн' in celevoe.lower():
                rows.append({
                    "celevoe": celevoe,
                    "hozyajstvo": hozyajstvo,
                    "ploshad": self._format_area(area),
                })
                total_area += area

        # Затем эксплуатационные
        for (celevoe, hozyajstvo), area in sorted(groups.items()):
            if 'защитн' not in celevoe.lower():
                rows.append({
                    "celevoe": celevoe,
                    "hozyajstvo": hozyajstvo,
                    "ploshad": self._format_area(area),
                })
                total_area += area

        return {
            "rows": rows,
            "itogo_ploshad": self._format_area(total_area),
        }

    def _categorize_hozyajstvo(self, hozyajstvo: str, feature: Dict) -> str:
        """Определить категорию хозяйства."""
        if not hozyajstvo or hozyajstvo == '-':
            # Определяем по составу и распределению
            sostav = feature.get('Состав', '')
            raspredelenie = feature.get('Распределение_земель', '')

            if raspredelenie:
                raspr_lower = str(raspredelenie).lower()
                if any(x in raspr_lower for x in ['дорог', 'болот', 'просек', 'трасс', 'карьер']):
                    return 'Нелесное'
                if any(x in raspr_lower for x in ['вырубк', 'прогалин', 'погиб']):
                    return 'Непокрытое'

            if sostav:
                first_char = str(sostav)[0].upper() if sostav else ''
                if first_char in ['С', 'Е', 'П', 'Л', 'К']:  # Хвойные
                    return 'Хвойное'
                return 'Лиственное'

            return 'Нелесное'

        hozyajstvo_lower = str(hozyajstvo).lower()
        if 'хвойн' in hozyajstvo_lower:
            return 'Хвойное'
        elif 'листв' in hozyajstvo_lower:
            return 'Лиственное'
        elif 'непокр' in hozyajstvo_lower:
            return 'Непокрытое'
        else:
            return 'Нелесное'

    def _prepare_ozu_le4(self, features: List[Dict]) -> Dict[str, Any]:
        """
        Подготовка данных об ОЗУ для Le_3_*.

        Returns:
            Dict: {est: bool, text: str, types: [...]}
        """
        # Группировка по типам ОЗУ
        ozu_groups: Dict[str, List[Dict]] = {}

        for f in features:
            ozu_type = f.get('ОЗУ')
            if not ozu_type or str(ozu_type) == '-':
                continue

            ozu_type = str(ozu_type)
            if ozu_type not in ozu_groups:
                ozu_groups[ozu_type] = []

            ozu_groups[ozu_type].append({
                "kvartal": str(f.get('Номер_квартала', '')),
                "vydel": str(f.get('Номер_выдела', '')),
                "uch_lesnichestvo": f.get('Уч_лесничество', ''),
                "lesnichestvo": f.get('Лесничество', '')
            })

        if not ozu_groups:
            return {
                "est": False,
                "text": "",
                "types": []
            }

        # Формирование текста и типов
        types = []
        for ozu_type, items in sorted(ozu_groups.items()):
            # Группировка по уч. лесничеству
            uch_groups: Dict[str, Dict[str, set]] = {}
            for item in items:
                uch = item['uch_lesnichestvo']
                kvartal = item['kvartal']
                vydel = item['vydel']

                if uch not in uch_groups:
                    uch_groups[uch] = {}
                if kvartal not in uch_groups[uch]:
                    uch_groups[uch][kvartal] = set()
                if vydel:
                    uch_groups[uch][kvartal].add(vydel)

            # Формирование строк
            type_items = []
            for uch, kvartaly in sorted(uch_groups.items()):
                for kvartal, vydely in sorted(kvartaly.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
                    vydely_str = ', '.join(sorted(vydely, key=lambda x: int(x) if x.isdigit() else 0))
                    if vydely_str:
                        type_items.append(
                            f"в квартале N {kvartal} (части выделов {vydely_str}) {uch} участкового лесничества"
                        )
                    else:
                        type_items.append(
                            f"в квартале N {kvartal} {uch} участкового лесничества"
                        )

            types.append({
                "name": ozu_type,
                "items": type_items
            })

        return {
            "est": True,
            "text": "Согласно данным государственного лесного реестра на территории проектируемого лесного участка выделены особо защитные участки лесов:",
            "types": types
        }
