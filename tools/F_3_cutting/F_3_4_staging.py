# -*- coding: utf-8 -*-
"""
F_3_4_Этапность - Формирование этапов кадастровых работ

Создаёт многоэтапную структуру нарезки для площадных объектов (ОКС):
- 1 этап: Первоначальный раздел (копия из F_3_3 с привязкой к ЗПР)
- 2 этап: Объединение контуров по границам ЗПР
- Итог: Финальные контуры соответствующие конфигурации ЗПР

Логика работы:
1. Копирует слои нарезки из F_3_3 в слои 1 этапа
2. Анализирует соответствие участков контурам ЗПР (intersection area >= 80%)
3. Присваивает ID:
   - Соответствующие ЗПР: ID = ID контура ЗПР
   - Не соответствующие: ID = 100+ (следующий разряд от max контуров ЗПР)
4. Объединяет участки с одинаковым ID по ЗПР во 2 этапе
5. Формирует итоговый слой из 1 этапа (без объединённых) + результаты 2 этапа
"""

from typing import Optional, Dict, List, Any, Tuple, TYPE_CHECKING
from collections import defaultdict

from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (
    QgsProject, Qgis, QgsVectorLayer, QgsFeature,
    QgsGeometry, QgsField, QgsFields
)
from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.managers import get_project_structure_manager
from Daman_QGIS.constants import (
    PLUGIN_NAME, MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION,
    COORDINATE_PRECISION,
    # Исходные слои нарезки (после F_3_3)
    LAYER_CUTTING_OKS_RAZDEL, LAYER_CUTTING_OKS_NGS,
    LAYER_CUTTING_POINTS_OKS_RAZDEL, LAYER_CUTTING_POINTS_OKS_NGS,
    # Слой Без_Меж (после F_3_2, без точек)
    LAYER_CUTTING_OKS_BEZ_MEZH,
    # ЗПР ОКС
    LAYER_ZPR_OKS,
    # Выборка КК
    LAYER_SELECTION_KK,
    # Слои этапности - полигоны
    LAYER_STAGING_1_RAZDEL, LAYER_STAGING_1_NGS,
    LAYER_STAGING_1_BEZ_MEZH, LAYER_STAGING_1_PS,
    LAYER_STAGING_2_RAZDEL, LAYER_STAGING_2_NGS,
    LAYER_STAGING_2_BEZ_MEZH, LAYER_STAGING_2_PS,
    LAYER_STAGING_FINAL_RAZDEL, LAYER_STAGING_FINAL_NGS,
    LAYER_STAGING_FINAL_BEZ_MEZH, LAYER_STAGING_FINAL_PS,
    # Слои этапности - точки
    LAYER_STAGING_POINTS_1_RAZDEL, LAYER_STAGING_POINTS_1_NGS,
    LAYER_STAGING_POINTS_1_BEZ_MEZH, LAYER_STAGING_POINTS_1_PS,
    LAYER_STAGING_POINTS_2_RAZDEL, LAYER_STAGING_POINTS_2_NGS,
    LAYER_STAGING_POINTS_2_BEZ_MEZH, LAYER_STAGING_POINTS_2_PS,
    LAYER_STAGING_POINTS_FINAL_RAZDEL, LAYER_STAGING_POINTS_FINAL_NGS,
    LAYER_STAGING_POINTS_FINAL_BEZ_MEZH, LAYER_STAGING_POINTS_FINAL_PS,
)
from Daman_QGIS.utils import log_info, log_warning, log_error

# Импорт менеджеров
from Daman_QGIS.managers import (
    PointNumberingManager, StyleManager, LabelManager, VRIAssignmentManager,
    WorkTypeAssignmentManager, LayerType, StageType, DataCleanupManager,
    OksZuAnalysisManager
)

# Импорт субмодулей F_3_1 для переиспользования
from .submodules.Fsm_3_1_2_attribute_mapper import Fsm_3_1_2_AttributeMapper
from .submodules.Fsm_3_1_5_kk_matcher import Fsm_3_1_5_KKMatcher
from .submodules.Fsm_3_1_6_point_layer_creator import Fsm_3_1_6_PointLayerCreator

if TYPE_CHECKING:
    from Daman_QGIS.managers import LayerManager


class F_3_4_Staging(BaseTool):
    """Инструмент формирования этапности кадастровых работ"""

    # Порог совпадения площади пересечения с ЗПР (80%)
    ZPR_MATCH_THRESHOLD = 0.80

    # Маппинг исходных слоёв → слои этапов
    # Формат: (source_poly, source_points, stage1_poly, stage1_points,
    #          stage2_poly, stage2_points, final_poly, final_points, layer_type)
    # Для Без_Меж: source_points, stage1_points, stage2_*, final_points = None
    LAYER_MAPPING = [
        # Раздел
        (LAYER_CUTTING_OKS_RAZDEL, LAYER_CUTTING_POINTS_OKS_RAZDEL,
         LAYER_STAGING_1_RAZDEL, LAYER_STAGING_POINTS_1_RAZDEL,
         LAYER_STAGING_2_RAZDEL, LAYER_STAGING_POINTS_2_RAZDEL,
         LAYER_STAGING_FINAL_RAZDEL, LAYER_STAGING_POINTS_FINAL_RAZDEL,
         'RAZDEL'),
        # НГС
        (LAYER_CUTTING_OKS_NGS, LAYER_CUTTING_POINTS_OKS_NGS,
         LAYER_STAGING_1_NGS, LAYER_STAGING_POINTS_1_NGS,
         LAYER_STAGING_2_NGS, LAYER_STAGING_POINTS_2_NGS,
         LAYER_STAGING_FINAL_NGS, LAYER_STAGING_POINTS_FINAL_NGS,
         'NGS'),
        # Без_Меж (БЕЗ ТОЧЕК, БЕЗ 2 ЭТАПА!)
        (LAYER_CUTTING_OKS_BEZ_MEZH, None,  # source_points = None
         LAYER_STAGING_1_BEZ_MEZH, None,     # stage1_points = None
         None, None,                          # stage2 = None (НЕТ 2 ЭТАПА!)
         LAYER_STAGING_FINAL_BEZ_MEZH, None,  # final_points = None
         'BEZ_MEZH'),
    ]

    def __init__(self, iface: Any) -> None:
        """Инициализация инструмента"""
        super().__init__(iface)
        self.layer_manager: Optional['LayerManager'] = None
        self.plugin_dir: Optional[str] = None
        self._attribute_mapper: Optional[Fsm_3_1_2_AttributeMapper] = None
        self._kk_matcher: Optional[Fsm_3_1_5_KKMatcher] = None
        self._vri_manager: Optional[VRIAssignmentManager] = None
        self._work_type_manager: Optional[WorkTypeAssignmentManager] = None
        self._point_layer_creator: Optional[Fsm_3_1_6_PointLayerCreator] = None
        self._oks_zu_manager: Optional[OksZuAnalysisManager] = None
        self._gpkg_path: Optional[str] = None

    def set_plugin_dir(self, plugin_dir: str) -> None:
        """Установка пути к папке плагина"""
        self.plugin_dir = plugin_dir

    def set_layer_manager(self, layer_manager: 'LayerManager') -> None:
        """Установка менеджера слоёв"""
        self.layer_manager = layer_manager

    @staticmethod
    def get_name() -> str:
        """Имя инструмента для cleanup"""
        return "F_3_4_Этапность"

    def run(self) -> None:
        """Основной метод запуска инструмента (без диалога)"""
        log_info("F_3_4: Запуск формирования этапности")

        # Проверка открытого проекта
        if not self.check_project_opened():
            return

        # Автоматическая очистка слоев перед выполнением
        self.auto_cleanup_layers()

        # Выполняем формирование этапности
        self._execute()

    def _execute(self) -> None:
        """Основная логика формирования этапности"""
        log_info("F_3_4: Начало формирования этапности")

        # 1. Инициализация
        if not self._initialize():
            return

        # 2. Проверка наличия исходных слоёв (после F_3_3)
        source_layers = self._get_source_layers()
        if not source_layers:
            QMessageBox.warning(
                None, PLUGIN_NAME,
                "Не найдены слои нарезки.\n\n"
                "Сначала выполните нарезку через F_3_1 и корректировку через F_3_3."
            )
            return

        # 2.1. Валидация структуры полей исходных слоёв
        missing_fields = self._validate_source_layer_fields(source_layers)
        if missing_fields:
            fields_str = ", ".join(missing_fields)
            QMessageBox.warning(
                None, PLUGIN_NAME,
                f"Устаревшая структура слоёв нарезки.\n\n"
                f"Отсутствуют поля: {fields_str}\n\n"
                f"Пересоздайте нарезку через F_3_1 для обновления структуры."
            )
            return

        # 3. Загрузка слоя ЗПР_ОКС
        zpr_layer = self._get_zpr_layer()
        if not zpr_layer:
            QMessageBox.warning(
                None, PLUGIN_NAME,
                f"Не найден слой ЗПР_ОКС ({LAYER_ZPR_OKS}).\n\n"
                "Загрузите слой ЗПР перед запуском этапности."
            )
            return

        # 4. Валидация ВРИ в слое ЗПР (только логирование, без GUI)
        if self._vri_manager:
            is_valid, errors = self._vri_manager.validate_zpr_vri(zpr_layer)
            if not is_valid:
                for error in errors:
                    log_warning(f"F_3_4: Валидация ВРИ: {error}")
                # Продолжаем выполнение - ВРИ будет установлено как "-"

        # 5. Получение максимального ID контуров ЗПР
        max_zpr_id = self._get_max_zpr_id(zpr_layer)
        # Вычисляем начало следующего разряда (например, 83 → 100, 150 → 200)
        next_id_base = ((max_zpr_id // 100) + 1) * 100
        log_info(f"F_3_4: Макс. ID ЗПР = {max_zpr_id}, "
                f"ID для несоответствующих участков начинается с {next_id_base}")

        # 5. Обработка каждого типа слоёв (Раздел, НГС)
        for mapping in self.LAYER_MAPPING:
            (source_poly, source_points,
             stage1_poly, stage1_points,
             stage2_poly, stage2_points,
             final_poly, final_points,
             layer_type) = mapping

            if source_poly not in source_layers:
                log_info(f"F_3_4: Исходный слой {source_poly} не найден, пропуск")
                continue

            source_layer = source_layers[source_poly]
            log_info(f"F_3_4: Обработка слоя {source_poly} ({layer_type})")

            # Сброс счётчиков КН для каждого типа слоя
            self._attribute_mapper.reset_kn_counters()

            self._process_layer_staging(
                source_layer=source_layer,
                zpr_layer=zpr_layer,
                stage1_name=stage1_poly,
                stage1_points_name=stage1_points,
                stage2_name=stage2_poly,
                stage2_points_name=stage2_points,
                final_name=final_poly,
                final_points_name=final_points,
                layer_type=layer_type,
                next_id_base=next_id_base
            )

        # 7. Применение стилей и подписей
        self._apply_styles_and_labels()

        # 8. Сортировка слоёв
        if self.layer_manager:
            self.layer_manager.sort_all_layers()
            log_info("F_3_4: Слои отсортированы")

        # 9. Валидация минимальных площадей
        self._validate_min_areas()

        # 10. Завершение
        log_info("F_3_4: Формирование этапности завершено")
        self.iface.messageBar().pushMessage(
            PLUGIN_NAME,
            "Этапность сформирована успешно",
            level=Qgis.Success,
            duration=MESSAGE_SUCCESS_DURATION
        )

    def _initialize(self) -> bool:
        """Инициализация компонентов"""
        if not self.plugin_dir:
            log_error("F_3_4: Не установлен путь к плагину (plugin_dir)")
            return False

        self._attribute_mapper = Fsm_3_1_2_AttributeMapper(self.plugin_dir)

        structure_manager = get_project_structure_manager()
        self._gpkg_path = structure_manager.get_gpkg_path(create=False)
        if not self._gpkg_path:
            log_error("F_3_4: Не найден путь к project.gpkg")
            return False

        self._point_layer_creator = Fsm_3_1_6_PointLayerCreator(self._gpkg_path)

        # Инициализируем KKMatcher для привязки 2 этапа к КК
        kk_layer = self._get_kk_layer()
        self._kk_matcher = Fsm_3_1_5_KKMatcher(kk_layer) if kk_layer else None

        # Инициализируем VRIManager для присвоения ВРИ в итоговом слое
        self._vri_manager = VRIAssignmentManager(self.plugin_dir)

        # Инициализируем WorkTypeManager для присвоения Вид_Работ
        self._work_type_manager = WorkTypeAssignmentManager(self.plugin_dir)

        # Инициализируем OksZuAnalysisManager для пересчёта ОКС на 2 этапе
        self._oks_zu_manager = OksZuAnalysisManager()

        return True

    def _get_source_layers(self) -> Dict[str, QgsVectorLayer]:
        """Получение исходных слоёв нарезки"""
        result = {}
        project = QgsProject.instance()

        for source_poly, _, _, _, _, _, _, _, _ in self.LAYER_MAPPING:
            layers = project.mapLayersByName(source_poly)
            if layers and isinstance(layers[0], QgsVectorLayer) and layers[0].isValid() and layers[0].featureCount() > 0:
                result[source_poly] = layers[0]
                log_info(f"F_3_4: Найден слой {source_poly} "
                        f"({layers[0].featureCount()} объектов)")

        return result

    def _get_zpr_layer(self) -> Optional[QgsVectorLayer]:
        """Получение слоя ЗПР_ОКС"""
        project = QgsProject.instance()
        layers = project.mapLayersByName(LAYER_ZPR_OKS)
        if layers and isinstance(layers[0], QgsVectorLayer) and layers[0].isValid():
            return layers[0]
        return None

    def _get_kk_layer(self) -> Optional[QgsVectorLayer]:
        """Получение слоя кадастровых кварталов"""
        project = QgsProject.instance()
        layers = project.mapLayersByName(LAYER_SELECTION_KK)
        if layers and isinstance(layers[0], QgsVectorLayer) and layers[0].isValid():
            return layers[0]
        return None

    def _validate_source_layer_fields(
        self,
        source_layers: Dict[str, QgsVectorLayer]
    ) -> List[str]:
        """Валидация структуры полей исходных слоёв

        Проверяет наличие обязательных полей согласно актуальной схеме Base_cutting.json.

        Returns:
            List[str]: Список отсутствующих полей (пустой если всё ОК)
        """
        # Обязательные поля для F_3_4 (наследование ОКС)
        required_fields = {'ОКС_на_ЗУ_выписка', 'ОКС_на_ЗУ_факт'}

        missing = set()
        for layer_name, layer in source_layers.items():
            layer_field_names = {f.name() for f in layer.fields()}
            layer_missing = required_fields - layer_field_names
            if layer_missing:
                log_warning(f"F_3_4: Слой {layer_name} не содержит полей: {layer_missing}")
                missing.update(layer_missing)

        return list(missing)

    def _get_max_zpr_id(self, zpr_layer: QgsVectorLayer) -> int:
        """Получение максимального ID контуров ЗПР"""
        max_id = 0
        id_idx = zpr_layer.fields().indexFromName('ID')
        if id_idx < 0:
            log_warning("F_3_4: Поле ID не найдено в слое ЗПР, используем fid")
            for feature in zpr_layer.getFeatures():
                max_id = max(max_id, feature.id())
        else:
            for feature in zpr_layer.getFeatures():
                fid = feature['ID']
                if fid and isinstance(fid, (int, float)):
                    max_id = max(max_id, int(fid))
        return max_id

    def _process_layer_staging(
        self,
        source_layer: QgsVectorLayer,
        zpr_layer: QgsVectorLayer,
        stage1_name: str,
        stage1_points_name: Optional[str],  # None для Без_Меж
        stage2_name: Optional[str],          # None для Без_Меж
        stage2_points_name: Optional[str],   # None для Без_Меж
        final_name: str,
        final_points_name: Optional[str],    # None для Без_Меж
        layer_type: str,
        next_id_base: int
    ) -> None:
        """Обработка одного типа слоя через все этапы"""
        log_info(f"F_3_4: Обработка этапности для {layer_type}")

        # Специальная обработка для Без_Меж (без точек и 2 этапа)
        if layer_type == 'BEZ_MEZH':
            self._process_bez_mezh_staging(
                source_layer=source_layer,
                zpr_layer=zpr_layer,
                stage1_name=stage1_name,
                final_name=final_name
            )
            return

        # 1. Анализ соответствия участков контурам ЗПР
        # feature_zpr_mapping: {feature_id: zpr_id}
        # features_by_zpr: {zpr_id: [feature_ids]}
        feature_zpr_mapping, features_by_zpr = self._analyze_zpr_matching(
            source_layer, zpr_layer
        )

        # 2. Определение какие участки соответствуют ЗПР (один участок = один контур ЗПР)
        # Соответствуют: zpr_id имеет ровно один feature
        matching_features = set()  # feature_id которые соответствуют ЗПР
        merging_features = set()   # feature_id которые требуют объединения

        for zpr_id, feature_ids in features_by_zpr.items():
            if len(feature_ids) == 1:
                # Один участок = один контур ЗПР → соответствует
                matching_features.add(feature_ids[0])
            else:
                # Несколько участков на один ЗПР → требуют объединения
                merging_features.update(feature_ids)

        log_info(f"F_3_4: Соответствуют ЗПР: {len(matching_features)}, "
                f"требуют объединения: {len(merging_features)}")

        # 3. Формирование данных для 1 этапа
        stage1_data = self._prepare_stage1_data(
            source_layer, feature_zpr_mapping, matching_features,
            next_id_base
        )

        # 3.1. Присвоение Вид_Работ для 1 этапа
        if self._work_type_manager:
            # Определяем LayerType по layer_type строке
            lt = LayerType.RAZDEL if layer_type == 'RAZDEL' else LayerType.NGS
            stage1_data = self._work_type_manager.assign_work_type_basic(
                stage1_data, lt, zpr_layer
            )

        # 3.2. Присвоение План_ВРИ для 1 этапа
        if self._vri_manager:
            stage1_data = self._vri_manager.assign_vri_to_features(
                zpr_layer, stage1_data, zpr_id_key='zpr_id'
            )
            # 3.3. Геометрический ВРИ для контуров, которые будут объединяться
            # Заменяет План_ВРИ на основе геометрического пересечения с ЗПР
            stage1_data = self._vri_manager.assign_vri_by_zpr_geometry(
                stage1_data, zpr_layer
            )

        # 4. Нумерация точек для 1 этапа и обновление поля "Точки"
        stage1_data = self._number_points_and_update_field(stage1_data)

        # 5. Создание слоя 1 этапа
        stage1_layer = self._create_staging_layer(
            stage1_name, source_layer.crs(), source_layer.fields(),
            stage1_data, add_merged_field=False
        )

        # 6. Создание точечного слоя 1 этапа
        if stage1_points_name:
            self._create_points_layer_from_data(stage1_data, stage1_points_name, source_layer.crs())

        # 7. Формирование данных для 2 этапа (только объединяемые участки)
        # Передаём stage1_data чтобы получить правильные ID (100, 101...) для Состав_контуров
        stage2_data, merged_contours_info = self._prepare_stage2_data(
            source_layer, feature_zpr_mapping, features_by_zpr,
            merging_features, stage1_data
        )

        if stage2_data:
            # 7.1. Присвоение Вид_Работ для 2 этапа (с указанием объединённых ID)
            if self._work_type_manager:
                lt = LayerType.RAZDEL if layer_type == 'RAZDEL' else LayerType.NGS
                stage2_data = self._work_type_manager.assign_work_type_stage2(
                    stage2_data, lt, zpr_layer
                )

            # 8. Нумерация точек для 2 этапа и обновление поля "Точки"
            stage2_data = self._number_points_and_update_field(stage2_data)

            # 9. Создание слоя 2 этапа с дополнительным полем "Состав_контуров"
            # Поле добавляется в _create_staging_layer когда add_merged_field=True
            if stage2_name:
                stage2_layer = self._create_staging_layer(
                    stage2_name, source_layer.crs(), source_layer.fields(),
                    stage2_data, add_merged_field=True
                )

            # 10. Создание точечного слоя 2 этапа
            if stage2_points_name:
                self._create_points_layer_from_data(stage2_data, stage2_points_name, source_layer.crs())
        else:
            log_info(f"F_3_4: Нет данных для 2 этапа ({layer_type})")

        # 11. Формирование итогового слоя (с полем Этап, Состав_контуров и ВРИ)
        # Итого = ВСЕ контуры 1 этапа + ВСЕ контуры 2 этапа
        # ВАЖНО: stage1_data и stage2_data уже содержат обновлённое поле "Точки"
        final_data = self._prepare_final_data(
            stage1_data, stage2_data, zpr_layer
        )

        # 11.1. Присвоение Вид_Работ для итогового слоя
        # ВАЖНО: Разделяем обработку по этапам:
        # - Этап 1: assign_work_type_basic() - обычный раздел
        # - Этап 2: assign_work_type_stage2() - объединение с указанием номеров
        if self._work_type_manager:
            lt = LayerType.RAZDEL if layer_type == 'RAZDEL' else LayerType.NGS

            # Разделяем данные по этапам
            stage1_final = [item for item in final_data if item.get('stage') == 1]
            stage2_final = [item for item in final_data if item.get('stage') == 2]

            # Присваиваем Вид_Работ для 1 этапа (базовая логика)
            if stage1_final:
                stage1_final = self._work_type_manager.assign_work_type_basic(
                    stage1_final, lt, zpr_layer
                )

            # Присваиваем Вид_Работ для 2 этапа (объединение с номерами)
            if stage2_final:
                stage2_final = self._work_type_manager.assign_work_type_stage2(
                    stage2_final, lt, zpr_layer
                )

            # Объединяем обратно и пересортируем
            final_data = stage1_final + stage2_final
            final_data.sort(key=lambda x: (x.get('stage', 1), x['attributes'].get('ID', 0)))

        # 12. Создание итогового слоя
        final_layer = self._create_staging_layer(
            final_name, source_layer.crs(), source_layer.fields(),
            final_data,
            add_merged_field=True,  # Добавляем поле Состав_контуров
            add_stage_field=True    # Добавляем поле Этап перед ID
        )

        # 13. Создание итогового точечного слоя из точек 1 и 2 этапов
        # Объединяем точки с полем "Этап" - дубли по ID нормальны (разные чертежи)
        if stage1_points_name and stage2_points_name and final_points_name:
            self._create_final_points_layer(
                stage1_points_name,
                stage2_points_name,
                final_points_name,
                source_layer.crs()
            )

        log_info(f"F_3_4: Этапность для {layer_type} завершена: "
                f"1 этап={len(stage1_data)}, 2 этап={len(stage2_data)}, "
                f"итог={len(final_data)}")

    def _analyze_zpr_matching(
        self,
        source_layer: QgsVectorLayer,
        zpr_layer: QgsVectorLayer
    ) -> Tuple[Dict[int, int], Dict[int, List[int]]]:
        """Анализ соответствия участков контурам ЗПР

        Определяет к какому контуру ЗПР относится каждый участок
        по максимальной площади пересечения (>= 80%).

        Returns:
            Tuple:
                - feature_zpr_mapping: {feature_id: zpr_id}
                - features_by_zpr: {zpr_id: [feature_ids]}
        """
        feature_zpr_mapping: Dict[int, int] = {}
        features_by_zpr: Dict[int, List[int]] = defaultdict(list)

        # Получаем индекс поля ID в ЗПР
        zpr_id_idx = zpr_layer.fields().indexFromName('ID')

        # Кэшируем геометрии и ID контуров ЗПР
        zpr_data = []
        for zpr_feature in zpr_layer.getFeatures():
            zpr_geom = zpr_feature.geometry()
            if zpr_geom.isEmpty():
                continue

            if zpr_id_idx >= 0:
                zpr_id = zpr_feature['ID']
            else:
                zpr_id = zpr_feature.id()

            if not zpr_id:
                zpr_id = zpr_feature.id()

            zpr_data.append({
                'id': int(zpr_id),
                'geometry': zpr_geom,
                'area': zpr_geom.area()
            })

        # Анализируем каждый участок
        for feature in source_layer.getFeatures():
            feature_id = feature.id()
            feature_geom = feature.geometry()

            if feature_geom.isEmpty():
                continue

            feature_area = feature_geom.area()

            # Находим ЗПР с максимальным пересечением
            best_zpr_id = None
            best_intersection_ratio = 0.0

            for zpr in zpr_data:
                intersection = feature_geom.intersection(zpr['geometry'])
                if intersection.isEmpty():
                    continue

                intersection_area = intersection.area()
                # Отношение площади пересечения к площади участка
                ratio = intersection_area / feature_area if feature_area > 0 else 0

                if ratio > best_intersection_ratio:
                    best_intersection_ratio = ratio
                    best_zpr_id = zpr['id']

            # Если пересечение >= 80% - привязываем к ЗПР
            if best_zpr_id is not None and best_intersection_ratio >= self.ZPR_MATCH_THRESHOLD:
                feature_zpr_mapping[feature_id] = best_zpr_id
                features_by_zpr[best_zpr_id].append(feature_id)
            else:
                # Участок не соответствует ни одному ЗПР достаточно
                log_warning(f"F_3_4: Участок {feature_id} не соответствует ни одному ЗПР "
                           f"(лучшее пересечение {best_intersection_ratio:.1%})")

        return feature_zpr_mapping, dict(features_by_zpr)

    def _prepare_stage1_data(
        self,
        source_layer: QgsVectorLayer,
        feature_zpr_mapping: Dict[int, int],
        matching_features: set,
        next_id_base: int
    ) -> List[Dict[str, Any]]:
        """Подготовка данных для 1 этапа

        ID назначается:
        - Для соответствующих ЗПР: ID = ID контура ЗПР
        - Для несоответствующих: ID = next_id_base + счётчик
        """
        stage1_data = []
        non_matching_counter = 0

        for feature in source_layer.getFeatures():
            feature_id = feature.id()
            geom = feature.geometry()

            if geom.isEmpty():
                continue

            # Копируем атрибуты
            attrs = {}
            for field in source_layer.fields():
                attrs[field.name()] = feature[field.name()]

            # Назначаем ID
            if feature_id in feature_zpr_mapping:
                zpr_id = feature_zpr_mapping[feature_id]
                if feature_id in matching_features:
                    # Соответствует ЗПР → ID = ID ЗПР
                    attrs['ID'] = zpr_id
                else:
                    # Требует объединения → ID с нового разряда
                    attrs['ID'] = next_id_base + non_matching_counter
                    non_matching_counter += 1
            else:
                # Не привязан к ЗПР
                attrs['ID'] = next_id_base + non_matching_counter
                non_matching_counter += 1

            stage1_data.append({
                'geometry': QgsGeometry(geom),
                'attributes': attrs,
                'original_fid': feature_id,
                'zpr_id': feature_zpr_mapping.get(feature_id)
            })

        # Сортировка по ID
        stage1_data.sort(key=lambda x: x['attributes'].get('ID', 0))

        return stage1_data

    def _prepare_stage2_data(
        self,
        source_layer: QgsVectorLayer,
        feature_zpr_mapping: Dict[int, int],
        features_by_zpr: Dict[int, List[int]],
        merging_features: set,
        stage1_data: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], Dict[int, str]]:
        """Подготовка данных для 2 этапа (объединение)

        Объединяет участки с одинаковым zpr_id в один контур.
        Добавляет поле "Состав_контуров" с перечислением ID из 1 этапа (100, 101...).
        КН и Услов_КН присваиваются по логике НГС - привязка к КК (не к ЗУ),
        так как на момент 2 этапа ещё неизвестно какой номер ЗУ будет присвоен.

        Args:
            stage1_data: Данные 1 этапа для получения правильных ID

        Returns:
            Tuple:
                - stage2_data: список объединённых контуров
                - merged_contours_info: {zpr_id: "100;101;102"}
        """
        if not merging_features:
            return [], {}

        stage2_data = []
        merged_contours_info: Dict[int, str] = {}

        # Создаём маппинг original_fid → данные из stage1_data
        # ВАЖНО: Используем stage1_data вместо source_layer.getFeature()
        # потому что feature.id() в QGIS может быть нестабильным для GPKG слоёв
        fid_to_stage1_item: Dict[int, Dict] = {}
        for item in stage1_data:
            original_fid = item.get('original_fid')
            if original_fid is not None:
                fid_to_stage1_item[original_fid] = item

        # Проверяем наличие полей ОКС
        has_oks_vypiska = any('ОКС_на_ЗУ_выписка' in item.get('attributes', {}) for item in stage1_data[:1])
        has_oks_fact = any('ОКС_на_ЗУ_факт' in item.get('attributes', {}) for item in stage1_data[:1])

        # Группируем по zpr_id для объединения
        groups_with_multiple = [(zpr_id, len(fids)) for zpr_id, fids in features_by_zpr.items() if len(fids) > 1]
        log_info(f"F_3_4: Групп для объединения (2 этап): {len(groups_with_multiple)}")

        for zpr_id, feature_ids in features_by_zpr.items():
            if len(feature_ids) <= 1:
                continue  # Не требует объединения

            # Собираем геометрии для объединения из stage1_data
            geometries = []
            stage1_ids = []  # ID из 1 этапа (100, 101...)
            sample_attrs = None
            # Собираем значения ОКС полей из всех объединяемых участков
            oks_vypiska_values: set = set()
            oks_fact_values: set = set()

            for fid in feature_ids:
                # Используем данные из stage1_data вместо source_layer.getFeature()
                stage1_item = fid_to_stage1_item.get(fid)
                if not stage1_item:
                    log_warning(f"F_3_4: zpr_id={zpr_id}, fid={fid} - не найден в stage1_data")
                    continue

                geom = stage1_item.get('geometry')
                if not geom or geom.isEmpty():
                    log_warning(f"F_3_4: zpr_id={zpr_id}, fid={fid} - геометрия пустая")
                    continue

                geometries.append(QgsGeometry(geom))
                # Берём ID из 1 этапа (100, 101...)
                stage1_id = stage1_item['attributes'].get('ID', fid)
                stage1_ids.append(str(stage1_id))

                attrs = stage1_item.get('attributes', {})
                if sample_attrs is None:
                    sample_attrs = dict(attrs)

                # Собираем ОКС_на_ЗУ_выписка (дедупликация внутри колонки)
                if has_oks_vypiska:
                    val = attrs.get('ОКС_на_ЗУ_выписка')
                    if val and str(val).strip() and str(val).strip() != '-':
                        for kn in str(val).split(';'):
                            kn_clean = kn.strip()
                            if kn_clean and kn_clean != '-':
                                oks_vypiska_values.add(kn_clean)

                # Собираем ОКС_на_ЗУ_факт (дедупликация внутри колонки)
                if has_oks_fact:
                    val = attrs.get('ОКС_на_ЗУ_факт')
                    if val and str(val).strip() and str(val).strip() != '-':
                        for kn in str(val).split(';'):
                            kn_clean = kn.strip()
                            if kn_clean and kn_clean != '-':
                                oks_fact_values.add(kn_clean)

            if not geometries or len(geometries) < 2:
                log_warning(f"F_3_4: zpr_id={zpr_id} пропущен - geometries={len(geometries)}, feature_ids={len(feature_ids)}")
                continue

            # Объединяем геометрии
            merged_geom = QgsGeometry.unaryUnion(geometries)
            # Округляем координаты до стандартной точности после объединения
            merged_geom = merged_geom.snappedToGrid(COORDINATE_PRECISION, COORDINATE_PRECISION)

            if merged_geom.isEmpty():
                log_warning(f"F_3_4: Не удалось объединить контуры для ЗПР {zpr_id}")
                continue

            # Формируем строку состава контуров (ID из 1 этапа: 100, 101...)
            contours_str = ", ".join(sorted(stage1_ids, key=lambda x: int(x) if x.isdigit() else 0))
            merged_contours_info[zpr_id] = contours_str

            # Атрибуты для объединённого контура
            # Во 2 этапе - как НГС: привязка к КК, без информации о сущ. ЗУ
            # Поля исходных ЗУ (Категория, ВРИ, Площадь и т.д.) должны быть пустыми,
            # так как контуры ещё не существуют - получат КН только после 1 этапа.
            # Санитайзер в конце заменит пустые/NULL значения на "-".
            attrs = dict(sample_attrs) if sample_attrs else {}
            attrs['ID'] = zpr_id  # ID = ID контура ЗПР

            # Очищаем поля исходных ЗУ - на 2 этапе они неизвестны
            # (исключения: План_категория, План_ВРИ, Площадь_ОЗУ - их мы знаем)
            fields_to_clear = [
                'Тип_объекта', 'Категория', 'ВРИ', 'Площадь',
                'Права', 'Обременение', 'Собственники', 'Арендаторы'
            ]
            for field_name in fields_to_clear:
                if field_name in attrs:
                    attrs[field_name] = None  # Будет заменено на "-" санитайзером

            # Адрес для 2 этапа - заглушка для ручного заполнения
            attrs['Адрес_Местоположения'] = 'ЗАПОЛНИ!'

            # Привязка к КК (как НГС) - используем KKMatcher с проверкой нулёвок
            # КН = номер кадастрового квартала
            # Услов_КН = КН:ЗУ{N} (как для НГС)
            kk_kn = None
            if self._kk_matcher:
                kk_kn = self._kk_matcher.find_quarter_for_geometry(merged_geom)

            if kk_kn:
                # Валидный квартал найден (не нулёвка)
                attrs['КН'] = kk_kn
                # Генерируем Услов_КН через AttributeMapper (счётчик для каждого КН)
                attrs['Услов_КН'] = self._attribute_mapper.generate_conditional_kn(kk_kn)
            else:
                # Квартал не найден или нулёвка
                attrs['КН'] = "-"
                attrs['Услов_КН'] = "-"

            # Пересчёт площади (целое число как в Base_cutting.json)
            attrs['Площадь_ОЗУ'] = int(round(merged_geom.area()))

            # Пересчёт ОКС_на_ЗУ для 2 этапа через M_23:
            # - выписка = "-" (КН неизвестен, как НГС)
            # - факт = ПЕРЕСЧИТАТЬ геометрически для объединённой геометрии
            if self._oks_zu_manager:
                # source_kn = None означает логику НГС (выписка не используется)
                oks_values = self._oks_zu_manager.analyze_cutting_geometry(
                    geometry=merged_geom,
                    source_kn=None  # Как НГС - выписка = "-"
                )
                attrs['ОКС_на_ЗУ_выписка'] = oks_values.get('ОКС_на_ЗУ_выписка', '-')
                attrs['ОКС_на_ЗУ_факт'] = oks_values.get('ОКС_на_ЗУ_факт', '-')
            else:
                # Fallback: объединённые значения из контуров 1 этапа (без дублей)
                attrs['ОКС_на_ЗУ_выписка'] = '-'  # Выписка всегда "-" для 2 этапа
                attrs['ОКС_на_ЗУ_факт'] = '; '.join(sorted(oks_fact_values)) if oks_fact_values else '-'

            stage2_data.append({
                'geometry': merged_geom,
                'attributes': attrs,
                'zpr_id': zpr_id,
                'merged_contours': contours_str
            })

        # Сортировка по ID (zpr_id)
        stage2_data.sort(key=lambda x: x['attributes'].get('ID', 0))

        return stage2_data, merged_contours_info

    def _prepare_final_data(
        self,
        stage1_data: List[Dict[str, Any]],
        stage2_data: List[Dict[str, Any]],
        zpr_layer: QgsVectorLayer
    ) -> List[Dict[str, Any]]:
        """Подготовка данных для итогового слоя

        Итог = ВСЕ контуры из 1 этапа + ВСЕ контуры из 2 этапа

        Поле Этап:
        - Для контуров из 1 этапа: 1
        - Для контуров из 2 этапа: 2

        Поле Состав_контуров:
        - Для контуров 1 этапа: "-"
        - Для объединённых (2 этап): "100, 101, 102"

        Поля План_ВРИ и Общая_земля:
        - Присваиваются на основе ВРИ из слоя ЗПР по ID контура
        """
        final_data = []

        # Добавляем ВСЕ контуры из 1 этапа (Этап=1)
        for item in stage1_data:
            zpr_id = item['attributes'].get('ID')
            final_data.append({
                'geometry': QgsGeometry(item['geometry']),
                'attributes': dict(item['attributes']),
                'merged_contours': '-',  # Контуры 1 этапа не имеют Состав_контуров
                'zpr_id': zpr_id,
                'stage': 1  # Этап 1
            })

        # Добавляем ВСЕ контуры из 2 этапа (Этап=2)
        for item in stage2_data:
            attrs = dict(item['attributes'])
            # ID объединённого контура = ID ЗПР
            zpr_id = item.get('zpr_id') or attrs.get('ID')
            final_data.append({
                'geometry': QgsGeometry(item['geometry']),
                'attributes': attrs,
                'merged_contours': item.get('merged_contours', '-'),
                'zpr_id': zpr_id,
                'stage': 2  # Этап 2
            })

        # Присвоение План_ВРИ и Общее через VRIAssignmentManager
        if self._vri_manager and zpr_layer:
            final_data = self._vri_manager.assign_vri_to_features(
                zpr_layer, final_data, zpr_id_key='zpr_id'
            )

        # Сортировка по Этапу, затем по ID
        final_data.sort(key=lambda x: (x.get('stage', 1), x['attributes'].get('ID', 0)))

        return final_data

    def _process_bez_mezh_staging(
        self,
        source_layer: QgsVectorLayer,
        zpr_layer: QgsVectorLayer,
        stage1_name: str,
        final_name: str
    ) -> None:
        """Обработка Без_Меж: только 1 этап и Итог, без точек и объединения

        Без_Меж - существующие ЗУ без межевания:
        - НЕ нумеруем точки (поле "Точки" = "")
        - НЕ создаём точечные слои
        - НЕ создаём 2 этап (нет объединения)
        - Просто копируем: Источник -> 1 этап -> Итог
        - Присваиваем Вид_Работ из work_types.json
        """
        log_info("F_3_4: Обработка Без_Меж (без точек и 2 этапа)")

        # Сбор данных из источника
        features_data = []
        for feature in source_layer.getFeatures():
            geom = feature.geometry()
            if geom.isEmpty():
                continue

            attrs = {}
            for field in source_layer.fields():
                attrs[field.name()] = feature[field.name()]

            # Поле "Точки" = "" (нет нумерации)
            attrs['Точки'] = ""

            features_data.append({
                'geometry': QgsGeometry(geom),
                'attributes': attrs,
                'stage': 1,  # Всё в 1 этапе
                'zpr_id': attrs.get('ID')
            })

        if not features_data:
            log_info("F_3_4: Нет данных Без_Меж для обработки")
            return

        # Присвоение Вид_Работ для Без_Меж (существующий сохраняемый ЗУ)
        if self._work_type_manager:
            # Для Без_Меж используем специальный work_type
            for item in features_data:
                item['attributes']['Вид_Работ'] = \
                    "Существующий (сохраняемый) земельный участок"

        # Присвоение План_ВРИ из слоя ЗПР
        if self._vri_manager and zpr_layer:
            features_data = self._vri_manager.assign_vri_to_features(
                zpr_layer, features_data, zpr_id_key='zpr_id'
            )

        # Создание слоя 1 этапа (БЕЗ точечного слоя!)
        self._create_staging_layer(
            stage1_name, source_layer.crs(), source_layer.fields(),
            features_data, add_merged_field=False
        )

        # Подготовка данных для итогового слоя
        # Добавляем поля Этап и Состав_контуров
        for item in features_data:
            item['merged_contours'] = '-'  # Нет объединения

        # Создание итогового слоя (БЕЗ точечного слоя!)
        self._create_staging_layer(
            final_name, source_layer.crs(), source_layer.fields(),
            features_data,
            add_merged_field=True,
            add_stage_field=True
        )

        log_info(f"F_3_4: Без_Меж обработан: {len(features_data)} объектов "
                f"(1 этап и Итог, без точек)")

    def _create_staging_layer(
        self,
        layer_name: str,
        crs: Any,
        fields: QgsFields,
        features_data: List[Dict[str, Any]],
        add_merged_field: bool = False,
        add_stage_field: bool = False
    ) -> Optional[QgsVectorLayer]:
        """Создание слоя этапности в GPKG

        Args:
            add_merged_field: Добавить поле "Состав_контуров"
            add_stage_field: Добавить поле "Этап" перед ID (для итогового слоя)
        """
        if not features_data:
            log_info(f"F_3_4: Нет данных для слоя {layer_name}")
            return None

        try:
            from osgeo import ogr, osr

            # Открываем GPKG
            ds = ogr.Open(self._gpkg_path, 1)
            if not ds:
                log_error(f"F_3_4: Не удалось открыть GPKG: {self._gpkg_path}")
                return None

            # Удаляем существующий слой если есть
            for i in range(ds.GetLayerCount()):
                lyr = ds.GetLayerByIndex(i)
                if lyr and lyr.GetName() == layer_name:
                    ds.DeleteLayer(i)
                    break

            # Создаём SRS
            srs = osr.SpatialReference()
            srs.ImportFromWkt(crs.toWkt())

            # Создаём слой
            ogr_layer = ds.CreateLayer(layer_name, srs, ogr.wkbPolygon)
            if not ogr_layer:
                log_error(f"F_3_4: Не удалось создать слой {layer_name}")
                ds = None
                return None

            # Добавляем поле "Этап" ПЕРЕД остальными полями (для итогового слоя)
            if add_stage_field:
                ogr_layer.CreateField(ogr.FieldDefn("Этап", ogr.OFTInteger))

            # Добавляем поля (исключаем зарезервированное поле fid)
            # GeoPackage создаёт fid автоматически, ID используется для номера контура
            for field in fields:
                field_name = field.name()
                if field_name.lower() == 'fid':
                    continue  # Пропускаем системное поле fid
                field_type = ogr.OFTString
                if field.type() == QMetaType.Type.Int:
                    field_type = ogr.OFTInteger
                elif field.type() == QMetaType.Type.Double:
                    field_type = ogr.OFTReal
                ogr_layer.CreateField(ogr.FieldDefn(field_name, field_type))

            # Добавляем поле Состав_контуров для 2 этапа и итогового
            if add_merged_field:
                ogr_layer.CreateField(ogr.FieldDefn("Состав_контуров", ogr.OFTString))

            # Получаем список полей в созданном слое для проверки
            layer_defn = ogr_layer.GetLayerDefn()
            existing_field_names = set()
            for i in range(layer_defn.GetFieldCount()):
                existing_field_names.add(layer_defn.GetFieldDefn(i).GetName())

            # Для отслеживания уже залогированных предупреждений
            warned_fields: set = set()

            # Создаём маппинг имён полей на их типы OGR
            field_types: Dict[str, int] = {}
            for i in range(layer_defn.GetFieldCount()):
                field_defn = layer_defn.GetFieldDefn(i)
                field_types[field_defn.GetName()] = field_defn.GetType()

            # Добавляем объекты
            for item in features_data:
                ogr_feature = ogr.Feature(layer_defn)

                # Геометрия
                geom_wkt = item['geometry'].asWkt()
                ogr_geom = ogr.CreateGeometryFromWkt(geom_wkt)
                ogr_feature.SetGeometry(ogr_geom)

                # Атрибуты (исключаем fid и поля которых нет в слое)
                for field_name, value in item['attributes'].items():
                    if field_name.lower() == 'fid':
                        continue
                    if field_name not in existing_field_names:
                        # Поле не существует в слое - пропускаем (лог один раз)
                        if field_name not in warned_fields:
                            log_warning(f"F_3_4: Поле '{field_name}' отсутствует в слое {layer_name}")
                            warned_fields.add(field_name)
                        continue
                    if value is not None:
                        # Конвертируем значение в совместимый тип для OGR
                        field_type: int = field_types.get(field_name, ogr.OFTString)
                        converted_value = self._convert_value_for_ogr(value, field_type)
                        if converted_value is not None:
                            ogr_feature.SetField(field_name, converted_value)

                # Поле Этап (для итогового слоя)
                if add_stage_field and 'stage' in item:
                    ogr_feature.SetField("Этап", item['stage'])

                # Поле Состав_контуров
                if add_merged_field and 'merged_contours' in item:
                    ogr_feature.SetField("Состав_контуров", item['merged_contours'])

                ogr_layer.CreateFeature(ogr_feature)

            ds = None  # Закрываем

            # Загружаем слой в QGIS
            uri = f"{self._gpkg_path}|layername={layer_name}"
            qgs_layer = QgsVectorLayer(uri, layer_name, "ogr")

            if qgs_layer.isValid() and self.layer_manager:
                self.layer_manager.add_layer(
                    qgs_layer,
                    make_readonly=False,
                    auto_number=False,
                    check_precision=False
                )

                # Санитизация: замена NULL/пустых значений на "-"
                cleanup_manager = DataCleanupManager()
                cleanup_manager.finalize_layer(qgs_layer, layer_name, capitalize=False)

                log_info(f"F_3_4: Создан слой {layer_name} ({qgs_layer.featureCount()} объектов)")
                return qgs_layer
            else:
                log_error(f"F_3_4: Слой {layer_name} невалиден")
                return None

        except Exception as e:
            log_error(f"F_3_4: Ошибка создания слоя {layer_name}: {e}")
            return None

    def _number_points_and_update_field(
        self,
        features_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Нумерация точек и обновление поля 'Точки' в атрибутах

        Вызывает PointNumberingManager.process_polygon_layer() и обновляет
        поле 'Точки' в атрибутах каждого объекта.

        Args:
            features_data: Список данных объектов с 'geometry' и 'attributes'

        Returns:
            List[Dict]: Обновлённый features_data с заполненным полем 'Точки'
                       и добавленным 'points_data' для создания точечного слоя
        """
        if not features_data:
            return features_data

        # Подготавливаем данные для PointNumberingManager
        # Нужны поля: 'geometry', 'contour_id', 'attributes'
        for item in features_data:
            if 'contour_id' not in item:
                contour_id = item['attributes'].get('ID')
                if contour_id is None:
                    contour_id = 0
                item['contour_id'] = contour_id

        # Нумерация точек
        point_numbering = PointNumberingManager()
        features_with_points, points_data = point_numbering.process_polygon_layer(
            features_data, precision=2
        )

        # Обновление поля "Точки" в атрибутах
        for i, item in enumerate(features_data):
            if i < len(features_with_points):
                point_numbers_str = features_with_points[i].get('point_numbers_str', '-')
                item['attributes']['Точки'] = point_numbers_str
            else:
                item['attributes']['Точки'] = '-'

        # Сохраняем points_data для последующего создания точечного слоя
        # Записываем в последний элемент как служебное поле
        if features_data:
            features_data[0]['_points_data'] = points_data

        log_info(f"F_3_4: Нумерация точек завершена, обновлено {len(features_data)} объектов")
        return features_data

    def _create_points_layer_from_data(
        self,
        features_data: List[Dict[str, Any]],
        points_layer_name: str,
        crs: Any
    ) -> None:
        """Создание точечного слоя из уже пронумерованных данных

        Использует points_data, сохранённые в features_data методом
        _number_points_and_update_field().

        Args:
            features_data: Данные объектов с '_points_data'
            points_layer_name: Имя создаваемого точечного слоя
            crs: Система координат
        """
        if not self._point_layer_creator or not features_data:
            return

        # Извлекаем points_data из служебного поля
        points_data = features_data[0].get('_points_data', [])
        if not points_data:
            log_warning(f"F_3_4: Нет данных точек для слоя {points_layer_name}")
            return

        # Удаляем старый слой если есть
        project = QgsProject.instance()
        old_layers = project.mapLayersByName(points_layer_name)
        for old_layer in old_layers:
            project.removeMapLayer(old_layer.id())

        # Создаём новый слой
        points_layer = self._point_layer_creator.create_point_layer(
            points_layer_name,
            crs,
            points_data
        )

        if points_layer and self.layer_manager:
            self.layer_manager.add_layer(
                points_layer,
                make_readonly=False,
                auto_number=False,
                check_precision=False
            )
            log_info(f"F_3_4: Создан точечный слой {points_layer_name} "
                    f"({points_layer.featureCount()} точек)")

    def _create_points_layer(
        self,
        polygon_layer: Optional[QgsVectorLayer],
        points_layer_name: str
    ) -> None:
        """Создание точечного слоя для полигонального (устаревший метод)

        DEPRECATED: Используйте _number_points_and_update_field() +
        _create_points_layer_from_data() для корректного обновления поля 'Точки'.
        """
        if not polygon_layer or not self._point_layer_creator:
            return

        # Собираем данные объектов
        features_data = []
        for feature in polygon_layer.getFeatures():
            geom = feature.geometry()
            if geom.isEmpty():
                continue

            attrs = {}
            for field in polygon_layer.fields():
                attrs[field.name()] = feature[field.name()]

            # Извлекаем ID контура с проверкой на None
            # ВАЖНО: .get() возвращает None если ключ существует но значение None
            contour_id = attrs.get('ID')
            if contour_id is None:
                contour_id = feature.id() + 1  # Fallback на FID + 1

            features_data.append({
                'geometry': QgsGeometry(geom),
                'contour_id': contour_id,
                'attributes': attrs
            })

        if not features_data:
            return

        # Нумерация точек
        point_numbering = PointNumberingManager()
        features_with_points, points_data = point_numbering.process_polygon_layer(
            features_data, precision=2
        )

        if not points_data:
            return

        # Удаляем старый слой если есть
        project = QgsProject.instance()
        old_layers = project.mapLayersByName(points_layer_name)
        for old_layer in old_layers:
            project.removeMapLayer(old_layer.id())

        # Создаём новый слой
        points_layer = self._point_layer_creator.create_point_layer(
            points_layer_name,
            polygon_layer.crs(),
            points_data
        )

        if points_layer and self.layer_manager:
            self.layer_manager.add_layer(
                points_layer,
                make_readonly=False,
                auto_number=False,
                check_precision=False
            )
            log_info(f"F_3_4: Создан точечный слой {points_layer_name} "
                    f"({points_layer.featureCount()} точек)")

    def _create_final_points_layer(
        self,
        stage1_points_name: str,
        stage2_points_name: str,
        final_points_name: str,
        crs: Any
    ) -> None:
        """Создание итогового точечного слоя из точек 1 и 2 этапов

        Объединяет точки из слоёв 1 и 2 этапов с добавлением поля "Этап".
        Дубли точек по ID - нормальная ситуация, так как каждый этап
        имеет свой чертёж.

        Args:
            stage1_points_name: Имя точечного слоя 1 этапа
            stage2_points_name: Имя точечного слоя 2 этапа
            final_points_name: Имя итогового точечного слоя
            crs: Система координат
        """
        try:
            from osgeo import ogr, osr

            project = QgsProject.instance()

            # Получаем слои точек этапов
            stage1_points_layers = project.mapLayersByName(stage1_points_name)
            stage2_points_layers = project.mapLayersByName(stage2_points_name)

            stage1_points: Optional[QgsVectorLayer] = None
            stage2_points: Optional[QgsVectorLayer] = None
            if stage1_points_layers and isinstance(stage1_points_layers[0], QgsVectorLayer):
                stage1_points = stage1_points_layers[0]
            if stage2_points_layers and isinstance(stage2_points_layers[0], QgsVectorLayer):
                stage2_points = stage2_points_layers[0]

            if not stage1_points and not stage2_points:
                log_warning(f"F_3_4: Не найдены точечные слои этапов для {final_points_name}")
                return

            # Удаляем существующий итоговый слой точек
            old_layers = project.mapLayersByName(final_points_name)
            for old_layer in old_layers:
                project.removeMapLayer(old_layer.id())

            # Открываем GPKG
            ds = ogr.Open(self._gpkg_path, 1)
            if not ds:
                log_error(f"F_3_4: Не удалось открыть GPKG: {self._gpkg_path}")
                return

            # Удаляем существующий слой в GPKG если есть
            for i in range(ds.GetLayerCount()):
                lyr = ds.GetLayerByIndex(i)
                if lyr and lyr.GetName() == final_points_name:
                    ds.DeleteLayer(i)
                    break

            # Создаём SRS
            srs = osr.SpatialReference()
            srs.ImportFromWkt(crs.toWkt())

            # Создаём слой точек
            ogr_layer = ds.CreateLayer(final_points_name, srs, ogr.wkbPoint)
            if not ogr_layer:
                log_error(f"F_3_4: Не удалось создать слой {final_points_name}")
                ds = None
                return

            # Добавляем поле "Этап" первым
            ogr_layer.CreateField(ogr.FieldDefn("Этап", ogr.OFTInteger))

            # Собираем поля из исходных слоёв (берём из первого доступного)
            source_layer = stage1_points or stage2_points
            for field in source_layer.fields():
                field_name = field.name()
                if field_name.lower() == 'fid':
                    continue
                field_type = ogr.OFTString
                if field.type() == QMetaType.Type.Int:
                    field_type = ogr.OFTInteger
                elif field.type() == QMetaType.Type.Double:
                    field_type = ogr.OFTReal
                ogr_layer.CreateField(ogr.FieldDefn(field_name, field_type))

            layer_defn = ogr_layer.GetLayerDefn()
            points_count = 0

            # Создаём маппинг имён полей на их типы OGR
            field_types: Dict[str, int] = {}
            for i in range(layer_defn.GetFieldCount()):
                field_defn_item = layer_defn.GetFieldDefn(i)
                field_types[field_defn_item.GetName()] = field_defn_item.GetType()

            # Копируем точки из 1 этапа
            if stage1_points:
                for feature in stage1_points.getFeatures():
                    geom = feature.geometry()
                    if geom.isEmpty():
                        continue

                    ogr_feature = ogr.Feature(layer_defn)

                    # Геометрия
                    ogr_geom = ogr.CreateGeometryFromWkt(geom.asWkt())
                    ogr_feature.SetGeometry(ogr_geom)

                    # Этап = 1
                    ogr_feature.SetField("Этап", 1)

                    # Копируем атрибуты
                    for field in stage1_points.fields():
                        field_name = field.name()
                        if field_name.lower() == 'fid':
                            continue
                        value = feature[field_name]
                        if value is not None:
                            ogr_field_type: int = field_types.get(field_name, ogr.OFTString)
                            converted = self._convert_value_for_ogr(value, ogr_field_type)
                            if converted is not None:
                                ogr_feature.SetField(field_name, converted)

                    ogr_layer.CreateFeature(ogr_feature)
                    points_count += 1

            # Копируем точки из 2 этапа
            if stage2_points:
                for feature in stage2_points.getFeatures():
                    geom = feature.geometry()
                    if geom.isEmpty():
                        continue

                    ogr_feature = ogr.Feature(layer_defn)

                    # Геометрия
                    ogr_geom = ogr.CreateGeometryFromWkt(geom.asWkt())
                    ogr_feature.SetGeometry(ogr_geom)

                    # Этап = 2
                    ogr_feature.SetField("Этап", 2)

                    # Копируем атрибуты
                    for field in stage2_points.fields():
                        field_name = field.name()
                        if field_name.lower() == 'fid':
                            continue
                        value = feature[field_name]
                        if value is not None:
                            ogr_field_type: int = field_types.get(field_name, ogr.OFTString)
                            converted = self._convert_value_for_ogr(value, ogr_field_type)
                            if converted is not None:
                                ogr_feature.SetField(field_name, converted)

                    ogr_layer.CreateFeature(ogr_feature)
                    points_count += 1

            ds = None  # Закрываем

            # Загружаем слой в QGIS
            uri = f"{self._gpkg_path}|layername={final_points_name}"
            qgs_layer = QgsVectorLayer(uri, final_points_name, "ogr")

            if qgs_layer.isValid() and self.layer_manager:
                self.layer_manager.add_layer(
                    qgs_layer,
                    make_readonly=False,
                    auto_number=False,
                    check_precision=False
                )
                log_info(f"F_3_4: Создан итоговый точечный слой {final_points_name} "
                        f"({points_count} точек из этапов 1 и 2)")
            else:
                log_error(f"F_3_4: Слой {final_points_name} невалиден")

        except Exception as e:
            log_error(f"F_3_4: Ошибка создания итогового точечного слоя: {e}")
            import traceback
            log_error(traceback.format_exc())

    def _validate_min_areas(self) -> None:
        """Валидация минимальных площадей по ВРИ для ОКС

        Вызывает M_27_MinAreaValidator для проверки контуров стейджинга.
        F_3_4 работает только с ОКС, поэтому проверяем только этот тип.
        """
        try:
            from Daman_QGIS.managers import MinAreaValidator

            validator = MinAreaValidator(self.plugin_dir)
            result = validator.validate_cutting_results('ОКС', show_dialog=True)

            if result.get('skipped_no_field'):
                log_info("F_3_4: Валидация ОКС пропущена (нет поля MIN_AREA_VRI)")
            elif result.get('success'):
                log_info("F_3_4: Валидация ОКС успешна")
            else:
                log_warning(
                    f"F_3_4: Валидация ОКС - найдено {result.get('problem_count', 0)} "
                    f"контуров с недостаточной площадью"
                )
        except Exception as e:
            log_error(f"F_3_4: Ошибка валидации минимальных площадей: {e}")

    def _apply_styles_and_labels(self) -> None:
        """Применение стилей и подписей ко всем слоям этапности"""
        style_manager = StyleManager()
        label_manager = LabelManager()
        project = QgsProject.instance()

        # Собираем все слои этапности
        all_layer_names = [
            # Полигоны - Раздел
            LAYER_STAGING_1_RAZDEL, LAYER_STAGING_2_RAZDEL, LAYER_STAGING_FINAL_RAZDEL,
            # Полигоны - НГС
            LAYER_STAGING_1_NGS, LAYER_STAGING_2_NGS, LAYER_STAGING_FINAL_NGS,
            # Полигоны - Без_Меж (без 2 этапа!)
            LAYER_STAGING_1_BEZ_MEZH, LAYER_STAGING_FINAL_BEZ_MEZH,
            # Точки - Раздел
            LAYER_STAGING_POINTS_1_RAZDEL, LAYER_STAGING_POINTS_2_RAZDEL,
            LAYER_STAGING_POINTS_FINAL_RAZDEL,
            # Точки - НГС
            LAYER_STAGING_POINTS_1_NGS, LAYER_STAGING_POINTS_2_NGS,
            LAYER_STAGING_POINTS_FINAL_NGS,
            # Примечание: Без_Меж НЕ имеет точечных слоёв!
        ]

        for layer_name in all_layer_names:
            layers = project.mapLayersByName(layer_name)
            if not layers:
                continue

            layer = layers[0]
            if not layer.isValid():
                continue

            style_manager.apply_qgis_style(layer, layer_name)
            label_manager.apply_labels(layer, layer_name)
            layer.triggerRepaint()

        log_info("F_3_4: Стили и подписи применены")

    def _convert_value_for_ogr(self, value: Any, field_type: int) -> Any:
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
            log_warning(f"F_3_4: Не удалось конвертировать значение '{value}' "
                       f"(тип {type(value).__name__}) для OGR: {e}")
            return str(value) if field_type == ogr.OFTString else None
