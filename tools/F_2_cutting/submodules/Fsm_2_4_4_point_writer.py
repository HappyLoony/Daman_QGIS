# -*- coding: utf-8 -*-
"""
Fsm_2_4_4_PointWriter - Создание точечных слоёв этапности

НАЗНАЧЕНИЕ:
    Создание слоёв Т_* из готовых пронумерованных точек (формат M_20) и сборка
    итогового точечного слоя с полем "Этап".

ОСОБЕННОСТИ:
    - Старый одноимённый слой удаляется из проекта перед созданием.
    - Итоговый слой строится из отфильтрованного среза точек, а не копированием
      фич слоёв Т_Этап по имени.
    - Поле "Этап" добавляется после создания: базовая схема Fsm_2_1_6 его не несёт.

ИСПОЛЬЗОВАНИЕ:
    Вызывается F_2_4_Staging для точечных слоёв 1 этапа, 2 этапа и Итога.
"""

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from qgis.core import QgsProject, QgsVectorLayer, QgsField
from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.utils import log_info, log_warning, log_error, commit_or_rollback

if TYPE_CHECKING:
    from Daman_QGIS.managers import LayerManager
    from .Fsm_2_1_6_point_layer_creator import Fsm_2_1_6_PointLayerCreator


class Fsm_2_4_4_PointWriter:
    """Создание точечных слоёв этапности"""

    def __init__(
        self,
        point_layer_creator: Optional['Fsm_2_1_6_PointLayerCreator'] = None,
        layer_manager: Optional['LayerManager'] = None
    ) -> None:
        """Инициализация писателя точечных слоёв

        Args:
            point_layer_creator: Создатель точечных слоёв (Fsm_2_1_6)
            layer_manager: Менеджер слоёв для подключения результата к проекту
        """
        self._point_layer_creator = point_layer_creator
        self.layer_manager = layer_manager

    def create_points_layer(
        self,
        points_data: List[Dict[str, Any]],
        points_layer_name: str,
        crs: Any
    ) -> None:
        """Создание точечного слоя из уже пронумерованных точек

        Args:
            points_data: Список точек (срез merged points_data по этапу,
                        формат M_20.process_polygon_layer)
            points_layer_name: Имя создаваемого точечного слоя
            crs: Система координат
        """
        if not self._point_layer_creator:
            return

        if not points_data:
            log_warning(f"Fsm_2_4_4: Нет данных точек для слоя {points_layer_name}")
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
            log_info(f"Fsm_2_4_4: Создан точечный слой {points_layer_name} "
                    f"({points_layer.featureCount()} точек)")

    def create_final_points_layer(
        self,
        final_points: List[Dict[str, Any]],
        final_points_name: str,
        crs: Any,
        stage_by_contour: Dict[Any, int]
    ) -> None:
        """Создание итогового точечного слоя из отфильтрованного points_data (§4.3)

        Строит Т_Итог напрямую из уже пронумерованных точек merged-пространства,
        НЕ копированием фич слоёв Т_Этап по имени. Финальные точки формирует
        caller: точки stage1 БЕЗ точек временных контуров + точки stage2.

        Единое пространство номеров (нумерация merged stage1+stage2): общая
        координата этапов представлена ДВУМЯ фичами (по одной на контур каждого
        этапа) с ОДИНАКОВЫМ номером — инвариант «дубль = та же точка, тот же
        номер». Конфликт «одна координата, разные номера» невозможен by
        construction. Номера НЕ пересчитываются.

        Поле «Этап» (вариант B, §4.3/NEW-A): базовая схема точечного слоя
        (Fsm_2_1_6, 9 полей) поля «Этап» не содержит, points_data ключа `stage`
        не несёт. Поэтому поле «Этап» добавляется ПОСЛЕ создания слоя через
        dataProvider().addAttributes и заполняется по ID_Контура -> stage
        (stage_by_contour). Общий Fsm_2_1_6 не трогаем (используется F_2_3/F_2_4/
        Fsm_2_7_2). Поле сохраняется ради data-паритета с прежним поведением
        (стили/подписи/экспорт его не читают).

        Args:
            final_points: Отфильтрованные точки (merged points_data формата M_20)
            final_points_name: Имя итогового точечного слоя
            crs: Система координат
            stage_by_contour: Маппинг contour_id -> номер этапа (1|2)
        """
        qgs_layer: Optional[QgsVectorLayer] = None
        try:
            if not final_points:
                log_warning(
                    f"Fsm_2_4_4: Нет точек для итогового точечного слоя {final_points_name}"
                )
                return

            # 1. Создаём базовый точечный слой из отфильтрованных точек.
            # _create_points_layer_from_data сам удаляет старый слой и добавляет
            # новый в проект (схема Fsm_2_1_6, без поля «Этап»).
            self.create_points_layer(
                final_points, final_points_name, crs
            )

            # 2. Получаем созданный слой для добавления поля «Этап» (вариант B).
            project = QgsProject.instance()
            layers = project.mapLayersByName(final_points_name)
            if layers and isinstance(layers[0], QgsVectorLayer):
                qgs_layer = layers[0]

            if qgs_layer is None or not qgs_layer.isValid():
                log_error(
                    f"Fsm_2_4_4: Итоговый точечный слой {final_points_name} не найден "
                    f"после создания — поле «Этап» не добавлено"
                )
                return

            # 3. Добавляем поле «Этап» (если ещё нет — идемпотентность на реран).
            if qgs_layer.fields().indexFromName("Этап") < 0:
                provider = qgs_layer.dataProvider()
                if not provider.addAttributes([QgsField("Этап", QMetaType.Type.Int)]):
                    log_error(
                        f"Fsm_2_4_4: Не удалось добавить поле «Этап» в слой "
                        f"{final_points_name}"
                    )
                    return
                qgs_layer.updateFields()

            # 4. Заполняем «Этап» по ID_Контура -> stage_by_contour.
            stage_idx = qgs_layer.fields().indexFromName("Этап")
            contour_idx = qgs_layer.fields().indexFromName("ID_Контура")
            if stage_idx < 0 or contour_idx < 0:
                log_error(
                    f"Fsm_2_4_4: В слое {final_points_name} нет полей «Этап»/«ID_Контура» "
                    f"для заполнения этапа"
                )
                return

            if not qgs_layer.startEditing():
                log_error(
                    f"Fsm_2_4_4: Не удалось начать редактирование слоя {final_points_name} "
                    f"для заполнения «Этап»"
                )
                return

            filled = 0
            for feature in qgs_layer.getFeatures():
                contour_id = feature.attribute(contour_idx)
                stage_value = stage_by_contour.get(contour_id)
                if stage_value is not None:
                    qgs_layer.changeAttributeValue(feature.id(), stage_idx, stage_value)
                    filled += 1

            if not commit_or_rollback(qgs_layer, "Fsm_2_4_4"):
                log_error(
                    f"Fsm_2_4_4: Не удалось сохранить поле «Этап» в слое "
                    f"{final_points_name}"
                )
                return

            log_info(
                f"Fsm_2_4_4: Создан итоговый точечный слой {final_points_name} "
                f"({qgs_layer.featureCount()} точек, «Этап» заполнен у {filled})"
            )

        except Exception as e:
            log_error(f"Fsm_2_4_4: Ошибка создания итогового точечного слоя: {e}")
            import traceback
            log_error(traceback.format_exc())

        finally:
            # Успешный путь закрывает сессию через commit_or_rollback выше. Исключение
            # в цикле заполнения «Этап» оставляло бы слой project.gpkg в режиме
            # редактирования — соседние слои того же файла читаются пустыми.
            if qgs_layer is not None and qgs_layer.isEditable():
                if not qgs_layer.rollBack():
                    log_error(
                        f"Fsm_2_4_4: откат не выполнен, слой {final_points_name} "
                        f"остался в режиме редактирования"
                    )
