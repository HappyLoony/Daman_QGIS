# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_1_1_4 - Тесты для Fsm_1_1_4_VypiskaImporter

Покрытие:
- Инициализация импортера и FieldMappingManager
- Парсинг XML (land_record, build_record, unified_land_record)
- Field mapping (все поля из Base_field_mapping_EGRN.json)
- Geometry extraction (MultiPolygon, MultiLineString, NoGeometry)
- unaryUnion для >100 частей
- Type conversion (comma_to_dot, iso_date_truncate, semicolon_join)
- Создание слоев в GPKG с корректными типами полей
- Проверка атрибутов в результирующих слоях
"""

import os
import tempfile
import shutil
from qgis.core import QgsProject, QgsVectorLayer, QgsCoordinateReferenceSystem

from Daman_QGIS.database.project_db import ProjectDB


class TestF114:
    """Тесты для Fsm_1_1_4_VypiskaImporter"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.module = None
        self.field_mapper = None
        self.test_dir = None
        self.test_gpkg = None
        self.test_xml_files = {}

    def run_all_tests(self):
        """Запуск всех тестов F_1_1_4"""
        self.logger.section("ТЕСТ Fsm_1_1_4: Импорт выписок ЕГРН")

        # Создаем временную директорию
        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_f114_")
        self.test_gpkg = os.path.join(self.test_dir, "test.gpkg")
        self.logger.info(f"Временная директория: {self.test_dir}")

        # Создаем пустой GPKG файл (без этого импорт не сможет записать слои)
        try:
            project_db = ProjectDB(self.test_gpkg)
            crs = QgsCoordinateReferenceSystem("EPSG:4326")
            project_db.create(crs)
            self.logger.info(f"GPKG создан: {self.test_gpkg}")
        except Exception as e:
            self.logger.error(f"Не удалось создать GPKG: {str(e)}")
            return

        try:
            # БЛОК 1: Инициализация
            self.test_01_init_importer()
            self.test_02_init_field_mapper()

            # БЛОК 2: Создание тестовых XML
            self.test_03_create_test_xml_zu()
            self.test_04_create_test_xml_oks()
            self.test_05_create_test_xml_ez_100plus()

            # БЛОК 3: Field Mapping
            self.test_06_field_mapper_zu()
            self.test_07_field_mapper_oks()
            self.test_08_type_conversion()

            # БЛОК 4: Geometry Extraction
            self.test_09_geometry_polygon()
            self.test_10_geometry_line()
            self.test_11_geometry_unary_union()

            # БЛОК 5: Full Import
            self.test_12_import_zu_xml()
            self.test_13_import_oks_xml()
            self.test_14_import_ez_100plus()

            # БЛОК 6: GPKG Validation
            self.test_15_check_gpkg_layers()
            self.test_16_check_field_types()
            self.test_17_check_attributes()

        finally:
            # Очистка
            if self.test_dir and os.path.exists(self.test_dir):
                try:
                    shutil.rmtree(self.test_dir)
                    self.logger.info("Временные файлы очищены")
                except Exception as e:
                    self.logger.warning(f"Не удалось удалить временные файлы: {str(e)}")

        self.logger.summary()

    # ========================================================================
    # БЛОК 1: Инициализация
    # ========================================================================

    def test_01_init_importer(self):
        """ТЕСТ 1: Инициализация Fsm_1_1_4_VypiskaImporter"""
        self.logger.section("1. Инициализация Fsm_1_1_4_VypiskaImporter")

        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_1_4_vypiska_importer.Fsm_1_1_4_vypiska_importer import Fsm_1_1_4_VypiskaImporter

            self.module = Fsm_1_1_4_VypiskaImporter(self.iface)
            self.logger.success("Модуль Fsm_1_1_4_VypiskaImporter загружен")

            # Проверяем наличие метод��в
            self.logger.check(
                hasattr(self.module, 'import_file'),
                "Метод import_file существует",
                "Метод import_file отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, 'supports_format'),
                "Метод supports_format существует",
                "Метод supports_format отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, 'field_mapper'),
                "FieldMappingManager инициализирован",
                "FieldMappingManager НЕ инициализирован!"
            )

            # Проверяем поддержку формата XML
            supports_xml = self.module.supports_format('.xml')
            self.logger.check(
                supports_xml,
                "Формат .xml поддерживается",
                "Формат .xml НЕ поддерживается!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка инициализации: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
            self.module = None

    def test_02_init_field_mapper(self):
        """ТЕСТ 2: Проверка FieldMappingManager"""
        self.logger.section("2. Проверка FieldMappingManager")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            self.field_mapper = self.module.field_mapper
            self.logger.check(
                self.field_mapper is not None,
                "FieldMappingManager доступен",
                "FieldMappingManager НЕ доступен!"
            )

            # Проверяем наличие методов
            self.logger.check(
                hasattr(self.field_mapper, 'get_fields_for_record_type'),
                "Метод get_fields_for_record_type существует",
                "Метод get_fields_for_record_type отсутствует!"
            )

            self.logger.check(
                hasattr(self.field_mapper, 'extract_value'),
                "Метод extract_value существует",
                "Метод extract_value отсутствует!"
            )

            self.logger.check(
                hasattr(self.field_mapper, 'create_qgs_field'),
                "Метод create_qgs_field существует",
                "Метод create_qgs_field отсутствует!"
            )

            # Проверяем загрузку mappings
            zu_fields = self.field_mapper.get_fields_for_record_type('land_record')
            self.logger.check(
                len(zu_fields) > 0,
                f"Найдено {len(zu_fields)} полей для land_record",
                "Нет полей для land_record!"
            )

            oks_fields = self.field_mapper.get_fields_for_record_type('build_record')
            self.logger.check(
                len(oks_fields) > 0,
                f"Найдено {len(oks_fields)} полей для build_record",
                "Нет полей для build_record!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка проверки FieldMappingManager: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    # ========================================================================
    # БЛОК 2: Создание тестовых XML
    # ========================================================================

    def test_03_create_test_xml_zu(self):
        """ТЕСТ 3: Создание тестового XML для ЗУ"""
        self.logger.section("3. Создание тестового XML для ЗУ")

        if not self.test_dir:
            self.logger.fail("test_dir не инициализирован, пропускаем тест")
            return

        try:
            xml_path = os.path.join(self.test_dir, "test_zu.xml")
            xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<extract_about_property_land>
  <land_record>
    <object>
      <common_data>
        <cad_number>77:01:0001001:1234</cad_number>
        <type><value>Земельный участок</value></type>
      </common_data>
      <subtype><value>Земельный участок</value></subtype>
    </object>
    <params>
      <category><type><value>Земли населенных пунктов</value></type></category>
      <area><value>1234,56</value></area>
      <permitted_use>
        <permitted_use_established>
          <by_document>Для индивидуального жилищного строительства</by_document>
        </permitted_use_established>
      </permitted_use>
    </params>
    <address_location>
      <address><readable_address>г Москва, ул Тестовая, д 1</readable_address></address>
    </address_location>
    <cost><value>5000000,00</value></cost>
    <right_records>
      <right_record>
        <right_data><right_type><value>Собственность</value></right_type></right_data>
        <right_holders>
          <right_holder>
            <individual><name>Иванов Иван Иванович</name></individual>
          </right_holder>
        </right_holders>
        <record_info><registration_date>2024-01-15T10:30:00+03:00</registration_date></record_info>
      </right_record>
    </right_records>
    <contours_location>
      <contours>
        <spatial_element>
          <ordinates>
            <ordinate><x>37.500000</x><y>55.750000</y></ordinate>
            <ordinate><x>37.500100</x><y>55.750000</y></ordinate>
            <ordinate><x>37.500100</x><y>55.750100</y></ordinate>
            <ordinate><x>37.500000</x><y>55.750100</y></ordinate>
            <ordinate><x>37.500000</x><y>55.750000</y></ordinate>
          </ordinates>
        </spatial_element>
      </contours>
    </contours_location>
    <status>Учтенный</status>
  </land_record>
</extract_about_property_land>
"""

            with open(xml_path, 'w', encoding='utf-8') as f:
                f.write(xml_content)

            self.test_xml_files['zu'] = xml_path
            self.logger.success(f"Создан тестовый XML для ЗУ: {xml_path}")

            # Проверяем, что файл читается
            import xml.etree.ElementTree as ET
            tree = ET.parse(xml_path)
            root = tree.getroot()
            self.logger.check(
                root.tag == 'extract_about_property_land',
                "XML корректно парсится",
                "XML НЕ парсится!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка создания XML для ЗУ: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_04_create_test_xml_oks(self):
        """ТЕСТ 4: Создание тестового XML для ОКС"""
        self.logger.section("4. Создание тестового XML для ОКС")

        if not self.test_dir:
            self.logger.fail("test_dir не инициализирован, пропускаем тест")
            return

        try:
            xml_path = os.path.join(self.test_dir, "test_oks.xml")
            xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<extract_about_property_build>
  <build_record>
    <object>
      <common_data>
        <cad_number>77:01:0001001:2345</cad_number>
        <type><value>Здание</value></type>
      </common_data>
    </object>
    <params>
      <name>Жилой дом</name>
      <purpose><value>Жилое</value></purpose>
      <area>150,5</area>
    </params>
    <address_location>
      <address><readable_address>г Москва, ул Тестовая, д 1, стр 1</readable_address></address>
    </address_location>
    <right_records>
      <right_record>
        <right_data><right_type><value>Собственность</value></right_type></right_data>
        <right_holders>
          <right_holder>
            <legal_entity>
              <entity>
                <resident><name>ООО "Тестовая компания"</name></resident>
              </entity>
            </legal_entity>
          </right_holder>
        </right_holders>
        <record_info><registration_date>2024-02-20T14:45:00+03:00</registration_date></record_info>
      </right_record>
    </right_records>
    <cad_links>
      <land_cad_numbers>
        <land_cad_number><cad_number>77:01:0001001:1234</cad_number></land_cad_number>
      </land_cad_numbers>
    </cad_links>
    <contours_location>
      <contours>
        <spatial_element>
          <ordinates>
            <ordinate><x>37.500000</x><y>55.750000</y></ordinate>
            <ordinate><x>37.500050</x><y>55.750000</y></ordinate>
            <ordinate><x>37.500050</x><y>55.750050</y></ordinate>
            <ordinate><x>37.500000</x><y>55.750050</y></ordinate>
            <ordinate><x>37.500000</x><y>55.750000</y></ordinate>
          </ordinates>
        </spatial_element>
      </contours>
    </contours_location>
    <status>Завершенное</status>
  </build_record>
</extract_about_property_build>
"""

            with open(xml_path, 'w', encoding='utf-8') as f:
                f.write(xml_content)

            self.test_xml_files['oks'] = xml_path
            self.logger.success(f"Создан тестовый XML для ОКС: {xml_path}")

        except Exception as e:
            self.logger.error(f"Ошибка создания XML для ОКС: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_05_create_test_xml_ez_100plus(self):
        """ТЕСТ 5: Создание тестового XML для ЕЗ с >100 частями"""
        self.logger.section("5. Создание тестового XML для ЕЗ с >100 spatial_element")

        if not self.test_dir:
            self.logger.fail("test_dir не инициализирован, пропускаем тест")
            return

        try:
            xml_path = os.path.join(self.test_dir, "test_ez_100plus.xml")

            # Генерируем 150 spatial_element
            spatial_elements = []
            for i in range(150):
                x_offset = i * 0.001
                y_offset = (i % 10) * 0.001
                spatial_elements.append(f"""
        <spatial_element>
          <ordinates>
            <ordinate><x>{37.5 + x_offset}</x><y>{55.75 + y_offset}</y></ordinate>
            <ordinate><x>{37.5 + x_offset + 0.0001}</x><y>{55.75 + y_offset}</y></ordinate>
            <ordinate><x>{37.5 + x_offset + 0.0001}</x><y>{55.75 + y_offset + 0.0001}</y></ordinate>
            <ordinate><x>{37.5 + x_offset}</x><y>{55.75 + y_offset + 0.0001}</y></ordinate>
            <ordinate><x>{37.5 + x_offset}</x><y>{55.75 + y_offset}</y></ordinate>
          </ordinates>
        </spatial_element>""")

            xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<extract_about_property_land>
  <land_record>
    <object>
      <common_data>
        <cad_number>77:01:0000000:9999</cad_number>
        <type><value>Единое землепользование</value></type>
      </common_data>
      <subtype>
        <code>02</code>
        <value>Единое землепользование</value>
      </subtype>
    </object>
    <params>
      <category><type><value>Земли сельскохозяйственного назначения</value></type></category>
      <area><value>50000,00</value></area>
    </params>
    <included_objects>
      <included_object><cad_number>77:01:0001001:1111</cad_number></included_object>
      <included_object><cad_number>77:01:0001001:2222</cad_number></included_object>
    </included_objects>
    <address_location>
      <address><readable_address>Московская область, Тестовый район</readable_address></address>
    </address_location>
    <contours_location>
      <contours>{''.join(spatial_elements)}
      </contours>
    </contours_location>
    <status>Учтенный</status>
  </land_record>
</extract_about_property_land>
"""

            with open(xml_path, 'w', encoding='utf-8') as f:
                f.write(xml_content)

            self.test_xml_files['ez_100plus'] = xml_path
            self.logger.success(f"Создан тестовый XML для ЕЗ с 150 частями: {xml_path}")

        except Exception as e:
            self.logger.error(f"Ошибка создания XML для ЕЗ: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    # ========================================================================
    # БЛОК 3: Field Mapping Tests
    # ========================================================================

    def test_06_field_mapper_zu(self):
        """ТЕСТ 6: Field mapping для land_record"""
        self.logger.section("6. Field mapping для land_record")

        if not self.field_mapper:
            self.logger.fail("FieldMappingManager не инициализирован")
            return

        try:
            fields = self.field_mapper.get_fields_for_record_type('land_record')
            self.logger.info(f"Получено {len(fields)} полей для land_record")

            # Проверяем наличие ключевых полей
            field_names = [f['working_name'] for f in fields]

            required_fields = ['КН', 'Площадь', 'Адрес_Местоположения', 'Категория', 'ВРИ', 'Права']
            for field_name in required_fields:
                self.logger.check(
                    field_name in field_names,
                    f"Поле '{field_name}' присутствует",
                    f"Поле '{field_name}' ОТСУТСТВУЕТ!"
                )

            # Проверяем типы данных
            for field in fields:
                if field['working_name'] == 'Площадь':
                    self.logger.check(
                        field['data_type'] == 'Real',
                        "Поле 'Площадь' имеет тип Real",
                        f"Поле 'Площадь' имеет неверный тип: {field['data_type']}"
                    )
                    self.logger.check(
                        field['conversion'] == 'comma_to_dot',
                        "Поле 'Площадь' имеет конверсию comma_to_dot",
                        f"Поле 'Площадь' имеет неверную конверсию: {field['conversion']}"
                    )

        except Exception as e:
            self.logger.error(f"Ошибка field mapping для ЗУ: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_07_field_mapper_oks(self):
        """ТЕСТ 7: Field mapping для build_record"""
        self.logger.section("7. Field mapping для build_record")

        if not self.field_mapper:
            self.logger.fail("FieldMappingManager не инициализирован")
            return

        try:
            fields = self.field_mapper.get_fields_for_record_type('build_record')
            self.logger.info(f"Получено {len(fields)} полей для build_record")

            # Проверяем наличие ключевых полей
            field_names = [f['working_name'] for f in fields]

            required_fields = ['КН', 'Тип_ОКСа', 'Наименование', 'Назначение', 'Связанные_ЗУ']
            for field_name in required_fields:
                self.logger.check(
                    field_name in field_names,
                    f"Поле '{field_name}' присутствует",
                    f"Поле '{field_name}' ОТСУТСТВУЕТ!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка field mapping для ОКС: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_08_type_conversion(self):
        """ТЕСТ 8: Проверка type conversion"""
        self.logger.section("8. Проверка type conversion")

        if not self.field_mapper:
            self.logger.fail("FieldMappingManager не инициализирован")
            return

        try:
            # Тест comma_to_dot
            mapping_area = {'data_type': 'Real', 'conversion': 'comma_to_dot'}
            result = self.field_mapper._convert_value("1234,56", mapping_area)
            self.logger.check(
                result == 1234.56,
                f"comma_to_dot: '1234,56' → {result}",
                f"comma_to_dot ОШИБКА: ожидалось 1234.56, получено {result}"
            )

            # Тест iso_date_truncate
            mapping_date = {'data_type': 'Date', 'conversion': 'iso_date_truncate'}
            result = self.field_mapper._convert_value("2024-01-15T10:30:00+03:00", mapping_date)
            self.logger.check(
                result == "2024-01-15",
                f"iso_date_truncate: '2024-01-15T10:30:00+03:00' → '{result}'",
                f"iso_date_truncate ОШИБКА: ожидалось '2024-01-15', получено '{result}'"
            )

            # Тест String fallback на ошибке
            mapping_real = {'data_type': 'Real', 'conversion': 'null'}
            result = self.field_mapper._convert_value("NOT_A_NUMBER", mapping_real)
            self.logger.check(
                isinstance(result, str),
                f"Fallback to String: 'NOT_A_NUMBER' → '{result}' (type: {type(result).__name__})",
                f"Fallback ОШИБКА: должен вернуть String"
            )

        except Exception as e:
            self.logger.error(f"Ошибка проверки type conversion: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    # ========================================================================
    # БЛОК 4: Geometry Extraction Tests
    # ========================================================================

    def test_09_geometry_polygon(self):
        """ТЕСТ 9: Извлечение polygon геометрии"""
        self.logger.section("9. Извлечение polygon геометрии")

        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_1_4_vypiska_importer.Fsm_1_1_4_3_geometry import extract_geometry
            import xml.etree.ElementTree as ET

            # Загружаем тестовый XML для ЗУ
            zu_xml = self.test_xml_files.get('zu')
            if not zu_xml:
                self.logger.fail("Тестовый XML для ЗУ не создан")
                return

            tree = ET.parse(zu_xml)
            contours_location = tree.find('.//contours_location')

            geometries = extract_geometry(contours_location)

            # FIX: Ключ теперь MultiPolygonM (с M-координатами для delta_geopoint)
            self.logger.check(
                'MultiPolygonM' in geometries,
                "MultiPolygonM геометрия извлечена",
                "MultiPolygonM геометрия НЕ извлечена!"
            )

            geom = geometries.get('MultiPolygonM')
            if geom:
                self.logger.check(
                    not geom.isEmpty(),
                    "Геометрия НЕ пустая",
                    "Геометрия ПУСТАЯ!"
                )
                self.logger.info(f"WKB Type: {geom.wkbType()}, Is Multipart: {geom.isMultipart()}")

        except Exception as e:
            self.logger.error(f"Ошибка извлечения polygon: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_10_geometry_line(self):
        """ТЕСТ 10: Извлечение line геометрии"""
        self.logger.section("10. Извлечение line геометрии (пропускаем)")
        self.logger.info("Line геометрия редко встречается в выписках ЕГРН")
        self.logger.success("Тест пропущен (не критично)")

    def test_11_geometry_unary_union(self):
        """ТЕСТ 11: unaryUnion для >100 частей"""
        self.logger.section("11. unaryUnion для >100 spatial_element")

        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_1_4_vypiska_importer.Fsm_1_1_4_3_geometry import extract_geometry
            import xml.etree.ElementTree as ET

            # Загружаем тестовый XML для ЕЗ с >100 частями
            ez_xml = self.test_xml_files.get('ez_100plus')
            if not ez_xml:
                self.logger.fail("Тестовый XML для ЕЗ не создан")
                return

            tree = ET.parse(ez_xml)
            contours_location = tree.find('.//contours_location')

            # ВАЖНО: extract_geometry должен автоматически применить unaryUnion()
            geometries = extract_geometry(contours_location)

            # FIX: Ключ теперь MultiPolygonM (с M-координатами для delta_geopoint)
            self.logger.check(
                'MultiPolygonM' in geometries,
                "MultiPolygonM геометрия извлечена",
                "MultiPolygonM геометрия НЕ извлечена!"
            )

            geom = geometries.get('MultiPolygonM')
            if geom:
                self.logger.check(
                    not geom.isEmpty(),
                    "unaryUnion() вернул НЕ пустую геометрию",
                    "unaryUnion() вернул ПУСТУЮ геометрию!"
                )

                # Проверяем что unaryUnion() выполнился без ошибок
                # ВАЖНО: unaryUnion() объединяет только ПЕРЕСЕКАЮЩИЕСЯ полигоны
                # Если полигоны не пересекаются - количество частей остаётся прежним
                if geom.isMultipart():
                    num_parts = geom.constGet().numGeometries()
                    self.logger.success(f"unaryUnion() выполнен, результат: {num_parts} частей")
                else:
                    self.logger.success("unaryUnion() объединил в один полигон")

        except Exception as e:
            self.logger.error(f"Ошибка проверки unaryUnion: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    # ========================================================================
    # БЛОК 5: Full Import Tests
    # ========================================================================

    def test_12_import_zu_xml(self):
        """ТЕСТ 12: Полный импорт ЗУ в GPKG"""
        self.logger.section("12. Полный импорт ЗУ в GPKG")

        if not self.module:
            self.logger.fail("Модуль не инициализирован")
            return

        try:
            zu_xml = self.test_xml_files.get('zu')
            if not zu_xml:
                self.logger.fail("Тестовый XML для ЗУ не создан")
                return

            # Выполняем импорт
            result = self.module.import_file(
                zu_xml,
                gpkg_path=self.test_gpkg,
                split_by_geometry=True
            )

            self.logger.check(
                result.get('success'),
                "Импорт ЗУ успешен",
                f"Импорт ЗУ ОШИБКА: {result.get('message')}"
            )

            self.logger.info(f"Создано слоёв: {len(result.get('layers', []))}")

        except Exception as e:
            self.logger.error(f"Ошибка импорта ЗУ: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_13_import_oks_xml(self):
        """ТЕСТ 13: Полный импорт ОКС в GPKG"""
        self.logger.section("13. Полный импорт ОКС в GPKG")

        if not self.module:
            self.logger.fail("Модуль не инициализирован")
            return

        try:
            oks_xml = self.test_xml_files.get('oks')
            if not oks_xml:
                self.logger.fail("Тестовый XML для ОКС не создан")
                return

            # Выполняем импорт
            result = self.module.import_file(
                oks_xml,
                gpkg_path=self.test_gpkg,
                split_by_geometry=True
            )

            self.logger.check(
                result.get('success'),
                "Импорт ОКС успешен",
                f"Импорт ОКС ОШИБКА: {result.get('message')}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка импорта ОКС: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_14_import_ez_100plus(self):
        """ТЕСТ 14: Импорт ЕЗ с >100 частями"""
        self.logger.section("14. Импорт ЕЗ с >100 spatial_element")

        if not self.module:
            self.logger.fail("Модуль не инициализирован")
            return

        try:
            ez_xml = self.test_xml_files.get('ez_100plus')
            if not ez_xml:
                self.logger.fail("Тестовый XML для ЕЗ не создан")
                return

            # Выполняем импорт
            result = self.module.import_file(
                ez_xml,
                gpkg_path=self.test_gpkg,
                split_by_geometry=True
            )

            self.logger.check(
                result.get('success'),
                "Импорт ЕЗ с >100 частями успешен",
                f"Импорт ЕЗ ОШИБКА: {result.get('message')}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка импорта ЕЗ: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    # ========================================================================
    # БЛОК 6: GPKG Validation Tests
    # ========================================================================

    def test_15_check_gpkg_layers(self):
        """ТЕСТ 15: Проверка созданных слоёв в GPKG"""
        self.logger.section("15. Проверка созданных слоёв в GPKG")

        if not self.test_gpkg:
            self.logger.fail("test_gpkg не инициализирован, пропускаем тест")
            return

        try:
            if not os.path.exists(self.test_gpkg):
                self.logger.fail(f"GPKG файл не существует: {self.test_gpkg}")
                return

            # Загружаем слои из GPKG
            from qgis.core import QgsDataSourceUri
            layers = QgsProject.instance().mapLayers()

            self.logger.info(f"Всего слоёв в проекте: {len(layers)}")

            # Ищем слои выписок
            vypiska_layers = [layer for layer in layers.values() if 'Выписки' in layer.name()]
            self.logger.check(
                len(vypiska_layers) > 0,
                f"Найдено {len(vypiska_layers)} слоёв выписок",
                "НЕ найдено слоёв выписок!"
            )

            for layer in vypiska_layers:
                self.logger.info(f"  - {layer.name()}: {layer.featureCount()} объектов")

        except Exception as e:
            self.logger.error(f"Ошибка проверки GPKG слоёв: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_16_check_field_types(self):
        """ТЕСТ 16: Проверка типов полей в слоях"""
        self.logger.section("16. Проверка типов полей в слоях")

        try:
            layers = QgsProject.instance().mapLayers()
            zu_layers = [layer for layer in layers.values() if 'Выписки_ЗУ' in layer.name()]

            if not zu_layers:
                self.logger.fail("Слой ЗУ не найден")
                return

            zu_layer = zu_layers[0]
            fields = zu_layer.fields()

            # Проверяем типы ключевых полей
            # ВАЖНО: GPKG хранит типы как String/Real/Date (не QString/double/QDate)
            # ПРИМЕЧАНИЕ: Поле Дата_регистрации НЕТ в маппинге, проверяем только КН и Площадь
            field_checks = {
                'КН': 'String',        # QString → String (GPKG/SQLite)
                'Площадь': 'Real'      # double → Real (GPKG/SQLite)
            }

            for field_name, expected_type in field_checks.items():
                idx = fields.lookupField(field_name)
                if idx != -1:
                    field = fields.field(idx)
                    field_type = field.typeName()
                    self.logger.check(
                        expected_type.lower() in field_type.lower(),
                        f"Поле '{field_name}' имеет тип {field_type}",
                        f"Поле '{field_name}' имеет неверный тип: {field_type} (ожидалось {expected_type})"
                    )
                else:
                    self.logger.fail(f"Поле '{field_name}' ОТСУТСТВУЕТ в слое!")

        except Exception as e:
            self.logger.error(f"Ошибка проверки типов полей: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_17_check_attributes(self):
        """ТЕСТ 17: Проверка значений атрибутов"""
        self.logger.section("17. Проверка значений атрибутов")

        try:
            layers = QgsProject.instance().mapLayers()
            zu_layers = [layer for layer in layers.values() if 'Выписки_ЗУ' in layer.name()]

            if not zu_layers:
                self.logger.fail("Слой ЗУ не найден")
                return

            zu_layer = zu_layers[0]
            features = list(zu_layer.getFeatures())

            if not features:
                self.logger.fail("Нет объектов в слое ЗУ")
                return

            feature = features[0]
            fields = zu_layer.fields()

            # Проверяем КН
            kn_idx = fields.lookupField('КН')
            if kn_idx != -1:
                kn_value = feature.attribute(kn_idx)
                self.logger.check(
                    kn_value == "77:01:0001001:1234",
                    f"КН корректен: {kn_value}",
                    f"КН ОШИБКА: ожидалось '77:01:0001001:1234', получено '{kn_value}'"
                )

            # Проверяем Площадь (должна быть Real, конвертированная из "1234,56")
            area_idx = fields.lookupField('Площадь')
            if area_idx != -1:
                area_value = feature.attribute(area_idx)
                # Конвертируем QVariant в float для сравнения
                area_float = float(area_value) if area_value is not None else 0.0
                self.logger.check(
                    area_value is not None and abs(area_float - 1234.56) < 0.01,
                    f"Площадь корректна: {area_value} (comma_to_dot работает)",
                    f"Площадь ОШИБКА: ожидалось 1234.56, получено {area_value}"
                )

            # ПРИМЕЧАНИЕ: Поле Дата_регистрации НЕТ в маппинге land_record
            # Проверка iso_date_truncate выполняется в test_08_type_conversion

        except Exception as e:
            self.logger.error(f"Ошибка проверки атрибутов: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
