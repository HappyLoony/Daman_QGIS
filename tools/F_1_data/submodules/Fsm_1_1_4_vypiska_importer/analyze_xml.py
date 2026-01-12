# -*- coding: utf-8 -*-
"""
Анализ проблемного XML файла 91_03_000000_321
"""
import xml.etree.ElementTree as ET
from pathlib import Path

xml_path = Path(__file__).parent / "Примеры выписок" / "ЗУ_Гоголь" / "91_03_000000_321.xml"

print(f"Анализ файла: {xml_path.name}")
print("=" * 80)

try:
    tree = ET.parse(str(xml_path))
    root = tree.getroot()

    # Найдем namespace
    ns = {}
    if root.tag.startswith('{'):
        ns_uri = root.tag.split('}')[0].strip('{')
        ns = {'ns': ns_uri}
        print(f"Namespace: {ns_uri}\n")

    # Поиск land_record
    land_records = root.findall('.//land_record') if not ns else root.findall('.//ns:land_record', ns)
    print(f"land_record элементов: {len(land_records)}")

    if land_records:
        lr = land_records[0]

        # Кадастровый номер
        cn = lr.find('cadastral_number') if not ns else lr.find('.//ns:cadastral_number', ns)
        if cn is not None:
            print(f"Кадастровый номер: {cn.text}")

        # Координаты contours_location
        contours_loc = lr.find('.//contours_location') if not ns else lr.find('.//ns:contours_location', ns)
        if contours_loc is not None:
            print(f"\ncontours_location найден")

            # Ищем entity_spatial внутри contours_location
            entities = contours_loc.findall('.//entity_spatial') if not ns else contours_loc.findall('.//ns:entity_spatial', ns)
            print(f"entity_spatial элементов в contours_location: {len(entities)}")

            if entities:
                first_entity = entities[0]
                # Считаем ordinates
                ordinates = first_entity.findall('.//ordinate') if not ns else first_entity.findall('.//ns:ordinate', ns)
                print(f"Первая entity_spatial содержит ordinates: {len(ordinates)}")

                # Проверяем spatials_elements
                spatials = contours_loc.findall('.//spatials_elements') if not ns else contours_loc.findall('.//ns:spatials_elements', ns)
                print(f"spatials_elements элементов: {len(spatials)}")

                if spatials:
                    # Считаем spatial_element внутри
                    spatial_els = spatials[0].findall('.//spatial_element') if not ns else spatials[0].findall('.//ns:spatial_element', ns)
                    print(f"spatial_element элементов в первом spatials_elements: {len(spatial_els)}")

                    if spatial_els:
                        # Первый spatial_element
                        se = spatial_els[0]
                        se_ordinates = se.findall('.//ordinate') if not ns else se.findall('.//ns:ordinate', ns)
                        print(f"Первый spatial_element содержит ordinates: {len(se_ordinates)}")
        else:
            print(f"\ncontours_location НЕ найден!")

            # Попробуем найти entity_spatial напрямую в land_record
            entities_direct = lr.findall('.//entity_spatial') if not ns else lr.findall('.//ns:entity_spatial', ns)
            print(f"entity_spatial напрямую в land_record: {len(entities_direct)}")

    # Поиск object_part
    object_parts = root.findall('.//object_part') if not ns else root.findall('.//ns:object_part', ns)
    print(f"\nobject_part элементов: {len(object_parts)}")

    if object_parts:
        print(f"Первый object_part:")
        op = object_parts[0]

        # Номер части
        num = op.find('.//number_record') if not ns else op.find('.//ns:number_record', ns)
        if num is not None:
            print(f"  number_record: {num.text}")

        # Координаты
        op_contours = op.find('.//contours_location') if not ns else op.find('.//ns:contours_location', ns)
        if op_contours is not None:
            op_entities = op_contours.findall('.//entity_spatial') if not ns else op_contours.findall('.//ns:entity_spatial', ns)
            print(f"  entity_spatial: {len(op_entities)}")
            if op_entities:
                op_ordinates = op_entities[0].findall('.//ordinate') if not ns else op_entities[0].findall('.//ns:ordinate', ns)
                print(f"  ordinates в первой entity: {len(op_ordinates)}")

    print("\n" + "=" * 80)
    print("ВЫВОД:")
    print(f"  land_record: {len(land_records)} шт")
    print(f"  object_part: {len(object_parts)} шт")

except Exception as e:
    print(f"ОШИБКА: {e}")
    import traceback
    traceback.print_exc()
