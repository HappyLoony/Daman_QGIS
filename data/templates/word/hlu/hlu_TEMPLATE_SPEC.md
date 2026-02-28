# Спецификация шаблона hlu.docx

Единый шаблон для документа "Характеристика образуемых лесных участков" (ХЛУ).

**Источники данных:**
- **Le_4_*** (F_4_2) - расширенная версия с 24 полями лесной таксации
- **L_3_4_*/L_3_6_*** - базовая версия ЗПР (при отсутствии Le_4_*)

## Общая структура документа

```
Приложение {{ prilozhenie_nomer }}

{{ nazvanie_dokumenta }}

Вид использования: {{ vid_ispolzovaniya }}
Цель предоставления: {{ cel_predostavleniya }}

{% for rayon in rayony %}
---
РАЗДЕЛ: Характеристика образуемых лесных участков в {{ rayon.nazvanie }}

[Таблица 1]
[Таблица 2]
[Таблица 3]
[Таблица 4]
[Таблица 5]
[Таблица 6]
[Раздел ОЗУ]
{% endfor %}
```

## Структура контекста rayon

```python
{
    "nazvanie": str,           # Название МО (муниципального округа)
    "oblast": str,             # Область
    "lesnichestvo_name": str,  # Основное лесничество

    # Таблицы
    "table1": {                # Распределение по целевому назначению
        "zashitnye": [...],
        "ekspluatacionnye": [...]
    },
    "table2": [...],           # 16 видов разрешенного использования
    "table3": {...},           # Распределение земель
    "table4": {                # Характеристика лесного участка
        "groups": [...],
        "itogo": {...}
    },
    "table5": [...],           # Средние таксационные показатели
    "table6": {                # Виды и объемы использования
        "rows": [...],
        "itogo_ploshad": str
    },

    # ОЗУ
    "ozu": {
        "est": bool,
        "text": str,
        "types": [...]
    }
}
```

## Таблица 1: Распределение лесов по целевому назначению

**Заголовок:** Местоположение и границы проектируемых лесных участков (распределение кварталов по видам целевого назначения)

**Колонки:** Местоположение | Лесничество | Участковое лесничество | Номер квартала | Номер части выдела

```jinja2
{% for kat in rayon.table1.zashitnye %}
{{ kat.kategoriya }}
{% for row in kat.rows %}
{{ row.mestopolozhenie }} | {{ row.lesnichestvo }} | {{ row.uch_lesnichestvo }} | {{ row.kvartal }} | {{ row.vydely }}
{% endfor %}
{% endfor %}

Эксплуатационные леса
{% for kat in rayon.table1.ekspluatacionnye %}
{% for row in kat.rows %}
...
{% endfor %}
{% endfor %}
```

**Структура kategoriya:**
```python
{
    "kategoriya": str,  # "Защитные леса" / подкатегория
    "rows": [
        {
            "mestopolozhenie": str,
            "lesnichestvo": str,
            "uch_lesnichestvo": str,
            "kvartal": str,
            "vydely": str  # "1, 2, 5" - через запятую
        }
    ]
}
```

## Таблица 2: Распределение кварталов по видам разрешенного использования

**Заголовок:** Распределение кварталов проектируемого лесного участка по видам разрешенного использования лесов

**Колонки:** Участковое лесничество | Номер квартала

```jinja2
{% for vid in rayon.table2 %}
{{ vid.nomer }}. {{ vid.vid }}
{% for row in vid.rows %}
{{ row.uch_lesnichestvo }} | {{ row.kvartaly }}
{% endfor %}
{% endfor %}
```

**Структура vid (16 видов):**
```python
{
    "nomer": str,  # "1" - "16"
    "vid": str,    # Название вида использования
    "rows": [
        {
            "uch_lesnichestvo": str,
            "kvartaly": str  # "12, 15, 18" - через запятую
        }
    ]
}
```

**16 видов разрешенного использования:**
1. Заготовка древесины
2. Заготовка живицы
3. Заготовка и сбор недревесных лесных ресурсов
4. Заготовка пищевых лесных ресурсов и сбор лекарственных растений
5. Осуществление видов деятельности в сфере охотничьего хозяйства
6. Ведение сельского хозяйства
7. Осуществление научно-исследовательской деятельности, образовательной деятельности
8. Осуществление рекреационной деятельности
9. Создание лесных плантаций и их эксплуатация
10. Выращивание лесных плодовых, ягодных, декоративных растений, лекарственных растений
11. Выращивание посадочного материала лесных растений (саженцев, сеянцев)
12. Выполнение работ по геологическому изучению недр, разработка месторождений полезных ископаемых
13. Строительство и эксплуатация водохранилищ и иных искусственных водных объектов
14. Строительство, реконструкция, эксплуатация линейных объектов
15. Переработка древесины и иных лесных ресурсов
16. Осуществление религиозной деятельности

## Таблица 3: Распределение земель

**Заголовок:** Распределение земель на проектируемом лесном участке

**Структура:**

| Категория | Ключ контекста |
|-----------|----------------|
| Общая площадь | `rayon.table3.obshaya_ploshad` |
| **Лесные земли:** | |
| - занятые насаждениями | `rayon.table3.lesnye_zanyatye` |
| - лесные культуры | `rayon.table3.lesnye_kultury` |
| - питомники | `rayon.table3.lesnye_pitomniki` |
| - не занятые насаждениями | `rayon.table3.lesnye_ne_zanyatye` |
| Итого лесных земель | `rayon.table3.lesnye_itogo` |
| **Нелесные земли:** | |
| - дороги | `rayon.table3.nelesnye_dorogi` |
| - просеки | `rayon.table3.nelesnye_proseki` |
| - болота | `rayon.table3.nelesnye_bolota` |
| - другие | `rayon.table3.nelesnye_drugie` |
| Итого нелесных земель | `rayon.table3.nelesnye_itogo` |

## Таблица 4: Характеристика проектируемого лесного участка (ГЛАВНАЯ)

**Заголовок:** Характеристика проектируемого лесного участка

**Колонки:** N на чертеже | Целевое назначение | Лесничество | Уч. лесничество | Квартал | Выдел | Состав | Площадь/запас | молодняки | средневозр. | приспев. | спелые

```jinja2
{% for celevoe_group in rayon.table4.groups %}
{% for lesn_group in celevoe_group.lesnichestvo_groups %}
{% for uch_group in lesn_group.uch_groups %}
{% for row in uch_group.rows %}
{{ row.nomer }} | {{ celevoe_group.celevoe }} | {{ lesn_group.lesnichestvo }} | {{ uch_group.uch_lesnichestvo }} | {{ row.kvartal }} | {{ row.vydel }} | {{ row.sostav }} | {{ row.ploshad_zapas }} | {{ row.molodnyaki }} | {{ row.srednevozrastnye }} | {{ row.prispevayushie }} | {{ row.spelye }}
{% endfor %}
Всего по {{ celevoe_group.celevoe|lower }} лесам {{ uch_group.uch_lesnichestvo }} уч. лесничества: | | | | | | | {{ uch_group.subtotal.ploshad_zapas }} | {{ uch_group.subtotal.molodnyaki }} | {{ uch_group.subtotal.srednevozrastnye }} | {{ uch_group.subtotal.prispevayushie }} | {{ uch_group.subtotal.spelye }}
{% endfor %}
{% endfor %}
{% endfor %}

ИТОГО: | | | | | | | {{ rayon.table4.itogo.ploshad_zapas }} | {{ rayon.table4.itogo.molodnyaki }} | {{ rayon.table4.itogo.srednevozrastnye }} | {{ rayon.table4.itogo.prispevayushie }} | {{ rayon.table4.itogo.spelye }}
```

**Структура table4:**
```python
{
    "groups": [
        {
            "celevoe": str,  # "Защитные леса" / "Эксплуатационные леса"
            "lesnichestvo_groups": [
                {
                    "lesnichestvo": str,
                    "uch_groups": [
                        {
                            "uch_lesnichestvo": str,
                            "rows": [
                                {
                                    "nomer": str,           # ID на чертеже
                                    "kvartal": str,
                                    "vydel": str,
                                    "sostav": str,          # "6С2Е2Б"
                                    "ploshad_zapas": str,   # "0,4535 / 15"
                                    "molodnyaki": str,      # "0,1234 / 5" или "-"
                                    "srednevozrastnye": str,
                                    "prispevayushie": str,
                                    "spelye": str
                                }
                            ],
                            "subtotal": {
                                "ploshad_zapas": str,
                                "molodnyaki": str,
                                "srednevozrastnye": str,
                                "prispevayushie": str,
                                "spelye": str
                            }
                        }
                    ]
                }
            ]
        }
    ],
    "itogo": {
        "ploshad_zapas": str,
        "molodnyaki": str,
        "srednevozrastnye": str,
        "prispevayushie": str,
        "spelye": str
    }
}
```

## Таблица 5: Средние таксационные показатели насаждений

**Заголовок:** Средние таксационные показатели насаждений на проектируемом лесном участке

**Колонки:** Целевое назначение | Лесничество/Уч.лесничество | Квартал/выдел | Хозяйство | Состав | Возраст | Бонитет | Полнота | молодняки | средневозр. | приспев. | спелые

```jinja2
{% for row in rayon.table5 %}
{{ row.celevoe }} | {{ row.lesn_uch }} | {{ row.kvartal_vydel }} | {{ row.hozyajstvo }} | {{ row.sostav }} | {{ row.vozrast }} | {{ row.bonitet }} | {{ row.polnota }} | {{ row.zapas_molodnyaki }} | {{ row.zapas_srednevozr }} | {{ row.zapas_prispev }} | {{ row.zapas_spelye }}
{% endfor %}
```

**Структура row:**
```python
{
    "celevoe": str,           # Целевое назначение
    "lesn_uch": str,          # "Лесничество / Уч.лесничество"
    "kvartal_vydel": str,     # "12 / 5"
    "hozyajstvo": str,        # "Хвойное" / "Лиственное" / "Нелесное"
    "sostav": str,            # "6С2Е2Б"
    "vozrast": str,           # "85"
    "bonitet": str,           # "II"
    "polnota": str,           # "0,7"
    "zapas_molodnyaki": str,  # Запас или "-"
    "zapas_srednevozr": str,
    "zapas_prispev": str,
    "zapas_spelye": str
}
```

## Таблица 6: Виды и объемы использования лесов

**Заголовок:** Виды и объемы использования лесов на проектируемом лесном участке

Вид использования: {{ vid_ispolzovaniya }}
Цель предоставления: {{ cel_predostavleniya }}

**Колонки:** Целевое назначение | Хозяйство | Площадь, га | Ед. измерения | Объемы

```jinja2
{% for row in rayon.table6.rows %}
{{ row.celevoe }} | {{ row.hozyajstvo }} | {{ row.ploshad }} | - | -
{% endfor %}

Итого: | | {{ rayon.table6.itogo_ploshad }} | - | -
```

**Структура table6:**
```python
{
    "rows": [
        {
            "celevoe": str,     # Целевое назначение
            "hozyajstvo": str,  # "Хвойное" / "Лиственное" / "Непокрытое" / "Нелесное"
            "ploshad": str      # "0,4535"
        }
    ],
    "itogo_ploshad": str  # "6,3422"
}
```

## Раздел ОЗУ

```jinja2
{% if rayon.ozu.est %}
Сведения о наличии на территории проектируемого лесного участка особо защитных участков лесов

{{ rayon.ozu.text }}

{% for ozu_type in rayon.ozu.types %}
{{ ozu_type.name }}:
{% for item in ozu_type.items %}
- {{ item }}
{% endfor %}
{% endfor %}
{% endif %}
```

**Структура ozu:**
```python
{
    "est": bool,   # True если есть ОЗУ
    "text": str,   # Вводный текст
    "types": [
        {
            "name": str,     # Тип ОЗУ
            "items": [str]   # Список локаций
        }
    ]
}
```

## Форматирование

- **Шрифт:** GOST 2.304 (или Times New Roman как fallback)
- **Размер:** 10-11pt для таблиц
- **Площадь:** 4 знака после запятой, разделитель запятая (0,4535)
- **Площадь/Запас:** "0,4535 / 15"
- **Пустые значения:** "-"

## Примечания по созданию шаблона

1. Использовать docxtpl синтаксис (Jinja2)
2. Таблицы с объединением ячеек для группировки ({% vm %} для вертикального объединения)
3. Условные блоки {% if %} для опциональных секций
4. Циклы {% for %} для повторяющихся строк
5. Фильтр |lower для преобразования регистра

## Тестирование

После создания шаблона протестировать с тестовым контекстом:
```python
context = {
    "prilozhenie_nomer": "8",
    "nazvanie_dokumenta": "Характеристика образуемых лесных участков",
    "vid_ispolzovaniya": "Строительство линейных объектов",
    "cel_predostavleniya": "Строительство автомобильной дороги",
    "rayony": [{
        "nazvanie": "Тестовый район",
        "oblast": "Тестовая область",
        "lesnichestvo_name": "Тестовое лесничество",
        "table1": {"zashitnye": [], "ekspluatacionnye": []},
        "table2": [],
        "table3": {"obshaya_ploshad": "1,0000", ...},
        "table4": {"groups": [], "itogo": {}},
        "table5": [],
        "table6": {"rows": [], "itogo_ploshad": "0,0000"},
        "ozu": {"est": False, "text": "", "types": []}
    }]
}
```
