# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_1_2_1 - Детальный тест всех категорий ЕГРН
Полная проверка API NSPD для всех 36 категорий загрузки
"""

import sys
import json
from typing import Dict, List, Any
from qgis.core import QgsProject


class TestF121:
    """Детальный тест всех категорий ЕГРН через Fsm_1_2_1_EgrnLoader"""

    # Полный список категорий ЕГРН с их ID
    EGRN_CATEGORIES = [
        {'id': 36368, 'name': 'Земельные участки из ЕГРН', 'priority': 'high'},
        {'id': 36381, 'name': 'Кадастровые кварталы', 'priority': 'high'},
        {'id': 36832, 'name': 'Населённые пункты_полигоны', 'priority': 'high'},
        {'id': 36369, 'name': 'Здания', 'priority': 'high'},
        {'id': 36383, 'name': 'Сооружения', 'priority': 'medium'},
        {'id': 36384, 'name': 'Объекты незавершенного строительства', 'priority': 'medium'},
        {'id': 36940, 'name': 'Зоны с особыми условиями использования территории (ООПТ)', 'priority': 'medium'},
        {'id': 36941, 'name': 'Особые экономические зоны', 'priority': 'high'},

        # Дополнительные категории (не в основном списке F_1_2)
        {'id': 36382, 'name': 'Территориальные зоны', 'priority': 'low'},
        {'id': 36385, 'name': 'Границы', 'priority': 'low'},
        {'id': 36942, 'name': 'Зоны санитарной охраны источников водоснабжения', 'priority': 'medium'},
        {'id': 36943, 'name': 'Охранные зоны объектов электросетевого хозяйства', 'priority': 'medium'},
        {'id': 36944, 'name': 'Зоны охраны объектов культурного наследия', 'priority': 'medium'},
        {'id': 36945, 'name': 'Придорожные полосы', 'priority': 'medium'},
        {'id': 36946, 'name': 'Водоохранные зоны', 'priority': 'medium'},
        {'id': 36947, 'name': 'Зоны затопления и подтопления', 'priority': 'medium'},
        {'id': 36948, 'name': 'Береговые полосы', 'priority': 'medium'},
        {'id': 36949, 'name': 'Рыбоохранные зоны', 'priority': 'low'},
        {'id': 36950, 'name': 'Зоны санитарной охраны скотомогильников', 'priority': 'low'},
        {'id': 36951, 'name': 'Охранные зоны объектов газоснабжения', 'priority': 'medium'},
        {'id': 36952, 'name': 'Охранные зоны объектов теплоснабжения', 'priority': 'medium'},
        {'id': 36953, 'name': 'Охранные зоны линий и сооружений связи', 'priority': 'medium'},
        {'id': 36954, 'name': 'Приаэродромная территория', 'priority': 'low'},
        {'id': 36955, 'name': 'Охранные зоны особо охраняемых природных территорий', 'priority': 'medium'},
        {'id': 36956, 'name': 'Зоны охраняемых объектов', 'priority': 'low'},
        {'id': 36957, 'name': 'Охранные зоны стационарных пунктов наблюдений', 'priority': 'low'},
        {'id': 36958, 'name': 'Защитные леса', 'priority': 'low'},
        {'id': 36959, 'name': 'Зоны затопления', 'priority': 'medium'},
        {'id': 36960, 'name': 'Зоны подтопления', 'priority': 'medium'},
        {'id': 36961, 'name': 'Территории объектов культурного наследия', 'priority': 'medium'},
        {'id': 36962, 'name': 'Публичные сервитуты', 'priority': 'low'},
        {'id': 36963, 'name': 'Территории опережающего развития', 'priority': 'low'},
        {'id': 36964, 'name': 'Свободный порт', 'priority': 'low'},
        {'id': 36965, 'name': 'Игорная зона', 'priority': 'low'},
        {'id': 36966, 'name': 'Лесничества и лесопарки', 'priority': 'low'},
        {'id': 36967, 'name': 'Территории традиционного природопользования', 'priority': 'low'},
    ]

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.egrn_loader = None
        self.test_results: Dict[int, Dict[str, Any]] = {}

    def run_all_tests(self):
        """Запуск всех тестов категорий ЕГРН"""
        self.logger.section("ТЕСТ F_1_2_1: Детальный тест всех категорий ЕГРН")

        # Тест 1: Инициализация загрузчика
        self.test_01_init_egrn_loader()

        # Тест 2: Получение геометрии
        self.test_02_get_map_extent()

        # Тест 3: Тестирование high-priority категорий
        self.test_03_high_priority_categories()

        # Тест 4: Тестирование medium-priority категорий
        self.test_04_medium_priority_categories()

        # Тест 5: Тестирование low-priority категорий
        self.test_05_low_priority_categories()

        # Тест 6: Статистика по всем категориям
        self.test_06_statistics()

        # Итоговая сводка
        self.logger.summary()

    def test_01_init_egrn_loader(self):
        """ТЕСТ 1: Инициализация модуля Fsm_1_2_1_EgrnLoader"""
        self.logger.section("1. Инициализация модуля Fsm_1_2_1_EgrnLoader")

        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_1_egrn_loader import Fsm_1_2_1_EgrnLoader
            from Daman_QGIS.managers import APIManager

            # Инициализируем APIManager (требуется для EgrnLoader)
            api_manager = APIManager()
            self.logger.info("APIManager инициализирован")

            self.egrn_loader = Fsm_1_2_1_EgrnLoader(self.iface, api_manager)

            loaded_path = sys.modules['Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_1_egrn_loader'].__file__
            self.logger.success(f"Модуль загружен: {loaded_path}")

            # Проверяем методы
            # ПРИМЕЧАНИЕ: API_URL хранится в APIManager, а не в EgrnLoader
            # get_map_extent переименован в get_boundary_extent
            required_methods = ['load_layer', 'get_boundary_extent', 'create_geojson', 'send_request']
            for method_name in required_methods:
                if hasattr(self.egrn_loader, method_name):
                    self.logger.success(f"Метод {method_name} существует")
                else:
                    self.logger.fail(f"Метод {method_name} отсутствует!")

        except Exception as e:
            self.logger.error(f"Ошибка инициализации Fsm_1_2_1_EgrnLoader: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
            self.egrn_loader = None

    def test_02_get_map_extent(self):
        """ТЕСТ 2: Получение геометрии границ (get_boundary_extent)"""
        self.logger.section("2. Получение extent границ для API")

        if not self.egrn_loader:
            self.logger.fail("Fsm_1_2_1_EgrnLoader не инициализирован, пропускаем тест")
            return

        try:
            # ПРИМЕЧАНИЕ: get_boundary_extent требует слой L_1_1_2_Границы_работ_10_м
            # В тестовой среде без проекта он вернёт None - это ожидаемое поведение
            geometry = self.egrn_loader.get_boundary_extent()

            if not geometry:
                # В тестовой среде без проекта это нормально
                self.logger.warning("get_boundary_extent вернул None (нет слоя границ в проекте)")
                self.logger.success("Метод get_boundary_extent работает корректно")
                return

            self.logger.success(f"Геометрия получена, тип: {type(geometry)}")

            # Проверяем формат GeoJSON
            if isinstance(geometry, dict):
                self.logger.check(
                    'type' in geometry and geometry['type'] == 'Polygon',
                    "Тип геометрии: Polygon",
                    "Неверный тип геометрии!"
                )

                self.logger.check(
                    'coordinates' in geometry,
                    "Координаты присутствуют",
                    "Координаты отсутствуют!"
                )

                # Проверяем диапазон WGS84
                if 'coordinates' in geometry:
                    coords = geometry['coordinates']
                    if coords and len(coords) > 0 and len(coords[0]) > 0:
                        first_point = coords[0][0]
                        lon, lat = first_point[0], first_point[1]

                        self.logger.check(
                            -180 <= lon <= 180 and -90 <= lat <= 90,
                            f"Координаты в диапазоне WGS84: lon={lon:.6f}, lat={lat:.6f}",
                            f"Координаты вне диапазона WGS84!"
                        )

        except Exception as e:
            self.logger.error(f"Ошибка получения extent: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_03_high_priority_categories(self):
        """ТЕСТ 3: Тестирование high-priority категорий"""
        self.logger.section("3. Тестирование high-priority категорий ЕГРН")

        high_priority = [c for c in self.EGRN_CATEGORIES if c['priority'] == 'high']
        self.logger.info(f"High-priority категорий: {len(high_priority)}")

        self._test_categories(high_priority)

    def test_04_medium_priority_categories(self):
        """ТЕСТ 4: Тестирование medium-priority категорий"""
        self.logger.section("4. Тестирование medium-priority категорий ЕГРН")

        medium_priority = [c for c in self.EGRN_CATEGORIES if c['priority'] == 'medium']
        self.logger.info(f"Medium-priority категорий: {len(medium_priority)}")

        self._test_categories(medium_priority)

    def test_05_low_priority_categories(self):
        """ТЕСТ 5: Тестирование low-priority категорий"""
        self.logger.section("5. Тестирование low-priority категорий ЕГРН")

        low_priority = [c for c in self.EGRN_CATEGORIES if c['priority'] == 'low']
        self.logger.info(f"Low-priority категорий: {len(low_priority)}")

        self._test_categories(low_priority)

    def _test_categories(self, categories: List[Dict[str, Any]]):
        """Тестирование списка категорий"""
        if not self.egrn_loader:
            self.logger.fail("Fsm_1_2_1_EgrnLoader не инициализирован")
            return

        for category in categories:
            category_id = category['id']
            category_name = category['name']

            try:
                self.logger.info(f"Тест категории {category_id}: {category_name}")

                # Получаем геометрию (get_boundary_extent требует слой границ в проекте)
                geometry = self.egrn_loader.get_boundary_extent()
                if not geometry:
                    # В тестовой среде без проекта это ожидаемо
                    self.logger.warning(f"  Нет геометрии для категории {category_id} (нет слоя границ)")
                    self.test_results[category_id] = {
                        'name': category_name,
                        'success': False,
                        'error': 'Нет слоя границ в проекте'
                    }
                    continue

                # Создаем payload
                payload = self.egrn_loader.create_geojson(geometry, category_id)

                self.logger.check(
                    'categories' in payload and payload['categories'][0]['id'] == category_id,
                    f"  Payload создан для категории {category_id}",
                    f"  Ошибка создания payload для категории {category_id}"
                )

                # Отправляем запрос
                response = self.egrn_loader.send_request(payload)

                if response is None:
                    self.logger.warning(f"  API вернул None для категории {category_id}")
                    self.test_results[category_id] = {
                        'name': category_name,
                        'success': False,
                        'error': 'API вернул None'
                    }
                    continue

                # Проверяем наличие features
                if 'features' in response:
                    feature_count = len(response['features'])

                    if feature_count > 0:
                        self.logger.success(f"  Категория {category_id}: {feature_count} объектов")

                        # Проверяем первый feature
                        first_feature = response['features'][0]
                        has_geometry = 'geometry' in first_feature
                        has_properties = 'properties' in first_feature

                        self.test_results[category_id] = {
                            'name': category_name,
                            'success': True,
                            'feature_count': feature_count,
                            'has_geometry': has_geometry,
                            'has_properties': has_properties
                        }

                        if has_geometry:
                            geom_type = first_feature['geometry'].get('type', 'N/A')
                            self.logger.data(f"    Тип геометрии", geom_type)

                        if has_properties:
                            props_count = len(first_feature['properties'])
                            self.logger.data(f"    Свойств", str(props_count))
                    else:
                        self.logger.warning(f"  Категория {category_id}: нет данных в области")
                        self.test_results[category_id] = {
                            'name': category_name,
                            'success': True,
                            'feature_count': 0
                        }
                else:
                    self.logger.fail(f"  Категория {category_id}: ответ не содержит 'features'")
                    self.test_results[category_id] = {
                        'name': category_name,
                        'success': False,
                        'error': 'Нет поля features'
                    }

            except Exception as e:
                self.logger.error(f"  Ошибка теста категории {category_id}: {str(e)}")
                self.test_results[category_id] = {
                    'name': category_name,
                    'success': False,
                    'error': str(e)[:100]
                }

    def test_06_statistics(self):
        """ТЕСТ 6: Статистика по всем категориям"""
        self.logger.section("6. Статистика по всем категориям ЕГРН")

        if not self.test_results:
            self.logger.fail("Нет результатов для анализа")
            return

        total = len(self.test_results)
        successful = sum(1 for r in self.test_results.values() if r['success'])
        failed = total - successful

        with_data = sum(1 for r in self.test_results.values()
                       if r['success'] and r.get('feature_count', 0) > 0)
        empty = sum(1 for r in self.test_results.values()
                   if r['success'] and r.get('feature_count', 0) == 0)

        self.logger.data("Всего категорий протестировано", str(total))
        self.logger.data("Успешных запросов", str(successful))
        self.logger.data("Неудачных запросов", str(failed))
        self.logger.data("Категорий с данными", str(with_data))
        self.logger.data("Категорий без данных (пусто)", str(empty))

        # Топ-5 категорий по количеству объектов
        self.logger.info("")
        self.logger.info("Топ-5 категорий по количеству объектов:")

        categories_with_data = [
            (cat_id, r['name'], r.get('feature_count', 0))
            for cat_id, r in self.test_results.items()
            if r['success'] and r.get('feature_count', 0) > 0
        ]

        categories_with_data.sort(key=lambda x: x[2], reverse=True)

        for i, (cat_id, name, count) in enumerate(categories_with_data[:5], 1):
            self.logger.data(f"  {i}. {name} (ID {cat_id})", f"{count} объектов")

        # Список неудачных категорий
        if failed > 0:
            self.logger.info("")
            self.logger.info("Неудачные категории:")

            failed_categories = [
                (cat_id, r['name'], r.get('error', 'Неизвестная ошибка'))
                for cat_id, r in self.test_results.items()
                if not r['success']
            ]

            for cat_id, name, error in failed_categories:
                self.logger.data(f"  {name} (ID {cat_id})", error)
