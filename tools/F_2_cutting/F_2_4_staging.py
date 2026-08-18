# -*- coding: utf-8 -*-
"""
F_2_4_Этапность - Формирование этапов кадастровых работ

Создаёт многоэтапную структуру нарезки для площадных объектов (ОКС):
- 1 этап: Первоначальный раздел (копия из F_2_3 с привязкой к ЗПР)
- 2 этап: Объединение контуров по границам ЗПР
- Итог: Финальные контуры соответствующие конфигурации ЗПР

Логика работы:
1. Копирует слои нарезки из F_2_3 в слои 1 этапа
2. Анализирует соответствие участков контурам ЗПР (intersection area >= 95%)
3. Присваивает ID:
   - Соответствующие ЗПР: ID = ID контура ЗПР
   - Не соответствующие: ID = 100+ (следующий разряд от max контуров ЗПР)
4. Объединяет участки с одинаковым ID по ЗПР во 2 этапе
5. Формирует итоговый слой из 1 этапа (без объединённых) + результаты 2 этапа
"""

from typing import Optional, Dict, Any, TYPE_CHECKING

from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import Qgis, QgsVectorLayer

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.managers import registry
from Daman_QGIS.constants import (
    PLUGIN_NAME, MESSAGE_SUCCESS_DURATION,
    # Исходные слои нарезки (после F_2_3)
    LAYER_CUTTING_OKS_RAZDEL, LAYER_CUTTING_OKS_NGS,
    LAYER_CUTTING_POINTS_OKS_RAZDEL, LAYER_CUTTING_POINTS_OKS_NGS,
    # Слой Без_Меж (после F_2_2, без точек)
    LAYER_CUTTING_OKS_BEZ_MEZH,
    # ЗПР ОКС
    LAYER_ZPR_OKS,
    # Слои этапности - полигоны
    LAYER_STAGING_1_RAZDEL, LAYER_STAGING_1_NGS,
    LAYER_STAGING_1_BEZ_MEZH,
    LAYER_STAGING_2_RAZDEL, LAYER_STAGING_2_NGS,
    LAYER_STAGING_FINAL_RAZDEL, LAYER_STAGING_FINAL_NGS,
    LAYER_STAGING_FINAL_BEZ_MEZH,
    # Слои этапности - точки
    LAYER_STAGING_POINTS_1_RAZDEL, LAYER_STAGING_POINTS_1_NGS,
    LAYER_STAGING_POINTS_2_RAZDEL, LAYER_STAGING_POINTS_2_NGS,
    LAYER_STAGING_POINTS_FINAL_RAZDEL, LAYER_STAGING_POINTS_FINAL_NGS
)
from Daman_QGIS.utils import log_info, log_warning, log_error

# Импорт менеджеров
from Daman_QGIS.managers import (
    PointNumberingManager, VRIAssignmentManager,
    WorkTypeAssignmentManager, LayerType,
    OksZuAnalysisManager
)

from Daman_QGIS.managers.geometry.submodules.Msm_26_2_attribute_mapper import Msm_26_2_AttributeMapper
from .submodules.Fsm_2_1_5_kk_matcher import Fsm_2_1_5_KKMatcher
from .submodules.Fsm_2_1_6_point_layer_creator import Fsm_2_1_6_PointLayerCreator
from .submodules.Fsm_2_4_1_layer_writer import Fsm_2_4_1_LayerWriter
from .submodules.Fsm_2_4_3_point_numbering import Fsm_2_4_3_PointNumbering
from .submodules.Fsm_2_4_4_point_writer import Fsm_2_4_4_PointWriter
from .submodules.Fsm_2_4_5_finisher import Fsm_2_4_5_Finisher
from .submodules.Fsm_2_4_6_source_provider import Fsm_2_4_6_SourceProvider
from .submodules.Fsm_2_4_7_zpr_analyzer import Fsm_2_4_7_ZprAnalyzer
from .submodules.Fsm_2_4_8_geocoder import Fsm_2_4_8_Geocoder
from .submodules.Fsm_2_4_9_stage_builder import Fsm_2_4_9_StageBuilder
from .submodules.Fsm_2_4_10_stage2_builder import Fsm_2_4_10_Stage2Builder
from .submodules.Fsm_2_4_11_bez_mezh_staging import Fsm_2_4_11_BezMezhStaging

if TYPE_CHECKING:
    from Daman_QGIS.managers import LayerManager


class F_2_4_Staging(BaseTool):
    """Инструмент формирования этапности кадастровых работ"""

    # Порог совпадения площади пересечения с ЗПР (95%)
    # Поднят с 80% до 95% после рефактора Msm_26_1 (GEOS OverlayNG gridSize=0.001):
    # геометрия Раздела теперь deterministic без sub-mm slivers, и пересечение ЗУ
    # со "своим" ЗПР близко к 100%. Threshold 95% отлавливает ЗУ, у которых
    # геометрия "уехала" из ЗПР более чем на 5% площади.
    ZPR_MATCH_THRESHOLD = 0.95

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
        self._attribute_mapper: Optional[Msm_26_2_AttributeMapper] = None
        self._kk_matcher: Optional[Fsm_2_1_5_KKMatcher] = None
        self._vri_manager: Optional[VRIAssignmentManager] = None
        self._work_type_manager: Optional[WorkTypeAssignmentManager] = None
        self._point_layer_creator: Optional[Fsm_2_1_6_PointLayerCreator] = None
        self._oks_zu_manager: Optional[OksZuAnalysisManager] = None
        self._gpkg_path: Optional[str] = None
        self._layer_writer: Optional[Fsm_2_4_1_LayerWriter] = None
        self._point_numbering: Optional[Fsm_2_4_3_PointNumbering] = None
        self._point_writer: Optional[Fsm_2_4_4_PointWriter] = None
        self._finisher: Optional[Fsm_2_4_5_Finisher] = None
        self._source_provider: Optional[Fsm_2_4_6_SourceProvider] = None
        self._zpr_analyzer: Optional[Fsm_2_4_7_ZprAnalyzer] = None
        self._geocoder: Optional[Fsm_2_4_8_Geocoder] = None
        self._stage_builder: Optional[Fsm_2_4_9_StageBuilder] = None
        self._stage2_builder: Optional[Fsm_2_4_10_Stage2Builder] = None
        self._bez_mezh_staging: Optional[Fsm_2_4_11_BezMezhStaging] = None

    def set_plugin_dir(self, plugin_dir: str) -> None:
        """Установка пути к папке плагина"""
        self.plugin_dir = plugin_dir

    def set_layer_manager(self, layer_manager: 'LayerManager') -> None:
        """Установка менеджера слоёв"""
        self.layer_manager = layer_manager

    @staticmethod
    def get_name() -> str:
        """Имя инструмента для cleanup"""
        return "F_2_4_Этапность"

    def run(self) -> None:
        """Основной метод запуска инструмента (без диалога)"""
        log_info("F_2_4: Запуск формирования этапности")

        # Проверка открытого проекта
        if not self.check_project_opened():
            return

        # Автоматическая очистка слоев перед выполнением
        self.auto_cleanup_layers()

        # Выполняем формирование этапности
        self._execute()

    def _execute(self) -> None:
        """Основная логика формирования этапности"""
        log_info("F_2_4: Начало формирования этапности")

        # 1. Инициализация
        if not self._initialize():
            return

        # 1.1. Проверка типа объекта - этапность только для площадных
        if not self._check_object_type():
            return

        # 2. Проверка наличия исходных слоёв (после F_2_3)
        source_layers = self._source_provider.get_source_layers()

        # Слой присутствует, но не читается — этапность по неполному набору
        # даёт дыру в покрытии ЗПР, поэтому прогон прекращается (fail-closed)
        if self._source_provider.broken_layers:
            broken_str = "\n".join(f"- {name}" for name in self._source_provider.broken_layers)
            log_error(
                f"F_2_4: нечитаемые слои нарезки: "
                f"{', '.join(self._source_provider.broken_layers)}"
            )
            QMessageBox.critical(
                None, PLUGIN_NAME,
                f"Слои нарезки присутствуют в проекте, но не читаются:\n\n{broken_str}\n\n"
                "Этапность по неполному набору не строится. Переоткройте проект "
                "или пересоздайте нарезку через F_2_1."
            )
            return

        if not source_layers:
            # Причина выхода обязана быть в логе: пользователь видит диалог,
            # а разбор постфактум идёт по журналу
            log_warning(
                "F_2_4: ни одного слоя нарезки не найдено — этапность не строится"
            )
            QMessageBox.warning(
                None, PLUGIN_NAME,
                "Не найдены слои нарезки.\n\n"
                "Сначала выполните нарезку через F_2_1 и корректировку через F_2_3."
            )
            return

        # 2.1. Валидация структуры полей исходных слоёв
        missing_fields = self._source_provider.validate_source_layer_fields(source_layers)
        if missing_fields:
            fields_str = ", ".join(missing_fields)
            log_warning(
                f"F_2_4: устаревшая структура слоёв нарезки, отсутствуют поля: {fields_str}"
            )
            QMessageBox.warning(
                None, PLUGIN_NAME,
                f"Устаревшая структура слоёв нарезки.\n\n"
                f"Отсутствуют поля: {fields_str}\n\n"
                f"Пересоздайте нарезку через F_2_1 для обновления структуры."
            )
            return

        # 3. Загрузка слоя ЗПР_ОКС
        zpr_layer = self._source_provider.get_zpr_layer()
        if not zpr_layer:
            # Причина (отсутствует / сломан провайдер / пуст) — в журнале Fsm_2_4_6
            log_warning(f"F_2_4: слой ЗПР ({LAYER_ZPR_OKS}) непригоден для этапности")
            QMessageBox.warning(
                None, PLUGIN_NAME,
                f"Слой ЗПР_ОКС ({LAYER_ZPR_OKS}) недоступен или пуст.\n\n"
                "Причина указана в журнале. Загрузите слой ЗПР перед запуском этапности."
            )
            return

        # 4. Валидация ВРИ в слое ЗПР (только логирование, без GUI)
        if self._vri_manager:
            is_valid, errors = self._vri_manager.validate_zpr_vri(zpr_layer)
            if not is_valid:
                for error in errors:
                    log_warning(f"F_2_4: Валидация ВРИ: {error}")
                # Продолжаем выполнение - ВРИ будет установлено как "-"

        # 5. Получение максимального ID контуров ЗПР
        # Нецелый ID делает пространство ID неоднозначным — прогон прекращается
        try:
            max_zpr_id = self._zpr_analyzer.get_max_zpr_id(zpr_layer)
        except ValueError as e:
            log_error(f"F_2_4: {e}")
            QMessageBox.critical(
                None, PLUGIN_NAME,
                f"Слой {zpr_layer.name()} не соответствует схеме.\n\n{e}\n\n"
                "Исправьте тип поля ID (целое число) и повторите."
            )
            return
        # Промежуточные продолжают нумерацию ЗПР (например, 83 ЗПР → промежуточные с 84)
        next_id_base = max_zpr_id + 1
        log_info(f"F_2_4: Макс. ID ЗПР = {max_zpr_id}, "
                f"ID для несоответствующих участков начинается с {next_id_base}")

        # 5. Обработка каждого типа слоёв (Раздел, НГС)
        for mapping in self.LAYER_MAPPING:
            (source_poly, source_points,
             stage1_poly, stage1_points,
             stage2_poly, stage2_points,
             final_poly, final_points,
             layer_type) = mapping

            if source_poly not in source_layers:
                log_warning(
                    f"F_2_4: слоя {source_poly} нет в наборе (отсутствует в проекте "
                    f"либо пуст) — этап по этой ветке не строится"
                )
                continue

            source_layer = source_layers[source_poly]
            log_info(f"F_2_4: Обработка слоя {source_poly} ({layer_type})")

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
        self._finisher.apply_styles_and_labels()

        # 8. Сортировка слоёв
        if self.layer_manager:
            self.layer_manager.sort_all_layers()
            log_info("F_2_4: Слои отсортированы")

        # 9. Валидация минимальных площадей
        self._finisher.validate_min_areas()

        # 10. Завершение
        log_info("F_2_4: Формирование этапности завершено")
        self.iface.messageBar().pushMessage(
            PLUGIN_NAME,
            "Этапность сформирована успешно",
            level=Qgis.Success,
            duration=MESSAGE_SUCCESS_DURATION
        )

    def _initialize(self) -> bool:
        """Инициализация компонентов"""
        if not self.plugin_dir:
            log_error("F_2_4: Не установлен путь к плагину (plugin_dir)")
            return False

        self._attribute_mapper = Msm_26_2_AttributeMapper(self.plugin_dir)

        structure_manager = registry.get('M_19')
        self._gpkg_path = structure_manager.get_gpkg_path(create=False)
        if not self._gpkg_path:
            log_error("F_2_4: Не найден путь к project.gpkg")
            return False

        self._point_layer_creator = Fsm_2_1_6_PointLayerCreator(self._gpkg_path)

        # Писатель полигональных слоёв этапности (Fsm_2_4_1)
        self._layer_writer = Fsm_2_4_1_LayerWriter(self._gpkg_path, self.layer_manager)

        # Нумерация точек (Fsm_2_4_3), точечные слои (Fsm_2_4_4), завершение (Fsm_2_4_5)
        self._point_numbering = Fsm_2_4_3_PointNumbering()
        self._point_writer = Fsm_2_4_4_PointWriter(
            self._point_layer_creator, self.layer_manager
        )
        self._finisher = Fsm_2_4_5_Finisher(self.plugin_dir)

        # Источники (Fsm_2_4_6), анализ ЗПР (Fsm_2_4_7), геокодер адреса (Fsm_2_4_8)
        self._source_provider = Fsm_2_4_6_SourceProvider(self.LAYER_MAPPING)
        self._zpr_analyzer = Fsm_2_4_7_ZprAnalyzer(self.ZPR_MATCH_THRESHOLD)
        self._geocoder = Fsm_2_4_8_Geocoder()

        # Инициализируем KKMatcher для привязки 2 этапа к КК.
        # Слой кварталов без поля кадастрового номера — отказ: без привязки
        # контуры 2 этапа получили бы условные номера не того квартала
        kk_layer = self._source_provider.get_kk_layer()
        if kk_layer:
            try:
                self._kk_matcher = Fsm_2_1_5_KKMatcher(kk_layer)
            except ValueError as e:
                log_error(f"F_2_4: {e}")
                QMessageBox.critical(
                    None, PLUGIN_NAME,
                    f"Слой кадастровых кварталов непригоден для привязки.\n\n{e}"
                )
                return False
        else:
            # Без слоя кварталов все контуры 2 этапа получили бы КН и Услов_КН
            # «-»: прогон завершился бы «успешно» с пустыми условными номерами
            log_error(
                "F_2_4: слой Выборка_КК недоступен — контуры 2 этапа остались бы "
                "без кадастровых кварталов. Этапность остановлена."
            )
            QMessageBox.critical(
                None, PLUGIN_NAME,
                "Слой кадастровых кварталов недоступен.\n\n"
                "Без него контуры 2 этапа не получают условные кадастровые номера."
            )
            return False

        # Инициализируем VRIManager для присвоения ВРИ в итоговом слое
        self._vri_manager = VRIAssignmentManager(self.plugin_dir)

        # Инициализируем WorkTypeManager для присвоения Вид_Работ
        self._work_type_manager = WorkTypeAssignmentManager(self.plugin_dir)

        # Инициализируем OksZuAnalysisManager для пересчёта ОКС на 2 этапе
        self._oks_zu_manager = OksZuAnalysisManager()

        # Построители данных этапов (Fsm_2_4_9, Fsm_2_4_10) и ветка Без_Меж (Fsm_2_4_11)
        self._stage_builder = Fsm_2_4_9_StageBuilder(self._vri_manager)
        self._stage2_builder = Fsm_2_4_10_Stage2Builder(
            self._attribute_mapper, self._kk_matcher,
            self._geocoder, self._oks_zu_manager
        )
        self._bez_mezh_staging = Fsm_2_4_11_BezMezhStaging(
            self._layer_writer, self._vri_manager, self._work_type_manager
        )

        return True

    def _check_object_type(self) -> bool:
        """Проверка типа объекта - этапность только для площадных"""
        from Daman_QGIS.database.project_db import ProjectDB

        try:
            from Daman_QGIS.managers.core.M_1_project_manager import ProjectManager

            db = ProjectDB(self._gpkg_path)
            settings = db.load_project_settings()

            if ProjectManager.is_linear_object(settings):
                log_info("F_2_4: Тип объекта - линейный, этапность недоступна")
                QMessageBox.warning(
                    None, PLUGIN_NAME,
                    "Этапность только для площадных объектов.\n\n"
                    "Текущий проект имеет тип объекта: линейный."
                )
                return False

            log_info("F_2_4: Тип объекта - площадной, продолжаем")
            return True
        except Exception as e:
            # Fail-closed: неподтверждённый тип объекта не даёт права на прогон
            log_error(f"F_2_4: тип объекта не подтверждён: {e}")
            QMessageBox.critical(
                None, PLUGIN_NAME,
                "Не удалось подтвердить тип объекта проекта.\n\n"
                "Проверьте настройки проекта (F_0_3_Редактирование проекта)."
            )
            return False

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
        log_info(f"F_2_4: Обработка этапности для {layer_type}")

        # Специальная обработка для Без_Меж (без точек и 2 этапа)
        if layer_type == 'BEZ_MEZH':
            self._bez_mezh_staging.process_bez_mezh_staging(
                source_layer=source_layer,
                zpr_layer=zpr_layer,
                stage1_name=stage1_name,
                final_name=final_name
            )
            return

        # 1. Анализ соответствия участков контурам ЗПР
        # feature_zpr_mapping: {feature_id: zpr_id}
        # features_by_zpr: {zpr_id: [feature_ids]}
        # ID контуров ЗПР уже проверены вахтёром в _execute (get_max_zpr_id
        # прошёл весь слой) — повторная обработка ValueError здесь не нужна
        feature_zpr_mapping, features_by_zpr = self._zpr_analyzer.analyze_zpr_matching(
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

        log_info(f"F_2_4: Соответствуют ЗПР: {len(matching_features)}, "
                f"требуют объединения: {len(merging_features)}")

        # 3. Формирование данных для 1 этапа
        stage1_data = self._stage_builder.prepare_stage1_data(
            source_layer, feature_zpr_mapping, matching_features,
            merging_features, next_id_base
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

        # 4. Формирование данных для 2 этапа (только объединяемые участки)
        # Передаём stage1_data чтобы получить правильные ID (100, 101...) для Состав_контуров
        # _prepare_stage2_data зависит только от геометрий и attrs.ID stage1 —
        # нумерация точек на этом шаге ещё не нужна
        stage2_data, merged_contours_info = self._stage2_builder.prepare_stage2_data(
            source_layer, feature_zpr_mapping, features_by_zpr,
            merging_features, stage1_data
        )

        # 4.1. Присвоение Вид_Работ для 2 этапа (с указанием объединённых ID)
        if stage2_data and self._work_type_manager:
            lt = LayerType.RAZDEL if layer_type == 'RAZDEL' else LayerType.NGS
            stage2_data = self._work_type_manager.assign_work_type_stage2(
                stage2_data, lt, zpr_layer
            )

        # 4.2. Присвоение План_ВРИ и Общая_земля для 2 этапа (самодостаточность
        # слоя Этап-2). assign_work_type_stage2 заполняет только План_ВРИ (fallback
        # из ЗПР), но НЕ Общая_земля — её ставит только assign_vri_to_features.
        # Без этого вызова слой Этап-2 имел бы пустую Общая_земля у объединённых
        # контуров (расхождение с прежним слоем Итог, где ВРИ присваивался всем).
        # Вызывается ПОСЛЕ assign_work_type_stage2 и ДО создания слоя Этап-2 —
        # последнее слово за полным присвоением План_ВРИ+Общая_земля.
        if stage2_data and self._vri_manager:
            stage2_data = self._vri_manager.assign_vri_to_features(
                zpr_layer, stage2_data, zpr_id_key='zpr_id'
            )

        # 5. ЕДИНАЯ нумерация точек merged(stage1+stage2): единое пространство
        # номеров — контуры обоих этапов по возрастанию ID (интерливинг),
        # общие координаты этапов наследуют номер. РОВНО ОДИН вызов на тип слоя:
        # повторный вызов на том же менеджере сбросил бы счётчик (auto_reset)
        # и этапы снова стали бы независимыми.
        for item in stage1_data:
            item['stage'] = 1
        for item in stage2_data:
            item['stage'] = 2
        merged_data = stage1_data + stage2_data

        point_numbering = PointNumberingManager()
        # Контур без номеров точек уходит в координатный перечень неполным,
        # поэтому отказ нумерации останавливает прогон, а не даёт прочерк
        try:
            merged_data, points_data = self._point_numbering.number_points(
                merged_data, point_numbering
            )
        except RuntimeError as e:
            log_error(f"F_2_4: {e}")
            QMessageBox.critical(
                None, PLUGIN_NAME,
                f"Нумерация характерных точек отказала для «{layer_type}».\n\n{e}\n\n"
                "Проверьте геометрию контуров и повторите."
            )
            return

        # 5.1. Раскладка points_data по этапам через contour_id.
        # Уникальность contour_id в merged гарантирована логикой (matching ∩ merged
        # zpr_id = пусто, промежуточные > max_zpr_id) — defensive-проверка ниже
        # страхует будущие правки fallback-веток (не silent).
        stage_by_contour: Dict[Any, int] = {}
        for item in merged_data:
            cid = item.get('contour_id')
            existing_stage = stage_by_contour.get(cid)
            item_stage = item.get('stage', 1)
            if existing_stage is not None and existing_stage != item_stage:
                log_error(
                    f"F_2_4: Дубликат contour_id={cid} между этапами "
                    f"({existing_stage} и {item_stage}) — раскладка точек по "
                    f"Т-слоям может быть неверной, проверьте поле ID слоя ЗПР"
                )
            stage_by_contour[cid] = item_stage

        stage1_points = [p for p in points_data if stage_by_contour.get(p.get('contour_id')) == 1]
        stage2_points = [p for p in points_data if stage_by_contour.get(p.get('contour_id')) == 2]

        # 6. Создание слоя 1 этапа
        stage1_layer = self._layer_writer.create_staging_layer(
            stage1_name, source_layer.crs(), source_layer.fields(),
            stage1_data, add_merged_field=False
        )

        # 7. Создание точечного слоя 1 этапа
        if stage1_points_name:
            self._point_writer.create_points_layer(stage1_points, stage1_points_name, source_layer.crs())

        if stage2_data:
            # 8. Создание слоя 2 этапа с дополнительным полем "Состав_контуров"
            # Поле добавляется в _create_staging_layer когда add_merged_field=True
            if stage2_name:
                stage2_layer = self._layer_writer.create_staging_layer(
                    stage2_name, source_layer.crs(), source_layer.fields(),
                    stage2_data, add_merged_field=True
                )

            # 9. Создание точечного слоя 2 этапа
            if stage2_points_name:
                self._point_writer.create_points_layer(stage2_points, stage2_points_name, source_layer.crs())
        else:
            log_info(f"F_2_4: Нет данных для 2 этапа ({layer_type})")

        # 11. Формирование итогового слоя (с полем Этап, Состав_контуров и ВРИ)
        # Итого = ВСЕ контуры 1 этапа + ВСЕ контуры 2 этапа
        # ВАЖНО: stage1_data и stage2_data уже содержат обновлённое поле "Точки"
        # Неполный Итог не создаётся: контур, выпавший из объединения, ушёл бы
        # в ведомость дырой в покрытии ЗПР
        try:
            final_data = self._stage_builder.prepare_final_data(
                stage1_data, stage2_data, zpr_layer
            )
        except RuntimeError as e:
            log_error(f"F_2_4: {e}")
            QMessageBox.critical(
                None, PLUGIN_NAME,
                f"Итоговый слой не сформирован для «{layer_type}».\n\n{e}\n\n"
                "Проверьте геометрию контуров этой зоны ЗПР и повторите."
            )
            return

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
        final_layer = self._layer_writer.create_staging_layer(
            final_name, source_layer.crs(), source_layer.fields(),
            final_data,
            add_merged_field=True,  # Добавляем поле Состав_контуров
            add_stage_field=True    # Добавляем поле Этап перед ID
        )

        # 13. Создание итогового точечного слоя (§4.3): из отфильтрованного
        # points_data, НЕ копированием фич слоёв по имени.
        # Финальные точки = точки stage1 БЕЗ точек временных контуров + точки stage2.
        # ИНВАРИАНТ ФИЛЬТРА (§7): удаляем точку СТРОГО по contour_id ∈ множество
        # НАЗНАЧЕННЫХ ID временных (item['attributes']['ID'], НЕ сырой merging_features
        # = feature.id() OGR fid — другое пространство). Координатный фильтр запрещён
        # (выкинул бы граничные точки matching-контуров).
        if final_points_name:
            temp_ids = {
                item['attributes']['ID']
                for item in stage1_data
                if item.get('is_temporary')
            }
            final_points = [
                p for p in stage1_points if p.get('contour_id') not in temp_ids
            ] + stage2_points
            self._point_writer.create_final_points_layer(
                final_points,
                final_points_name,
                source_layer.crs(),
                stage_by_contour
            )

        log_info(f"F_2_4: Этапность для {layer_type} завершена: "
                f"1 этап={len(stage1_data)}, 2 этап={len(stage2_data)}, "
                f"итог={len(final_data)}")




