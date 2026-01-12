# -*- coding: utf-8 -*-
"""
Модуль управления базовыми слоями и картоосновами
Часть инструмента F_1_4_Запрос
Интегрирован с модулем okno_egrn для загрузки векторных данных ЕГРН
"""

import os
import sys
from qgis.core import (
    QgsProject, QgsMessageLog, Qgis, QgsRasterLayer,
    QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    QgsRectangle, QgsPointXY,
    QgsVectorFileWriter, QgsLayerTreeNode
)
from Daman_QGIS.constants import DEFAULT_LAYER_ORDER
from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers.M_19_project_structure_manager import (
    get_project_structure_manager, FolderType
)


class BaseLayersManager:
    """Менеджер базовых слоев и картооснов"""
    
    def __init__(self, iface):
        """Инициализация менеджера
        
        Args:
            iface: Интерфейс QGIS
        """
        self.iface = iface
        self.okno_egrn = None
        self._init_okno_egrn()
        
    def _init_okno_egrn(self):
        """Инициализация модуля okno_egrn"""
        try:
            # Добавляем путь к внешним модулям если его нет
            external_modules_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                'external_modules'
            )
            if external_modules_path not in sys.path:
                sys.path.append(external_modules_path)
            
            # Импортируем модуль okno_egrn
            from okno_egrn.okno_egrn import OknoEGRN
            self.okno_egrn = OknoEGRN(self.iface)
            
            log_info("Fsm_1_4_1: Модуль okno_egrn успешно инициализирован")
        except RuntimeError as e:
            log_error(f"Fsm_1_4_1: Модуль okno_egrn не найден: {str(e)}")
            raise Exception("Модуль okno_egrn не установлен. Установите его перед использованием функции F_1_4")
    def add_base_layers(self):
        """Добавление всех базовых слоев

        Добавляем слои в обратном порядке отображения
        (первый добавленный будет внизу)

        Returns:
            tuple: (success, error_msg)
        """
        # Добавляем слои снизу вверх
        # Самый нижний - Google Satellite
        self.add_google_satellite()

        # Картооснова НСПД ЦОС
        self.add_nspd_base_layer()

        # Google Labels
        self.add_google_labels()

        return True, None
    
    def add_nspd_base_layer(self):
        """Добавление картоосновы НСПД - ЦОС (Цифровая общегеографическая схема)
        
        Returns:
            bool: Успешность добавления
        """
        project = QgsProject.instance()
        layer_name = "L_1_3_2_Справочный_слой"

        # Удаляем существующий слой для обновления
        for layer in project.mapLayers().values():
            if layer.name() == layer_name:
                log_info(f"Удаляем существующий слой {layer_name} для обновления")
                project.removeMapLayer(layer.id())

        maphead = 'http-header:referer=https://nspd.gov.ru/map?baseLayerId%3D'
        uri = maphead + '235&referer=https://nspd.gov.ru/map?baseLayerId%3D235&type=xyz&url=https://nspd.gov.ru/api/aeggis/v2/235/wmts/%7Bz%7D/%7Bx%7D/%7By%7D.png&zmax=18&zmin=0'
        
        layer = QgsRasterLayer(uri, layer_name, 'wms')

        if layer.isValid():
            # Добавляем через LayerManager - он сам управляет порядком слоев
            try:
                from Daman_QGIS.managers import LayerManager
                layer_manager = LayerManager(self.iface)
                layer.setName(layer_name)
                layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
            except Exception as e:
                log_warning(f"Fsm_1_4_1: Не удалось добавить слой {layer_name} через менеджер: {str(e)}")
                # Fallback: добавляем напрямую
                project.addMapLayer(layer, True)

            log_info("Fsm_1_4_1: Картооснова НСПД добавлена")
            return True
        else:
            log_warning("Fsm_1_4_1: Не удалось добавить картооснову НСПД")
            return False
    
    def add_google_satellite(self):
        """Добавление слоя Google Satellite
        
        Returns:
            bool: Успешность добавления
        """
        project = QgsProject.instance()
        layer_name = "Le_1_2_7_1_Google_Satellite"
        
        # Удаляем существующий слой для обновления
        for layer in project.mapLayers().values():
            if layer.name() == layer_name:
                log_info(f"Fsm_1_4_1: Удаляем существующий слой {layer_name} для обновления")
                project.removeMapLayer(layer.id())

        uri = 'type=xyz&url=https://mt1.google.com/vt/lyrs%3Ds%26x%3D%7Bx%7D%26y%3D%7By%7D%26z%3D%7Bz%7D&zmax=22&zmin=0'
        
        layer = QgsRasterLayer(uri, layer_name, 'wms')

        if layer.isValid():
            # Добавляем через LayerManager - он сам управляет порядком слоев
            try:
                from Daman_QGIS.managers import LayerManager
                layer_manager = LayerManager(self.iface)
                layer.setName(layer_name)
                layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
            except Exception as e:
                log_warning(f"Fsm_1_4_1: Не удалось добавить слой {layer_name} через менеджер: {str(e)}")
                # Fallback: добавляем напрямую
                project.addMapLayer(layer, True)

            log_info("Fsm_1_4_1: Google Satellite добавлен")
            return True
        else:
            log_warning("Fsm_1_4_1: Не удалось добавить Google Satellite")
            return False
    
    def add_google_labels(self):
        """Добавление слоя Google Labels
        
        Returns:
            bool: Успешность добавления
        """
        project = QgsProject.instance()
        layer_name = "Le_1_2_7_3_Google_Labels"
        
        # Удаляем существующий слой для обновления
        for layer in project.mapLayers().values():
            if layer.name() == layer_name:
                log_info(f"Fsm_1_4_1: Удаляем существующий слой {layer_name} для обновления")
                project.removeMapLayer(layer.id())

        uri = 'type=xyz&url=https://mt1.google.com/vt/lyrs%3Dh%26x%3D%7Bx%7D%26y%3D%7By%7D%26z%3D%7Bz%7D&zmax=22&zmin=0'
        
        layer = QgsRasterLayer(uri, layer_name, 'wms')

        if layer.isValid():
            # Добавляем через LayerManager - он сам управляет порядком слоев
            try:
                from Daman_QGIS.managers import LayerManager
                layer_manager = LayerManager(self.iface)
                layer.setName(layer_name)
                layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
            except Exception as e:
                log_warning(f"Fsm_1_4_1: Не удалось добавить слой {layer_name} через менеджер: {str(e)}")
                # Fallback: добавляем напрямую
                project.addMapLayer(layer, True)

            log_info("Fsm_1_4_1: Google Labels добавлен")
            return True
        else:
            log_warning("Fsm_1_4_1: Не удалось добавить Google Labels")
            return False
    def load_nspd_layers(self, nspd_layers):
        """Загрузка векторных слоев ЕГРН через модуль okno_egrn

        Args:
            nspd_layers: Словарь с выбранными слоями НСПД

        Returns:
            tuple: (success_or_dict, error_msg)
                success_or_dict: True или словарь {'loaded': count, 'empty': count}
        """
        if not self.okno_egrn:
            raise ValueError("Модуль okno_egrn не инициализирован")
            
        # Получаем границы работ с буфером 10%
        geometry_dict = self._get_work_boundaries_geometry()
        if not geometry_dict:
            raise ValueError("Не найден слой 1_1_1_Границы_работ")

        # Конфигурация слоев для загрузки (точные названия из okno_egrn!)
        layers_config = [
                {
                    'enabled': nspd_layers.get('cadastral', False),
                    'category_name': 'Кадастровые кварталы',  # ID 4 в okno_egrn
                    'category_id': 36381,
                    'layer_name': 'L_1_2_2_WFS_КК'
                },
                {
                    'enabled': nspd_layers.get('admin', False),
                    'category_name': 'Населённые пункты',  # АТД полигоны
                    'category_id': 36832,
                    'layer_name': 'Le_1_2_3_5_АТД_НП_poly'
                },
                {
                    'enabled': nspd_layers.get('economic', False),
                    'category_name': 'Особые экономические зоны',  # ID 33 в okno_egrn
                    'category_id': 36941,
                    'layer_name': 'Le_1_2_6_1_WFS_Зоны_эконом'
                },
                {
                    'enabled': nspd_layers.get('land_plots', False),
                    'category_name': 'Земельные участки из ЕГРН',  # ID 12 в okno_egrn
                    'category_id': 36368,
                    'layer_name': 'L_1_2_1_WFS_ЗУ'
                },
                {
                    'enabled': nspd_layers.get('protected_areas', False),
                    'category_name': 'Особо охраняемые природные территории',  # ID 27 в okno_egrn
                    'category_id': 36948,
                    'layer_name': 'Le_1_2_5_1_WFS_ЗОУИТ_ООПТ'
            }
        ]

        # Загружаем векторные слои через okno_egrn
        project = QgsProject.instance()
        root = project.layerTreeRoot()

        # Получаем путь к GeoPackage проекта через M_19
        gpkg_path = None
        project_path = project.homePath()
        if project_path:
            structure_manager = get_project_structure_manager()
            structure_manager.project_root = project_path
            gpkg_path = structure_manager.get_gpkg_path(create=False)

            if gpkg_path and os.path.exists(gpkg_path):
                log_info(f"Fsm_1_4_1: Найден GeoPackage: {gpkg_path}")
            else:
                log_warning(f"Fsm_1_4_1: GeoPackage не найден в проекте: {project_path}")
                gpkg_path = None

        # Создаем функцию, которая возвращает геометрию
        def geometry_provider():
            """Провайдер геометрии проекта для okno_egrn API."""
            return geometry_dict

        for config in layers_config:
            if not config['enabled']:
                continue

            # Удаляем существующие слои с таким же именем для обновления данных
            layers_to_remove = []
            for existing_layer in project.mapLayers().values():
                # Проверяем и по нашему имени, и по исходному имени из okno_egrn
                if (existing_layer.name() == config['layer_name'] or
                    existing_layer.name() == config['category_name']):
                    layers_to_remove.append(existing_layer.id())
                    log_info(f"Fsm_1_4_1: Удаляем существующий слой {existing_layer.name()} для обновления")

            # Удаляем найденные слои
            for layer_id in layers_to_remove:
                project.removeMapLayer(layer_id)

            try:
                log_info(f"Fsm_1_4_1: Загрузка векторного слоя: {config['layer_name']}")

                # Запоминаем слои до вызова
                layers_before = set(project.mapLayers().keys())

                # Вызываем API okno_egrn
                # run_common НЕ возвращает слой, а добавляет его в проект
                self.okno_egrn.run_common(
                    geometry_provider,
                    config['category_name'],
                    config['category_id']
                )

                # Находим новый или обновленный слой
                # okno_egrn может добавить новый слой или обновить существующий
                layer = None

                # Сначала ищем по новым слоям
                layers_after = set(project.mapLayers().keys())
                new_layer_ids = layers_after - layers_before

                if new_layer_ids:
                    # Если есть новые слои, берем последний добавленный
                    # (okno_egrn добавляет слой в конец)
                    for layer_id in new_layer_ids:
                        potential_layer = project.mapLayer(layer_id)
                        if potential_layer and potential_layer.name() == config['category_name']:
                            layer = potential_layer
                            break
                    # Если не нашли по точному имени, берем любой новый
                    if not layer and new_layer_ids:
                        layer = project.mapLayer(list(new_layer_ids)[0])

                # Если новых слоев нет, ищем существующий по имени
                if not layer:
                    for lyr_id, lyr in project.mapLayers().items():
                        if lyr.name() == config['category_name']:
                            layer = lyr
                            break

                if layer and layer.isValid() and isinstance(layer, QgsVectorLayer):
                    # Определяем чистое имя для слоя
                    clean_name = config['layer_name'].replace(' ', '_')
                    import re
                    clean_name = re.sub(r'_{2,}', '_', clean_name)

                    # Логируем информацию о слое
                    original_name = layer.name()
                    feature_count = layer.featureCount()

                    # Сначала удаляем слой из дерева (но не из проекта!)
                    layer_node = root.findLayer(layer.id())
                    if layer_node:
                        parent = layer_node.parent()
                        if parent:
                            parent.removeChildNode(layer_node)

                    # Переименовываем слой согласно нашей нумерации
                    # Используем уже определенный clean_name
                    layer.setName(clean_name)

                    # Применяем стиль к векторному слою
                    self._apply_vector_style(layer, clean_name)

                    # Сохраняем слой в GeoPackage если возможно
                    if gpkg_path and os.path.exists(gpkg_path):
                        saved_layer = self._save_to_geopackage(layer, gpkg_path, clean_name)
                        if saved_layer:
                            # Удаляем временный memory слой
                            project.removeMapLayer(layer.id())
                            # Используем сохранённый слой
                            layer = saved_layer
                            # Применяем стиль к сохранённому слою
                            self._apply_vector_style(layer, clean_name)
                        else:
                            log_warning(f"Fsm_1_4_1: Слой {clean_name} не сохранён, используется временный")
                    else:
                        log_warning(f"Fsm_1_4_1: GeoPackage не найден, слой {clean_name} останется временным")

                    # Добавляем через LayerManager - он сам управляет порядком слоев
                    try:
                        from Daman_QGIS.managers import LayerManager
                        layer_manager = LayerManager(self.iface)
                        layer.setName(clean_name)
                        layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
                    except Exception as e:
                        log_warning(f"Fsm_1_4_1: Не удалось добавить слой {clean_name} через менеджер: {str(e)}")

                    log_info(f"Fsm_1_4_1: Векторный слой {clean_name} успешно загружен (исходное имя: {original_name}, объектов: {feature_count})")

            except Exception as e:
                log_error(f"Fsm_1_4_1: Ошибка загрузки слоя {config['layer_name']}: {str(e)}")
                raise

        # Обновляем видимость карт
        self.iface.mapCanvas().refresh()

        # Подсчитываем загруженные слои с данными
        loaded_count = 0
        empty_count = 0

        for config in layers_config:
            if config['enabled']:
                # Проверяем есть ли слой в проекте с данными
                found = False
                for layer in project.mapLayers().values():
                    if layer.name() == config['layer_name']:
                        if layer.featureCount() > 0:
                            loaded_count += 1
                        else:
                            empty_count += 1
                        found = True
                        break
                if not found:
                    empty_count += 1

        # Возвращаем информацию о загрузке
        return {'loaded': loaded_count, 'empty': empty_count}, None
    
    def _get_work_boundaries_geometry(self):
        """Получение геометрии границ работ с буфером 10% в формате GeoJSON
        
        Returns:
            dict: Геометрия в формате GeoJSON (WGS84) или None
        """
        project = QgsProject.instance()
        
        # Ищем слой границ работ
        boundaries_layer = None
        for layer in project.mapLayers().values():
            if layer.name() == "1_1_1_Границы_работ":
                boundaries_layer = layer
                break
        
        if not boundaries_layer or not boundaries_layer.isValid():
            return None
        
        # Получаем extent слоя
        extent = boundaries_layer.extent()
        
        # Добавляем буфер 10%
        width = extent.width()
        height = extent.height()
        buffer_x = width * 0.10
        buffer_y = height * 0.10
        
        # Создаем новый extent с буфером
        buffered_extent = QgsRectangle(
            extent.xMinimum() - buffer_x,
            extent.yMinimum() - buffer_y,
            extent.xMaximum() + buffer_x,
            extent.yMaximum() + buffer_y
        )
        
        # Трансформируем в WGS84 (EPSG:4326) для API
        crs_src = boundaries_layer.crs()
        crs_dest = QgsCoordinateReferenceSystem('EPSG:4326')
        transform = QgsCoordinateTransform(crs_src, crs_dest, project)
        
        # Создаем координаты прямоугольника
        coords = [
            transform.transform(QgsPointXY(buffered_extent.xMinimum(), buffered_extent.yMinimum())),
            transform.transform(QgsPointXY(buffered_extent.xMaximum(), buffered_extent.yMinimum())),
            transform.transform(QgsPointXY(buffered_extent.xMaximum(), buffered_extent.yMaximum())),
            transform.transform(QgsPointXY(buffered_extent.xMinimum(), buffered_extent.yMaximum())),
            transform.transform(QgsPointXY(buffered_extent.xMinimum(), buffered_extent.yMinimum()))
        ]
        
        # Формируем GeoJSON геометрию
        return {
            "type": "Polygon",
            "coordinates": [[[pt.x(), pt.y()] for pt in coords]]
        }
    def _apply_vector_style(self, layer, layer_name):
        """Применение стиля к векторному слою

        Args:
            layer: Векторный слой
            layer_name: Имя слоя для определения стиля
        """
        from Daman_QGIS.managers import StyleManager
        style_manager = StyleManager()
        style_manager.apply_qgis_style(layer, layer_name)


    # УДАЛЕН: _insert_layer_by_number() - теперь LayerManager управляет порядком слоев
    # См. layer_manager.py для настройки порядка слоев

    def _save_to_geopackage(self, layer, gpkg_path, layer_name):
        """Сохранение временного слоя в GeoPackage

        Args:
            layer: Временный векторный слой
            gpkg_path: Путь к GeoPackage
            layer_name: Имя слоя для сохранения

        Returns:
            QgsVectorLayer: Сохранённый слой или None
        """
        # Определяем опции сохранения
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = layer_name

        # Для GeoPackage всегда используем CreateOrOverwriteLayer при добавлении слоя
        if os.path.exists(gpkg_path):
            # Файл существует - добавляем или перезаписываем слой
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        else:
            # Файл не существует - создаём новый
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

        # Сохраняем слой
        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            gpkg_path,
            QgsProject.instance().transformContext(),
            options
        )

        if error[0] == QgsVectorFileWriter.NoError:
            # Загружаем сохранённый слой из GeoPackage
            saved_layer = QgsVectorLayer(
                f"{gpkg_path}|layername={layer_name}",
                layer_name,
                "ogr"
            )

            if saved_layer.isValid():
                # Добавляем слой в проект
                QgsProject.instance().addMapLayer(saved_layer, False)

                log_info(f"Fsm_1_4_1: Слой {layer_name} сохранён в GeoPackage")
                return saved_layer
            else:
                log_warning(f"Fsm_1_4_1: Не удалось загрузить сохранённый слой {layer_name}")
        else:
            log_warning(f"Fsm_1_4_1: Ошибка сохранения слоя {layer_name}: {error[1]}")

        return None
