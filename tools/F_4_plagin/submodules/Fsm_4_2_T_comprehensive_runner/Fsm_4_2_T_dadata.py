# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_dadata - Тесты M_39_DaDataGeocodingManager

Проверяет:
- Инициализация и регистрация в registry
- Управление API-ключом (set/get/is_configured)
- Обратное геокодирование (geolocate) - реальный API
- Подсказки по адресу (suggest)
- Поиск по идентификатору (find_by_id)
- Сессионное кэширование
- Форматирование адреса по qc_geo
"""


class TestDaData:
    """Тесты M_39_DaDataGeocodingManager"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.geocoder = None

    def run_all_tests(self):
        """Запуск всех тестов"""
        self.logger.section("ТЕСТ M_39: DaDataGeocodingManager")

        try:
            self.test_01_init()
            self.test_02_api_key()
            self.test_03_geolocate_moscow()
            self.test_04_geolocate_rural()
            self.test_05_cache()
            self.test_06_suggest()
            self.test_07_find_by_id()
            self.test_08_format_address()
        except Exception as e:
            self.logger.error(f"Критическая ошибка: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()

    def test_01_init(self):
        """ТЕСТ 1: Инициализация менеджера"""
        self.logger.section("1. Инициализация M_39")

        try:
            from Daman_QGIS.managers import registry

            self.geocoder = registry.get('M_39')
            self.logger.check(
                self.geocoder is not None,
                "M_39 загружен из registry",
                "M_39 не найден в registry!"
            )

            if not self.geocoder:
                return

            # Проверка методов
            required_methods = [
                'initialize', 'shutdown', 'is_configured', 'set_api_key',
                'get_api_key', 'geolocate', 'suggest', 'find_by_id',
                'format_address_by_quality', 'clear_cache'
            ]
            for method_name in required_methods:
                self.logger.check(
                    hasattr(self.geocoder, method_name),
                    f"Метод {method_name} существует",
                    f"Метод {method_name} отсутствует!"
                )

            # Инициализация
            result = self.geocoder.initialize()
            self.logger.check(
                result is True,
                "initialize() вернул True",
                "initialize() вернул False!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка инициализации: {e}")

    def test_02_api_key(self):
        """ТЕСТ 2: Управление API-ключом"""
        self.logger.section("2. API-ключ")

        if not self.geocoder:
            self.logger.fail("Geocoder не инициализирован")
            return

        try:
            # Должен быть настроен (bundled key)
            self.logger.check(
                self.geocoder.is_configured(),
                "is_configured() = True (bundled key)",
                "is_configured() = False, ключ не загрузился!"
            )

            # Получение ключа
            key = self.geocoder.get_api_key()
            self.logger.check(
                key is not None and len(key) > 10,
                f"API-ключ получен (длина {len(key) if key else 0})",
                "API-ключ пуст или слишком короткий!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка теста API-ключа: {e}")

    def test_03_geolocate_moscow(self):
        """ТЕСТ 3: Обратное геокодирование -- Москва"""
        self.logger.section("3. Geolocate: Москва")

        if not self.geocoder or not self.geocoder.is_configured():
            self.logger.fail("Geocoder не настроен")
            return

        try:
            # Красная площадь, Москва
            result = self.geocoder.geolocate(lat=55.7539, lon=37.6208)

            self.logger.check(
                result is not None,
                "Результат geolocate получен",
                "geolocate вернул None!"
            )

            if not result:
                return

            value = result.get('value', '')
            data = result.get('data', {})

            self.logger.check(
                len(value) > 0,
                f"Адрес: {value}",
                "Пустой адрес!"
            )

            # Проверка ключевых полей data
            self.logger.check(
                'region' in data and data['region'] is not None,
                f"Регион: {data.get('region')}",
                "Регион отсутствует!"
            )

            # ОКАТО/ОКТМО
            okato = data.get('okato')
            oktmo = data.get('oktmo')
            self.logger.check(
                okato is not None,
                f"ОКАТО: {okato}",
                "ОКАТО отсутствует!"
            )
            self.logger.check(
                oktmo is not None,
                f"ОКТМО: {oktmo}",
                "ОКТМО отсутствует!"
            )

            # ФИАС
            fias_id = data.get('fias_id')
            self.logger.check(
                fias_id is not None,
                f"ФИАС ID: {fias_id}",
                "ФИАС ID отсутствует!"
            )

            # qc_geo
            qc_geo = data.get('qc_geo')
            self.logger.check(
                qc_geo is not None,
                f"qc_geo: {qc_geo}",
                "qc_geo отсутствует!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка geolocate Москва: {e}")

    def test_04_geolocate_rural(self):
        """ТЕСТ 4: Обратное геокодирование -- сельская местность"""
        self.logger.section("4. Geolocate: сельская местность")

        if not self.geocoder or not self.geocoder.is_configured():
            self.logger.fail("Geocoder не настроен")
            return

        try:
            # Подмосковье (Серпуховский район)
            result = self.geocoder.geolocate(lat=54.9167, lon=37.4167)

            self.logger.check(
                result is not None,
                "Результат для сельской местности получен",
                "geolocate вернул None для сельской местности"
            )

            if result:
                value = result.get('value', '')
                data = result.get('data', {})
                qc_geo = data.get('qc_geo', '?')
                self.logger.data("Адрес", value)
                self.logger.data("qc_geo", str(qc_geo))
                self.logger.data("Регион", data.get('region', '-'))

        except Exception as e:
            self.logger.error(f"Ошибка geolocate сельская: {e}")

    def test_05_cache(self):
        """ТЕСТ 5: Сессионное кэширование"""
        self.logger.section("5. Кэширование")

        if not self.geocoder or not self.geocoder.is_configured():
            self.logger.fail("Geocoder не настроен")
            return

        try:
            # Первый вызов уже был в test_03 (55.7539, 37.6208)
            # Повторный вызов с близкими координатами (в пределах 10м -> тот же cache key)
            import time
            start = time.time()
            result = self.geocoder.geolocate(lat=55.7539, lon=37.6208)
            elapsed = time.time() - start

            self.logger.check(
                result is not None,
                f"Кэшированный результат получен за {elapsed:.4f} сек",
                "Кэшированный результат = None!"
            )

            # Кэш должен быть мгновенным (< 10ms)
            self.logger.check(
                elapsed < 0.01,
                f"Время из кэша: {elapsed:.4f} сек (< 10мс)",
                f"Слишком долго для кэша: {elapsed:.4f} сек"
            )

            # Очистка кэша
            self.geocoder.clear_cache()
            self.logger.success("clear_cache() выполнен")

        except Exception as e:
            self.logger.error(f"Ошибка теста кэша: {e}")

    def test_06_suggest(self):
        """ТЕСТ 6: Подсказки по адресу"""
        self.logger.section("6. Suggest")

        if not self.geocoder or not self.geocoder.is_configured():
            self.logger.fail("Geocoder не настроен")
            return

        try:
            results = self.geocoder.suggest("Москва Тверская", count=3)

            self.logger.check(
                isinstance(results, list),
                f"suggest вернул список ({len(results)} результатов)",
                f"suggest вернул не список: {type(results)}"
            )

            self.logger.check(
                len(results) > 0,
                f"Найдено {len(results)} подсказок",
                "Подсказки не найдены!"
            )

            if results:
                first = results[0]
                self.logger.data("Первая подсказка", first.get('value', '-'))

        except Exception as e:
            self.logger.error(f"Ошибка suggest: {e}")

    def test_07_find_by_id(self):
        """ТЕСТ 7: Поиск по кадастровому номеру"""
        self.logger.section("7. Find by ID")

        if not self.geocoder or not self.geocoder.is_configured():
            self.logger.fail("Geocoder не настроен")
            return

        try:
            # Кадастровый номер здания (ГУМ, Москва)
            result = self.geocoder.find_by_id("77:01:0001038:1065")

            # find_by_id может не найти конкретный КН -- это нормально
            if result:
                self.logger.success(f"find_by_id нашёл: {result.get('value', '-')}")
                data = result.get('data', {})
                self.logger.data("Регион", data.get('region', '-'))
            else:
                self.logger.warning("find_by_id не нашёл объект (допустимо для КН)")

        except Exception as e:
            self.logger.error(f"Ошибка find_by_id: {e}")

    def test_08_format_address(self):
        """ТЕСТ 8: Форматирование адреса по qc_geo"""
        self.logger.section("8. Format address by quality")

        if not self.geocoder:
            self.logger.fail("Geocoder не инициализирован")
            return

        try:
            # qc_geo 0 -- точный адрес
            result_exact = {
                'value': 'г Москва, ул Тверская, д 13',
                'data': {'qc_geo': '0'}
            }
            addr = self.geocoder.format_address_by_quality(result_exact)
            self.logger.check(
                addr == 'г Москва, ул Тверская, д 13',
                f"qc_geo=0: {addr}",
                f"qc_geo=0 неверный: {addr}"
            )

            # qc_geo 2 -- улица
            result_street = {
                'value': 'г Москва, ул Тверская',
                'data': {'qc_geo': '2'}
            }
            addr = self.geocoder.format_address_by_quality(result_street)
            self.logger.check(
                'Местоположение установлено относительно' in addr,
                f"qc_geo=2: {addr}",
                f"qc_geo=2 без 'относительно': {addr}"
            )

            # qc_geo 3 -- НП
            result_np = {
                'value': 'Московская обл, Серпуховский р-н',
                'data': {
                    'qc_geo': '3',
                    'region': 'Московская',
                    'region_type': 'обл',
                    'area': 'Серпуховский',
                    'area_type': 'р-н',
                    'city': None,
                    'settlement': None
                }
            }
            addr = self.geocoder.format_address_by_quality(result_np)
            self.logger.check(
                'Местоположение установлено относительно' in addr,
                f"qc_geo=3: {addr}",
                f"qc_geo=3 без 'относительно': {addr}"
            )

            # qc_geo 5 -- нет координат
            result_none = {
                'value': '',
                'data': {'qc_geo': '5'}
            }
            addr = self.geocoder.format_address_by_quality(result_none)
            self.logger.check(
                addr == '-',
                f"qc_geo=5: '{addr}' == '-'",
                f"qc_geo=5 не вернул '-': '{addr}'"
            )

        except Exception as e:
            self.logger.error(f"Ошибка format_address: {e}")
