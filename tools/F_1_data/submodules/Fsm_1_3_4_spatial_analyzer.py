# -*- coding: utf-8 -*-
"""
Субмодуль пространственного анализа для выборки бюджета
Выполняет анализ пересечений границ с объектами
"""

from qgis.core import (
    QgsProject, QgsMessageLog, Qgis,
    QgsGeometry, QgsFeatureRequest,
    QgsSpatialIndex, QgsCoordinateTransform
)
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error


class SpatialAnalyzer:
    """Анализатор пространственных пересечений"""
    
    def __init__(self, iface):
        """Инициализация анализатора"""
        self.iface = iface
        self.project = QgsProject.instance()
    def analyze_intersections(self, boundaries_layer):
        """Анализ пересечений границ с объектами

        Args:
            boundaries_layer: Слой с границами для анализа

        Returns:
            dict: Результаты анализа
        """
        results = {
            'cadastral_quarters': 0,
            'land_plots': 0,
            'land_plots_forest_fund': 0,  # ЗУ в лесном фонде
            'capital_objects': 0,
            'settlements': [],
            'municipal_districts': [],  # Муниципальные образования (АТД_МО)
            'oopt': [],  # ООПТ (особо охраняемые природные территории)
            'forest_quarters': 0,
            'forest_subdivisions': 0  # Лесоустроительные выделы
        }

        if not boundaries_layer or not boundaries_layer.isValid():
            raise ValueError("Недействительный слой границ")

        log_info("Fsm_1_3_4: Начало пространственного анализа")

        # Получаем объединенную геометрию границ
        boundaries_geom = self._get_boundaries_geometry(boundaries_layer)
        if not boundaries_geom:
            raise ValueError("Не удалось получить геометрию границ")

        # Логируем информацию о геометрии границ
        log_info(f"Fsm_1_3_4: Геометрия границ - тип: {boundaries_geom.type()}, площадь: {boundaries_geom.area():.2f}")

        # Анализируем каждый тип слоев

        # 1. Кадастровые кварталы
        layer = self._get_layer_by_name('L_1_2_2_WFS_КК')
        if layer:
            total = layer.featureCount()
            count = self._count_intersecting_features(layer, boundaries_geom)
            results['cadastral_quarters'] = count
            log_info(f"Fsm_1_3_4: Кадастровые кварталы - {count} из {total}")

        # 2. Земельные участки (используем округленный слой из F_2_1)
        layer = self._get_layer_by_name('Le_2_1_1_1_Выборка_ЗУ')
        if layer:
            total = layer.featureCount()
            count = self._count_intersecting_features(layer, boundaries_geom)
            results['land_plots'] = count
            log_info(f"Fsm_1_3_4: Земельные участки (округленные) - {count} из {total}")

            # 2.1. Земельные участки в лесном фонде
            forest_fund_count = self._count_forest_fund_land_plots(layer, boundaries_geom)
            results['land_plots_forest_fund'] = forest_fund_count
            log_info(f"Fsm_1_3_4: ЗУ в лесном фонде - {forest_fund_count} из {count}")
        else:
            log_warning("Fsm_1_3_4: Слой Le_2_1_1_1_Выборка_ЗУ не найден - количество ЗУ будет 0")
            results['land_plots'] = 0
            results['land_plots_forest_fund'] = 0

        # 3. Объекты капитального строительства (используем слой выборки L_2_1_2_Выборка_ОКС)
        layer = self._get_layer_by_name('L_2_1_2_Выборка_ОКС')
        if layer:
            total = layer.featureCount()
            count = self._count_intersecting_features(layer, boundaries_geom)
            results['capital_objects'] = count
            log_info(f"Fsm_1_3_4: Объекты капитального строительства (выборка) - {count} из {total}")
        else:
            results['capital_objects'] = 0
            log_warning("Fsm_1_3_4: Слой L_2_1_2_Выборка_ОКС не найден - количество ОКС будет 0")

        # 4. Населенные пункты (список наименований)
        layer = self._get_layer_by_name('Le_1_2_3_5_АТД_НП_poly')
        if layer:
            layer_count = layer.featureCount()
            log_info(f"Fsm_1_3_4: Слой Le_1_2_3_5_АТД_НП_poly содержит {layer_count} объектов")
            settlements = self._get_intersecting_settlements(layer, boundaries_geom)
            results['settlements'] = settlements
            log_info(f"Fsm_1_3_4: Населенные пункты - {len(settlements)} шт.")
        else:
            log_warning("Fsm_1_3_4: Слой Le_1_2_3_5_АТД_НП_poly не найден")

        # 5. Муниципальные образования (список наименований)
        layer = self._get_layer_by_name('Le_1_2_3_12_АТД_МО_poly')
        if layer:
            layer_count = layer.featureCount()
            log_info(f"Fsm_1_3_4: Слой Le_1_2_3_12_АТД_МО_poly содержит {layer_count} объектов")
            municipal_districts = self._get_intersecting_municipal_districts(layer, boundaries_geom)
            results['municipal_districts'] = municipal_districts
            log_info(f"Fsm_1_3_4: Муниципальные образования - {len(municipal_districts)} шт.")
        else:
            log_warning("Fsm_1_3_4: Слой Le_1_2_3_12_АТД_МО_poly не найден")

        # 6. ООПТ (особо охраняемые природные территории)
        layer = self._get_layer_by_name('Le_1_2_5_21_WFS_ЗОУИТ_ОЗ_ООПТ')
        if layer:
            layer_count = layer.featureCount()
            log_info(f"Fsm_1_3_4: Слой Le_1_2_5_21_WFS_ЗОУИТ_ОЗ_ООПТ содержит {layer_count} объектов")
            oopt = self._get_intersecting_oopt(layer, boundaries_geom)
            results['oopt'] = oopt
            log_info(f"Fsm_1_3_4: ООПТ - {len(oopt)} шт.")
        else:
            log_warning("Fsm_1_3_4: Слой Le_1_2_5_21_WFS_ЗОУИТ_ОЗ_ООПТ не найден")

        # 7. Лесные кварталы
        layer = self._get_layer_by_name('L_1_1_3_ФГИС_ЛК_Кварталы')
        if layer:
            total = layer.featureCount()
            count = self._count_intersecting_features(layer, boundaries_geom)
            results['forest_quarters'] = count
            log_info(f"Fsm_1_3_4: Лесные кварталы - {count} из {total}")

        # 8. Лесоустроительные выделы
        layer = self._get_layer_by_name('L_1_1_4_ФГИС_ЛК_Выделы')
        if layer:
            total = layer.featureCount()
            count = self._count_intersecting_features(layer, boundaries_geom)
            results['forest_subdivisions'] = count
            log_info(f"Fsm_1_3_4: Лесоустроительные выделы - {count} из {total}")

        log_info("Fsm_1_3_4: Анализ завершен успешно")

        return results
    
    def _get_boundaries_geometry(self, boundaries_layer):
        """Получение объединенной геометрии границ
        
        Args:
            boundaries_layer: Слой границ
            
        Returns:
            QgsGeometry: Объединенная геометрия или None
        """
        
        try:
            geometries = []
            
            for feature in boundaries_layer.getFeatures():
                if feature.hasGeometry():
                    geom = feature.geometry()
                    if geom and not geom.isNull():
                        geometries.append(geom)
            
            if geometries:
                # Объединяем все геометрии
                united = QgsGeometry.unaryUnion(geometries)
                if united and not united.isNull():
                    return united
            
            return None
            
        except Exception as e:
            log_warning(f"Fsm_1_3_4: Ошибка получения геометрии границ - {str(e)}")
            return None
    
    def _get_layer_by_name(self, layer_name):
        """Получение слоя по имени
        
        Args:
            layer_name: Имя слоя
            
        Returns:
            QgsVectorLayer: Найденный слой или None
        """
        
        for layer in self.project.mapLayers().values():
            if layer.name() == layer_name:
                return layer
        
        return None
    
    def _count_intersecting_features(self, layer, boundaries_geom):
        """Подсчет пересекающихся объектов (только уникальные кадастровые номера)

        Args:
            layer: Слой для анализа
            boundaries_geom: Подготовленная геометрия границ

        Returns:
            int: Количество уникальных кадастровых номеров
        """

        try:
            if not layer or not layer.isValid():
                return 0

            unique_cadnums = set()  # Набор уникальных кадастровых номеров
            total_features = layer.featureCount()

            # Определяем поле с кадастровым номером
            cad_field = None
            for field_name in ['cad_num', 'cadastral_number', 'cn', 'cadnum']:
                if layer.fields().indexFromName(field_name) >= 0:
                    cad_field = field_name
                    break

            if not cad_field:
                log_warning(f"Fsm_1_3_4: Поле с кадастровым номером не найдено в {layer.name()}, подсчёт всех объектов")
                # Если нет поля cad_num - считаем как раньше (все объекты)
                count = 0
            else:
                log_info(f"Fsm_1_3_4: Используется поле '{cad_field}' для уникальности")
            
            # Проверяем CRS слоев (используем L_1_1_1 для F_1_3)
            boundaries_layer = self._get_layer_by_name('L_1_1_1_Границы_работ')
            if boundaries_layer:
                boundaries_crs = boundaries_layer.crs()
                layer_crs = layer.crs()
                
                # Если CRS отличаются, создаем трансформацию
                if boundaries_crs != layer_crs:
                    transform = QgsCoordinateTransform(layer_crs, boundaries_crs, self.project)
                    log_info(f"Fsm_1_3_4: Трансформация CRS для {layer.name()}")
                else:
                    transform = None
            else:
                transform = None
            
            # Используем пространственный индекс для больших слоев
            if total_features > 100:
                # Получаем bbox границ
                bbox = boundaries_geom.boundingBox()
                
                # Если CRS отличаются, трансформируем bbox в СК слоя
                if transform:
                    # Создаем обратную трансформацию для bbox (из СК границ в СК слоя)
                    transform_bbox = QgsCoordinateTransform(boundaries_crs, layer_crs, self.project)
                    bbox = transform_bbox.transformBoundingBox(bbox)
                
                # Создаем пространственный запрос
                request = QgsFeatureRequest()
                request.setFilterRect(bbox)
                
                # Проверяем только объекты в bbox
                for feature in layer.getFeatures(request):
                    if feature.hasGeometry():
                        geom = feature.geometry()
                        if geom and not geom.isNull():
                            # Трансформируем геометрию если нужно
                            if transform:
                                geom = QgsGeometry(geom)  # Копия
                                geom.transform(transform)
                            if geom.intersects(boundaries_geom):
                                if cad_field:
                                    # Добавляем уникальный кадастровый номер
                                    cad_num = feature.attribute(cad_field)
                                    if cad_num and cad_num not in [None, '', 'NULL']:
                                        unique_cadnums.add(str(cad_num))
                                else:
                                    count += 1  # Резервный подсчёт если нет поля
            else:
                # Для маленьких слоев проверяем все объекты
                for feature in layer.getFeatures():
                    if feature.hasGeometry():
                        geom = feature.geometry()
                        if geom and not geom.isNull():
                            # Трансформируем геометрию если нужно
                            if transform:
                                geom = QgsGeometry(geom)  # Копия
                                geom.transform(transform)
                            if geom.intersects(boundaries_geom):
                                if cad_field:
                                    # Добавляем уникальный кадастровый номер
                                    cad_num = feature.attribute(cad_field)
                                    if cad_num and cad_num not in [None, '', 'NULL']:
                                        unique_cadnums.add(str(cad_num))
                                else:
                                    count += 1  # Резервный подсчёт если нет поля

            # Возвращаем количество уникальных номеров или обычный счётчик
            result = len(unique_cadnums) if cad_field else count
            if cad_field and len(unique_cadnums) != total_features:
                log_info(f"Fsm_1_3_4: {layer.name()} - {result} уникальных из {count if not cad_field else len(unique_cadnums)} объектов")
            return result
            
        except Exception as e:
            log_warning(f"Fsm_1_3_4: Ошибка подсчета для {layer.name()} - {str(e)}")
            return 0
    
    def _get_intersecting_settlements(self, layer, boundaries_geom):
        """Получение списка пересекающихся населенных пунктов
        
        Args:
            layer: Слой населенных пунктов
            boundaries_geom: Подготовленная геометрия границ
            
        Returns:
            list: Список наименований населенных пунктов
        """
        
        try:
            if not layer or not layer.isValid():
                log_warning("Fsm_1_3_4: Слой населенных пунктов недействителен")
                return []
            
            settlements = []
            
            # Логируем количество объектов
            total_features = layer.featureCount()
            log_info(f"Fsm_1_3_4: Населенные пункты - всего объектов: {total_features}")
            
            # Определяем поле с названием
            name_field = None
            for field_name in ['name', 'Name', 'NAME', 'наименование', 'Наименование', 'title', 'Title']:
                if layer.fields().indexFromName(field_name) >= 0:
                    name_field = field_name
                    break
            
            if not name_field:
                # Если не нашли стандартное поле, берем первое текстовое
                for field in layer.fields():
                    if field.type() == 10:  # String type
                        name_field = field.name()
                        break
            
            if not name_field:
                log_warning("Fsm_1_3_4: Не найдено поле с названием населенного пункта")
                return []
            
            log_info(f"Fsm_1_3_4: Используется поле '{name_field}' для названий")
            
            # Проверяем CRS и готовим трансформацию (используем L_1_1_1 для F_1_3)
            boundaries_layer = self._get_layer_by_name('L_1_1_1_Границы_работ')
            if boundaries_layer:
                boundaries_crs = boundaries_layer.crs()
                layer_crs = layer.crs()
                if boundaries_crs != layer_crs:
                    transform = QgsCoordinateTransform(boundaries_crs, layer_crs, self.project)
                    log_info(f"Fsm_1_3_4: Трансформация bbox для населенных пунктов")
                    # Трансформируем bbox в CRS слоя для корректной фильтрации
                    bbox = boundaries_geom.boundingBox()
                    bbox = transform.transformBoundingBox(bbox)
                    # Обратная трансформация для геометрии
                    transform_back = QgsCoordinateTransform(layer_crs, boundaries_crs, self.project)
                else:
                    bbox = boundaries_geom.boundingBox()
                    transform_back = None
            else:
                bbox = boundaries_geom.boundingBox()
                transform_back = None
            
            # Создаем запрос с фильтрацией по bbox
            request = QgsFeatureRequest()
            request.setFilterRect(bbox)
            
            # Собираем названия
            checked_count = 0
            for feature in layer.getFeatures(request):
                checked_count += 1
                if feature.hasGeometry():
                    geom = feature.geometry()
                    if geom and not geom.isNull():
                        # Трансформируем геометрию в CRS границ если нужно
                        if transform_back:
                            geom = QgsGeometry(geom)  # Копия
                            geom.transform(transform_back)
                        if geom.intersects(boundaries_geom):
                            name = feature.attribute(name_field)
                            if name and name not in settlements:
                                settlements.append(str(name))
            
            log_info(f"Fsm_1_3_4: Проверено {checked_count} населенных пунктов, найдено {len(settlements)}")
            
            # Сортируем по алфавиту
            settlements.sort()
            
            return settlements
            
        except Exception as e:
            log_warning(f"Fsm_1_3_4: Ошибка получения населенных пунктов - {str(e)}")
            return []

    def _get_intersecting_municipal_districts(self, layer, boundaries_geom):
        """Получение списка пересекающихся муниципальных образований

        Args:
            layer: Слой муниципальных образований
            boundaries_geom: Подготовленная геометрия границ

        Returns:
            list: Список наименований муниципальных образований
        """

        try:
            if not layer or not layer.isValid():
                log_warning("Fsm_1_3_4: Слой муниципальных образований недействителен")
                return []

            municipal_districts = []

            # Логируем количество объектов
            total_features = layer.featureCount()
            log_info(f"Fsm_1_3_4: Муниципальные образования - всего объектов: {total_features}")

            # Определяем поле с названием
            name_field = None
            for field_name in ['name', 'Name', 'NAME', 'наименование', 'Наименование', 'title', 'Title']:
                if layer.fields().indexFromName(field_name) >= 0:
                    name_field = field_name
                    break

            if not name_field:
                # Если не нашли стандартное поле, берем первое текстовое
                for field in layer.fields():
                    if field.type() == 10:  # String type
                        name_field = field.name()
                        break

            if not name_field:
                log_warning("Fsm_1_3_4: Не найдено поле с названием муниципального образования")
                return []

            log_info(f"Fsm_1_3_4: Используется поле '{name_field}' для названий МО")

            # Проверяем CRS и готовим трансформацию (используем L_1_1_1 для F_1_3)
            boundaries_layer = self._get_layer_by_name('L_1_1_1_Границы_работ')
            if boundaries_layer:
                boundaries_crs = boundaries_layer.crs()
                layer_crs = layer.crs()
                if boundaries_crs != layer_crs:
                    transform = QgsCoordinateTransform(boundaries_crs, layer_crs, self.project)
                    log_info(f"Fsm_1_3_4: Трансформация bbox для муниципальных образований")
                    # Трансформируем bbox в CRS слоя для корректной фильтрации
                    bbox = boundaries_geom.boundingBox()
                    bbox = transform.transformBoundingBox(bbox)
                    # Обратная трансформация для геометрии
                    transform_back = QgsCoordinateTransform(layer_crs, boundaries_crs, self.project)
                else:
                    bbox = boundaries_geom.boundingBox()
                    transform_back = None
            else:
                bbox = boundaries_geom.boundingBox()
                transform_back = None

            # Создаем запрос с фильтрацией по bbox
            request = QgsFeatureRequest()
            request.setFilterRect(bbox)

            # Собираем названия
            checked_count = 0
            for feature in layer.getFeatures(request):
                checked_count += 1
                if feature.hasGeometry():
                    geom = feature.geometry()
                    if geom and not geom.isNull():
                        # Трансформируем геометрию в CRS границ если нужно
                        if transform_back:
                            geom = QgsGeometry(geom)  # Копия
                            geom.transform(transform_back)
                        if geom.intersects(boundaries_geom):
                            name = feature.attribute(name_field)
                            if name and name not in municipal_districts:
                                municipal_districts.append(str(name))

            log_info(f"Fsm_1_3_4: Проверено {checked_count} муниципальных образований, найдено {len(municipal_districts)}")

            # Сортируем по алфавиту
            municipal_districts.sort()

            return municipal_districts

        except Exception as e:
            log_warning(f"Fsm_1_3_4: Ошибка получения муниципальных образований - {str(e)}")
            return []

    def _count_forest_fund_land_plots(self, layer, boundaries_geom):
        """Подсчет земельных участков с категорией 'Земли лесного фонда' (только уникальные кадастровые номера)

        Args:
            layer: Слой земельных участков (Le_2_1_1_1_Выборка_ЗУ - округленный слой из F_2_1)
            boundaries_geom: Подготовленная геометрия границ

        Returns:
            int: Количество уникальных ЗУ в лесном фонде
        """

        try:
            if not layer or not layer.isValid():
                return 0

            # Поиск поля категории земель (разные названия в разных слоях)
            # Le_2_1_1_1_Выборка_ЗУ использует working_name "Категория" из Base_selection_ZU.json
            # WFS слои используют "land_record_category_type"
            field_name = None
            for candidate in ['Категория', 'land_record_category_type']:
                if layer.fields().indexFromName(candidate) >= 0:
                    field_name = candidate
                    break

            if not field_name:
                log_warning(f"Fsm_1_3_4: Поле категории земель не найдено в слое {layer.name()}")
                return 0

            field_index = layer.fields().indexFromName(field_name)
            log_info(f"Fsm_1_3_4: Поле '{field_name}' найдено (индекс: {field_index})")

            # Определяем поле с кадастровым номером
            cad_field = None
            for cad_field_name in ['cad_num', 'cadastral_number', 'cn', 'cadnum']:
                if layer.fields().indexFromName(cad_field_name) >= 0:
                    cad_field = cad_field_name
                    break

            if not cad_field:
                log_warning(f"Fsm_1_3_4: Поле с кадастровым номером не найдено в {layer.name()}, подсчёт всех объектов")
                count = 0  # Резервный счётчик
            else:
                log_info(f"Fsm_1_3_4: Используется поле '{cad_field}' для уникальности лесных ЗУ")

            unique_cadnums = set()  # Набор уникальных кадастровых номеров лесных ЗУ
            total_features = layer.featureCount()

            # Проверяем CRS слоев (используем L_1_1_1 для F_1_3)
            boundaries_layer = self._get_layer_by_name('L_1_1_1_Границы_работ')
            if boundaries_layer:
                boundaries_crs = boundaries_layer.crs()
                layer_crs = layer.crs()

                # Если CRS отличаются, создаем трансформацию
                if boundaries_crs != layer_crs:
                    transform = QgsCoordinateTransform(layer_crs, boundaries_crs, self.project)
                    log_info(f"Fsm_1_3_4: Трансформация CRS для лесных ЗУ")
                else:
                    transform = None
            else:
                transform = None

            # Используем пространственный индекс для больших слоев
            if total_features > 100:
                # Получаем bbox границ
                bbox = boundaries_geom.boundingBox()

                # Если CRS отличаются, трансформируем bbox в СК слоя
                if transform:
                    # Создаем обратную трансформацию для bbox (из СК границ в СК слоя)
                    transform_bbox = QgsCoordinateTransform(boundaries_crs, layer_crs, self.project)
                    bbox = transform_bbox.transformBoundingBox(bbox)

                # Создаем пространственный запрос
                request = QgsFeatureRequest()
                request.setFilterRect(bbox)

                # Проверяем только объекты в bbox
                for feature in layer.getFeatures(request):
                    if feature.hasGeometry():
                        geom = feature.geometry()
                        if geom and not geom.isNull():
                            # Трансформируем геометрию если нужно
                            if transform:
                                geom = QgsGeometry(geom)  # Копия
                                geom.transform(transform)

                            # Проверяем пересечение
                            if geom.intersects(boundaries_geom):
                                # Проверяем категорию
                                category = feature.attribute(field_name)
                                if category == "Земли лесного фонда":
                                    if cad_field:
                                        # Добавляем уникальный кадастровый номер
                                        cad_num = feature.attribute(cad_field)
                                        if cad_num and cad_num not in [None, '', 'NULL']:
                                            unique_cadnums.add(str(cad_num))
                                    else:
                                        count += 1  # Резервный подсчёт если нет поля
            else:
                # Для маленьких слоев проверяем все объекты
                for feature in layer.getFeatures():
                    if feature.hasGeometry():
                        geom = feature.geometry()
                        if geom and not geom.isNull():
                            # Трансформируем геометрию если нужно
                            if transform:
                                geom = QgsGeometry(geom)  # Копия
                                geom.transform(transform)

                            # Проверяем пересечение
                            if geom.intersects(boundaries_geom):
                                # Проверяем категорию
                                category = feature.attribute(field_name)
                                if category == "Земли лесного фонда":
                                    if cad_field:
                                        # Добавляем уникальный кадастровый номер
                                        cad_num = feature.attribute(cad_field)
                                        if cad_num and cad_num not in [None, '', 'NULL']:
                                            unique_cadnums.add(str(cad_num))
                                    else:
                                        count += 1  # Резервный подсчёт если нет поля

            # Возвращаем количество уникальных номеров или обычный счётчик
            result = len(unique_cadnums) if cad_field else count
            if cad_field:
                log_info(f"Fsm_1_3_4: Лесные ЗУ - {result} уникальных кадастровых номеров")
            return result

        except Exception as e:
            log_warning(f"Fsm_1_3_4: Ошибка подсчета лесных ЗУ - {str(e)}")
            return 0

    def _get_intersecting_oopt(self, layer, boundaries_geom):
        """Получение списка пересекающихся ООПТ (особо охраняемых природных территорий)

        Args:
            layer: Слой ООПТ (Le_1_2_5_21_WFS_ЗОУИТ_ОЗ_ООПТ)
            boundaries_geom: Подготовленная геометрия границ

        Returns:
            list: Список наименований ООПТ из поля name_by_doc
        """

        try:
            if not layer or not layer.isValid():
                log_warning("Fsm_1_3_4: Слой ООПТ недействителен")
                return []

            oopt_list = []

            # Логируем количество объектов
            total_features = layer.featureCount()
            log_info(f"Fsm_1_3_4: ООПТ - всего объектов: {total_features}")

            # Поле с официальным названием ООПТ
            name_field = 'name_by_doc'
            if layer.fields().indexFromName(name_field) < 0:
                log_warning(f"Fsm_1_3_4: Поле '{name_field}' не найдено в слое ООПТ")
                return []

            log_info(f"Fsm_1_3_4: Используется поле '{name_field}' для названий ООПТ")

            # Проверяем CRS и готовим трансформацию (используем L_1_1_1 для F_1_3)
            boundaries_layer = self._get_layer_by_name('L_1_1_1_Границы_работ')
            if boundaries_layer:
                boundaries_crs = boundaries_layer.crs()
                layer_crs = layer.crs()
                if boundaries_crs != layer_crs:
                    transform = QgsCoordinateTransform(boundaries_crs, layer_crs, self.project)
                    log_info(f"Fsm_1_3_4: Трансформация bbox для ООПТ")
                    # Трансформируем bbox в CRS слоя для корректной фильтрации
                    bbox = boundaries_geom.boundingBox()
                    bbox = transform.transformBoundingBox(bbox)
                    # Обратная трансформация для геометрии
                    transform_back = QgsCoordinateTransform(layer_crs, boundaries_crs, self.project)
                else:
                    bbox = boundaries_geom.boundingBox()
                    transform_back = None
            else:
                bbox = boundaries_geom.boundingBox()
                transform_back = None

            # Создаем запрос с фильтрацией по bbox
            request = QgsFeatureRequest()
            request.setFilterRect(bbox)

            # Собираем названия
            checked_count = 0
            for feature in layer.getFeatures(request):
                checked_count += 1
                if feature.hasGeometry():
                    geom = feature.geometry()
                    if geom and not geom.isNull():
                        # Трансформируем геометрию в CRS границ если нужно
                        if transform_back:
                            geom = QgsGeometry(geom)  # Копия
                            geom.transform(transform_back)
                        if geom.intersects(boundaries_geom):
                            name = feature.attribute(name_field)
                            if name and name not in oopt_list:
                                oopt_list.append(str(name))

            log_info(f"Fsm_1_3_4: Проверено {checked_count} ООПТ, найдено {len(oopt_list)}")

            # Сортируем по алфавиту
            oopt_list.sort()

            return oopt_list

        except Exception as e:
            log_warning(f"Fsm_1_3_4: Ошибка получения ООПТ - {str(e)}")
            return []
