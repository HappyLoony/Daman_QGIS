# -*- coding: utf-8 -*-
"""
Экспортер в формат DXF с поддержкой стилей AutoCAD.
Обеспечивает полную совместимость со стилями AutoCAD.

АРХИТЕКТУРА:
Этот файл является КООРДИНАТОРОМ, делегирующим работу специализированным субмодулям:
- Fsm_dxf_5_layer_utils: утилиты для работы со слоями и стилями
- Fsm_dxf_4_hatch_manager: управление штриховками
- Fsm_dxf_3_label_exporter: экспорт подписей (MTEXT)
- Fsm_dxf_2_geometry_exporter: экспорт простой геометрии (без блоков)
- Fsm_dxf_1_block_exporter: экспорт блоков с атрибутами (ЗУ, ОКС, ЗОУИТ)
"""

from typing import Optional, List, Dict, Any
import ezdxf
from ezdxf import units
from ezdxf.filemanagement import new as ezdxf_new
import os

from qgis.core import (
    QgsVectorLayer, QgsProject,
    QgsCoordinateTransform
)
from qgis.PyQt.QtCore import QObject, pyqtSignal
from .base_exporter import BaseExporter

from Daman_QGIS.constants import PLUGIN_NAME, PRECISION_DECIMALS, PRECISION_DECIMALS_WGS84
from Daman_QGIS.utils import log_info, log_warning, log_error, log_debug
from Daman_QGIS.database.project_db import ProjectDB

# Импортируем субмодули
from .dxf.Fsm_dxf_5_layer_utils import DxfLayerUtils
from .dxf.Fsm_dxf_4_hatch_manager import DxfHatchManager
from .dxf.Fsm_dxf_3_label_exporter import DxfLabelExporter
from .dxf.Fsm_dxf_2_geometry_exporter import DxfGeometryExporter
from .dxf.Fsm_dxf_1_block_exporter import DxfBlockExporter


class DxfExporter(BaseExporter):
    """
    Координатор экспорта в DXF с поддержкой стилей AutoCAD

    Делегирует специализированные задачи субмодулям:
    - Layer Utils: информация о слоях, стили, типы линий
    - Hatch Manager: штриховки полигонов
    - Label Exporter: подписи как MTEXT
    - Geometry Exporter: простая геометрия (границы, буферы, и т.д.)
    - Block Exporter: блоки с атрибутами (ЗУ, ОКС, ЗОУИТ)
    """

    def __init__(self, iface=None, style_manager=None):
        """
        Инициализация экспортера

        Args:
            iface: Интерфейс QGIS
            style_manager: Менеджер стилей AutoCAD
        """
        super().__init__(iface)
        self.style_manager = style_manager

        # Инициализация reference managers для доступа к Base_labels.json и Base_layers.json
        from Daman_QGIS.managers import get_reference_managers
        self.ref_managers = get_reference_managers()

        # === ИНИЦИАЛИЗАЦИЯ СУБМОДУЛЕЙ ===
        self.hatch_manager = DxfHatchManager()
        self.label_exporter = DxfLabelExporter()
        self.layer_utils = DxfLayerUtils(self.ref_managers, self.style_manager)
        self.geometry_exporter = DxfGeometryExporter(
            hatch_manager=self.hatch_manager,
            label_exporter=self.label_exporter,
            ref_managers=self.ref_managers
        )
        self.block_exporter = DxfBlockExporter(
            hatch_manager=self.hatch_manager,
            label_exporter=self.label_exporter,
            ref_managers=self.ref_managers
        )

        # Масштабный коэффициент для подписей AutoCAD (вычисляется при экспорте)
        self._label_scale_factor: float = 1.0

    def export_layers(self,
                     layers: List[QgsVectorLayer],
                     output_folder: Optional[str] = None,
                     target_crs=None,
                     export_settings: Optional[Dict[str, Any]] = None,
                     **params) -> Dict[str, bool]:
        """
        Экспорт списка слоев в DXF

        Args:
            layers: Список слоев для экспорта
            output_folder: Папка назначения
            target_crs: Целевая СК (если None, используется СК проекта)
            export_settings: Дополнительные настройки экспорта
            **params: Параметры экспорта (для совместимости с BaseExporter)

        Returns:
            Словарь {layer_name: success}
        """
        if export_settings is None:
            export_settings = {}

        # Логируем информацию о стилях (без остановки экспорта)
        if self.style_manager:
            valid, issues = self.style_manager.validate_project_styles()
            if not valid:
                log_warning("DxfExporter: Некоторые слои используют стиль по умолчанию (красная линия, толщина 1мм):")
                for issue in issues:
                    log_warning(f"DxfExporter:   {issue}")

        # Получаем output_path из params или создаем из output_folder
        output_path: str
        if output_folder is None:
            output_path_param = params.get('output_path')
            if output_path_param is None:
                raise ValueError("Не указан output_folder или output_path")
            output_path = str(output_path_param)
        else:
            output_path = params.get('output_path', os.path.join(output_folder, 'export.dxf'))

        # Создаем DXF документ (версия AC1027 - AutoCAD 2013)
        doc = ezdxf_new('AC1027')

        # Очищаем кэш экспортированных точек (для дедупликации)
        self.geometry_exporter.clear_point_cache()

        # Добавляем текстовый стиль GOST 2.304 для MULTILEADER
        self.layer_utils.add_text_style(doc, 'GOST 2.304', 'gost.shx')

        # Логируем системные слои, созданные автоматически
        initial_layers = [layer.dxf.name for layer in doc.layers]
        log_debug(f"DxfExporter: Системные слои ezdxf: {', '.join(initial_layers)}")

        # Устанавливаем единицы измерения (метры)
        doc.header['$INSUNITS'] = units.M
        doc.header['$MEASUREMENT'] = 1  # Метрическая система

        # Получаем modelspace
        msp = doc.modelspace()

        # Определяем целевую СК
        if not target_crs:
            target_crs = QgsProject.instance().crs()

        # ВАЖНО: Определяем precision на основе целевой СК (СНАЧАЛА, до экспорта!)
        is_wgs84 = target_crs.authid() == "EPSG:4326"
        coordinate_precision = PRECISION_DECIMALS_WGS84 if is_wgs84 else PRECISION_DECIMALS
        log_debug(f"DxfExporter: DXF экспорт: target_crs={target_crs.authid()}, precision={coordinate_precision} знаков")

        # Получаем масштабный коэффициент для подписей AutoCAD
        self._label_scale_factor = self._get_label_scale_factor()

        # Сортируем слои: сначала Defpoints (будет внизу в AutoCAD), потом остальные
        defpoints_layers = []
        other_layers = []

        for layer in layers:
            if not isinstance(layer, QgsVectorLayer):
                continue
            layer_info = self.layer_utils.get_layer_info_from_base(layer.name())
            if layer_info and layer_info.get('layer_name_autocad') == 'Defpoints':
                defpoints_layers.append(layer)
            else:
                other_layers.append(layer)

        # Объединяем: сначала Defpoints, потом остальные
        ordered_layers = defpoints_layers + other_layers
        log_debug(f"DxfExporter: Порядок экспорта: {len(defpoints_layers)} Defpoints слоёв, {len(other_layers)} остальных")

        # Экспортируем каждый слой
        total_features = sum(layer.featureCount() for layer in ordered_layers)
        processed = 0

        for layer in ordered_layers:
            if not isinstance(layer, QgsVectorLayer):
                continue

            # Получаем информацию о слое из Base_layers.json
            layer_info = self.layer_utils.get_layer_info_from_base(layer.name())

            # Определяем имя слоя DXF (из layer_name_autocad или full_name)
            if layer_info and layer_info.get('layer_name_autocad'):
                layer_dxf_name = layer_info['layer_name_autocad']

                # Специальная обработка для "ИМЯ НЕ ЗАДАНО"
                if layer_dxf_name == "ИМЯ НЕ ЗАДАНО":
                    layer_dxf_name = layer.name()
                    log_warning(f"DxfExporter: Слой {layer.name()} не имеет layer_name_autocad, используем full_name")
            else:
                layer_dxf_name = layer.name()
                log_warning(f"DxfExporter: Слой {layer.name()} не найден в Base_layers.json")

            # Получаем стиль AutoCAD для слоя (используем layer_utils)
            autocad_style = self.layer_utils.get_layer_style(layer)
            log_debug(f"DxfExporter: Слой {layer.name()}: autocad_style={autocad_style}")

            # Создаём слой DXF или используем существующий (если уже создан)
            if layer_dxf_name in doc.layers:
                dxf_layer = doc.layers.get(layer_dxf_name)
                log_debug(f"DxfExporter: Слой DXF '{layer_dxf_name}' уже существует, используем его")
            else:
                dxf_layer = doc.layers.add(layer_dxf_name)
                log_debug(f"DxfExporter: Создан слой DXF '{layer_dxf_name}'")

            # Настраиваем цвет слоя
            color_value = autocad_style.get('color', 1)
            if color_value < 0:
                # Отрицательное значение = True Color (24-bit RGB)
                rgb_value = -color_value
                r = (rgb_value >> 16) & 0xFF
                g = (rgb_value >> 8) & 0xFF
                b = rgb_value & 0xFF
                dxf_layer.rgb = (r, g, b)
                log_debug(f"DxfExporter: Слой '{layer_dxf_name}': установлен True Color RGB({r},{g},{b})")
            else:
                # Положительное значение = стандартный AutoCAD color index (1-255)
                dxf_layer.color = color_value
                log_debug(f"DxfExporter: Слой '{layer_dxf_name}': установлен ACI color {color_value}")

            # Настраиваем тип линии (используем layer_utils)
            linetype = autocad_style.get('linetype', 'CONTINUOUS')
            if linetype != 'CONTINUOUS' and linetype not in doc.linetypes:
                self.layer_utils.add_linetype(doc, linetype)
            dxf_layer.dxf.linetype = linetype

            # Настраиваем толщину линии
            lineweight_value = autocad_style.get('lineweight', 100)
            dxf_layer.dxf.lineweight = lineweight_value
            log_debug(f"DxfExporter: Слой '{layer_dxf_name}': установлен lineweight={lineweight_value}")

            # Настраиваем флаг печати
            if layer_info and layer_info.get('not_print') == 1:
                dxf_layer.dxf.plot = 0  # 0 = не печатать
                log_debug(f"DxfExporter: Слой {layer_dxf_name} помечен как непечатаемый (plot=0)")
            else:
                dxf_layer.dxf.plot = 1  # 1 = печатать (по умолчанию)

            # Создаем трансформацию СК если нужно
            crs_transform = None
            if layer.crs() != target_crs:
                crs_transform = QgsCoordinateTransform(
                    layer.crs(),
                    target_crs,
                    QgsProject.instance()
                )

            # === ЭКСПОРТ ОБЪЕКТОВ СЛОЯ ===
            # Определяем нужны ли блоки для этого слоя (используем layer_utils)
            use_blocks = self.layer_utils.should_use_blocks_for_layer(layer.name())

            # Экспортируем объекты слоя
            for feature in layer.getFeatures():
                # Объединяем стили с настройками экспорта
                combined_style = autocad_style.copy()
                if export_settings and 'width' in export_settings:
                    combined_style['width'] = export_settings['width']

                if use_blocks:
                    # Экспорт с блоками (ЗУ, ОКС, ЗОУИТ) - делегируем block_exporter
                    self.block_exporter.export_feature_as_block(
                        feature, layer, layer_dxf_name, doc, msp,
                        crs_transform, combined_style, layer.name(), coordinate_precision,
                        label_scale_factor=self._label_scale_factor
                    )
                else:
                    # Экспорт простой геометрии (все остальные слои) - делегируем geometry_exporter
                    self.geometry_exporter.export_simple_geometry(
                        feature, layer, layer_dxf_name, doc, msp,
                        crs_transform, combined_style, layer.name(), coordinate_precision,
                        label_scale_factor=self._label_scale_factor
                    )

                processed += 1
                self.progress.emit(int(processed * 100 / total_features))

        # === СОЗДАНИЕ СЛОЁВ ПОДПИСЕЙ _Номер ===
        log_debug("DxfExporter: Создание слоёв подписей _Номер...")
        for layer in ordered_layers:
            if not isinstance(layer, QgsVectorLayer):
                continue

            # Получаем информацию о слое
            layer_info = self.layer_utils.get_layer_info_from_base(layer.name())
            if layer_info and layer_info.get('layer_name_autocad'):
                layer_dxf_name = layer_info['layer_name_autocad']
                if layer_dxf_name == "ИМЯ НЕ ЗАДАНО":
                    layer_dxf_name = layer.name()
            else:
                layer_dxf_name = layer.name()

            # Проверяем наличие настроек подписей в Base_labels.json
            label_config = self.ref_managers.label.get_label_config(layer.name())
            # ВАЖНО: создаём слой _Номер ТОЛЬКО если есть label_field И он не равен "-"
            if label_config and label_config.get('label_field') and label_config.get('label_field') != '-':
                # Имя слоя подписей: {layer_name_autocad}_Номер
                label_layer_name = f"{layer_dxf_name}_Номер"
                if label_layer_name not in doc.layers:
                    label_layer = doc.layers.add(label_layer_name)

                    # Получаем цвет из Base_labels.json (label_font_color_RGB)
                    color_rgb_str = label_config.get('label_font_color_RGB', '0,0,0')
                    try:
                        r, g, b = map(int, color_rgb_str.split(','))
                        label_layer.rgb = (r, g, b)
                        log_debug(f"DxfExporter: Создан слой для подписей: {label_layer_name} с цветом RGB({r},{g},{b})")
                    except Exception as e:
                        # Если ошибка парсинга - чёрный цвет по умолчанию
                        label_layer.color = 7
                        log_debug(f"DxfExporter: Создан слой для подписей: {label_layer_name} (цвет по умолчанию)")
                else:
                    log_debug(f"DxfExporter: Слой для подписей {label_layer_name} уже существует")
            else:
                log_debug(f"DxfExporter: Слой {layer.name()} не имеет подписей или label_field='-', слой _Номер не создаётся")

        # Логируем порядок всех слоёв в DXF (для отладки)
        layer_names = [layer.dxf.name for layer in doc.layers]
        log_debug(f"DxfExporter: Порядок слоёв в DXF (до очистки): {', '.join(layer_names)}")

        # Очищаем неиспользуемые слои перед сохранением
        self._cleanup_unused_layers(doc)

        # Сохраняем файл
        doc.saveas(output_path)

        self.message.emit(f"Экспорт завершен: {output_path}")
        log_info(f"DxfExporter: DXF экспортирован: {output_path}")

        return {layer.name(): True for layer in ordered_layers}

    def _cleanup_unused_layers(self, doc) -> None:
        """
        Удаление неиспользуемых слоёв из DXF документа

        Проверяет все слои и удаляет те, на которых нет объектов.
        Системный слой '0' не удаляется (обязательный слой DXF).

        Args:
            doc: DXF документ (ezdxf.document.Drawing)
        """
        from collections import defaultdict

        # Подсчитываем количество объектов на каждом слое
        layer_usage = defaultdict(int)

        # Проверяем modelspace
        msp = doc.modelspace()
        for entity in msp:
            layer_name = entity.dxf.layer
            layer_usage[layer_name] += 1

        # Проверяем все paperspace layouts
        for layout in doc.layouts:
            if layout.name != 'Model':  # Model это modelspace, уже проверили
                for entity in layout:
                    layer_name = entity.dxf.layer
                    layer_usage[layer_name] += 1

        # Проверяем все block definitions
        for block in doc.blocks:
            for entity in block:
                layer_name = entity.dxf.layer
                layer_usage[layer_name] += 1

        # Удаляем неиспользуемые слои
        layers_to_remove = []
        for layer in doc.layers:
            layer_name = layer.dxf.name

            # Системный слой '0' не удаляем (обязательный)
            if layer_name == '0':
                continue

            # Если слой не используется - помечаем на удаление
            if layer_usage.get(layer_name, 0) == 0:
                layers_to_remove.append(layer_name)

        # Удаляем слои и логируем
        if layers_to_remove:
            for layer_name in layers_to_remove:
                doc.layers.remove(layer_name)
                log_info(f"DxfExporter: Удалён неиспользуемый слой: {layer_name}")

            log_info(f"DxfExporter: Очистка DXF: удалено {len(layers_to_remove)} неиспользуемых слоёв")
        else:
            log_debug("DxfExporter: Очистка DXF: все слои используются, удалений нет")

    def _get_label_scale_factor(self) -> float:
        """
        Получение масштабного коэффициента для подписей AutoCAD.

        Коэффициент вычисляется на основе масштаба проекта (2_10_main_scale):
        - 1:500 -> 0.5
        - 1:1000 -> 1.0 (базовый)
        - 1:2000 -> 2.0

        Формула: scale_factor = project_scale / 1000

        Returns:
            Масштабный коэффициент

        Raises:
            ValueError: Если масштаб проекта не определён в метаданных
        """
        from Daman_QGIS.managers.M_19_project_structure_manager import get_project_structure_manager

        project_home = QgsProject.instance().homePath()
        if not project_home:
            raise ValueError("DxfExporter: Путь к проекту не определён. Сохраните проект перед экспортом.")

        structure_manager = get_project_structure_manager()
        structure_manager.project_root = project_home
        gpkg_path = structure_manager.get_gpkg_path(create=False)

        if not gpkg_path or not os.path.exists(gpkg_path):
            raise ValueError("DxfExporter: GeoPackage проекта не найден. Создайте проект через F_0_1.")

        project_db = ProjectDB(gpkg_path)
        scale_data = project_db.get_metadata('2_10_main_scale')

        if not scale_data or not scale_data.get('value'):
            raise ValueError("DxfExporter: Масштаб проекта (2_10_main_scale) не задан в метаданных. Укажите масштаб в настройках проекта.")

        scale_value = scale_data['value']

        # Преобразуем строку "1:1000" или "1000" в число
        try:
            if isinstance(scale_value, str):
                if ':' in scale_value:
                    scale_number = int(scale_value.split(':')[1])
                else:
                    scale_number = int(scale_value)
            else:
                scale_number = int(scale_value)
        except (ValueError, IndexError) as e:
            raise ValueError(f"DxfExporter: Некорректный формат масштаба '{scale_value}'. Ожидается '1:1000' или '1000'.")

        if scale_number <= 0:
            raise ValueError(f"DxfExporter: Масштаб должен быть положительным числом, получено: {scale_number}")

        # Вычисляем коэффициент: scale / 1000
        scale_factor = scale_number / 1000.0
        log_info(f"DxfExporter: Масштаб проекта 1:{scale_number}, коэффициент подписей: {scale_factor}")
        return scale_factor
