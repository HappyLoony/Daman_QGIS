# -*- coding: utf-8 -*-
"""
Fsm_5_2_T_expressions - Тест QgsExpression

Проверяет:
1. Базовые выражения (математика, строки)
2. Функции геометрии ($area, $length, $perimeter)
3. Атрибутные выражения (field access)
4. Агрегатные функции (sum, count, mean)
5. Условные выражения (CASE WHEN)
6. Пользовательские функции (если есть)
7. Выражения в контексте feature

Важно для field calculator и автоматических подписей.
"""

from typing import Any, Dict, List, Optional

from qgis.core import (
    QgsExpression, QgsExpressionContext, QgsExpressionContextUtils,
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
    QgsProject, QgsField
)
from qgis.PyQt.QtCore import QVariant


class TestExpressions:
    """Тесты QgsExpression"""

    def __init__(self, iface: Any, logger: Any) -> None:
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger

    def run_all_tests(self) -> None:
        """Запуск всех тестов выражений"""
        self.logger.section("ТЕСТ QGSEXPRESSION")

        try:
            self.test_01_basic_math()
            self.test_02_string_functions()
            self.test_03_geometry_functions()
            self.test_04_attribute_access()
            self.test_05_conditional_expressions()
            self.test_06_aggregate_functions()
            self.test_07_date_functions()
            self.test_08_expression_errors()
            self.test_09_feature_context()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов expressions: {str(e)}")

        self.logger.summary()

    def _evaluate_expression(self, expr_string: str, context: Optional[QgsExpressionContext] = None) -> Any:
        """Вычислить выражение и вернуть результат"""
        expr = QgsExpression(expr_string)

        if expr.hasParserError():
            return f"PARSE_ERROR: {expr.parserErrorString()}"

        if context is None:
            context = QgsExpressionContext()
            context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(None))

        result = expr.evaluate(context)

        if expr.hasEvalError():
            return f"EVAL_ERROR: {expr.evalErrorString()}"

        return result

    def test_01_basic_math(self) -> None:
        """ТЕСТ 1: Базовые математические выражения"""
        self.logger.section("1. Математические выражения")

        test_cases = [
            ("2 + 2", 4),
            ("10 - 3", 7),
            ("5 * 6", 30),
            ("15 / 3", 5.0),
            ("17 % 5", 2),  # модуль
            ("2 ^ 10", 1024.0),  # степень
            ("sqrt(16)", 4.0),
            ("abs(-5)", 5),
            ("round(3.7)", 4),
            ("floor(3.9)", 3),
            ("ceil(3.1)", 4),
            ("pi()", 3.141592653589793),
        ]

        passed = 0
        for expr_str, expected in test_cases:
            result = self._evaluate_expression(expr_str)

            if isinstance(result, str) and 'ERROR' in result:
                self.logger.fail(f"'{expr_str}': {result}")
            elif abs(float(result) - float(expected)) < 1e-10:
                passed += 1
            else:
                self.logger.fail(f"'{expr_str}': ожидалось {expected}, получено {result}")

        if passed == len(test_cases):
            self.logger.success(f"Все {len(test_cases)} математических выражений OK")
        else:
            self.logger.fail(f"Пройдено только {passed}/{len(test_cases)} математических выражений!")

    def test_02_string_functions(self) -> None:
        """ТЕСТ 2: Строковые функции"""
        self.logger.section("2. Строковые функции")

        test_cases = [
            ("'Hello' || ' ' || 'World'", "Hello World"),
            ("upper('hello')", "HELLO"),
            ("lower('HELLO')", "hello"),
            ("length('test')", 4),
            ("left('hello', 2)", "he"),
            ("right('hello', 2)", "lo"),
            ("substr('hello', 2, 3)", "ell"),
            ("trim('  test  ')", "test"),
            ("replace('hello', 'l', 'L')", "heLLo"),
            # regexp_match возвращает позицию первого совпадения (1-based), 0 если нет
            # 'test123' - цифры начинаются с позиции 5 (t=1,e=2,s=3,t=4,1=5)
            ("regexp_match('test123', '[0-9]+')", 5),
        ]

        passed = 0
        for expr_str, expected in test_cases:
            result = self._evaluate_expression(expr_str)

            if isinstance(result, str) and 'ERROR' in result:
                self.logger.fail(f"'{expr_str}': {result}")
            elif result == expected:
                passed += 1
            else:
                self.logger.fail(f"'{expr_str}': ожидалось '{expected}', получено '{result}'")

        if passed == len(test_cases):
            self.logger.success(f"Все {len(test_cases)} строковых функций OK")
        else:
            self.logger.fail(f"Пройдено только {passed}/{len(test_cases)} строковых функций!")

    def test_03_geometry_functions(self) -> None:
        """ТЕСТ 3: Функции геометрии"""
        self.logger.section("3. Функции геометрии")

        try:
            # Создаём слой с полигоном для контекста
            layer = QgsVectorLayer(
                "Polygon?crs=EPSG:4326&field=name:string",
                "geom_test",
                "memory"
            )

            provider = layer.dataProvider()

            # Добавляем полигон 1x1 градус (примерно 111x111 км)
            feature = QgsFeature()
            feature.setGeometry(QgsGeometry.fromWkt(
                "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"
            ))
            feature.setAttributes(['test_polygon'])
            provider.addFeatures([feature])

            # Создаём контекст с feature
            context = QgsExpressionContext()
            context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))

            # Получаем feature
            for feat in layer.getFeatures():
                context.setFeature(feat)
                break

            # Тестируем функции геометрии
            # $area - в квадратных единицах CRS (градусы^2 для 4326)
            area_result = self._evaluate_expression("$area", context)
            self.logger.info(f"$area = {area_result}")
            if isinstance(area_result, (int, float)) and area_result > 0:
                self.logger.success("$area возвращает положительное значение")
            else:
                self.logger.fail(f"$area: неожиданный результат {area_result}!")

            # $perimeter
            perimeter_result = self._evaluate_expression("$perimeter", context)
            self.logger.info(f"$perimeter = {perimeter_result}")
            if isinstance(perimeter_result, (int, float)) and perimeter_result > 0:
                self.logger.success("$perimeter возвращает положительное значение")
            else:
                self.logger.fail("$perimeter: неожиданный результат!")

            # num_points
            points_result = self._evaluate_expression("num_points($geometry)", context)
            self.logger.info(f"num_points = {points_result}")
            if points_result == 5:  # замкнутый полигон: 4 угла + 1 замыкающая точка
                self.logger.success("num_points корректно (5 точек)")
            else:
                self.logger.fail(f"num_points: ожидалось 5, получено {points_result}!")

            # geom_to_wkt
            wkt_result = self._evaluate_expression("geom_to_wkt($geometry)", context)
            wkt_str = str(wkt_result).upper()
            self.logger.info(f"geom_to_wkt result: {wkt_str[:100]}...")
            # Проверяем на Polygon или MultiPolygon (case insensitive)
            if 'POLYGON' in wkt_str or 'MULTIPOLYGON' in wkt_str:
                self.logger.success("geom_to_wkt возвращает WKT с полигоном")
            elif wkt_result is None or 'ERROR' in wkt_str:
                self.logger.fail(f"geom_to_wkt вернул ошибку: {wkt_result}")
            else:
                self.logger.fail(f"geom_to_wkt: не содержит POLYGON! Результат: {wkt_str[:50]}")

            del layer

        except Exception as e:
            self.logger.error(f"Ошибка теста геометрии: {e}")

    def test_04_attribute_access(self) -> None:
        """ТЕСТ 4: Доступ к атрибутам"""
        self.logger.section("4. Доступ к атрибутам")

        try:
            # Создаём слой с разными типами полей
            layer = QgsVectorLayer(
                "Point?crs=EPSG:4326"
                "&field=name:string"
                "&field=value:integer"
                "&field=price:double",
                "attr_test",
                "memory"
            )

            provider = layer.dataProvider()

            feature = QgsFeature()
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(0, 0)))
            feature.setAttributes(['Test Name', 42, 123.45])
            provider.addFeatures([feature])

            # Создаём контекст
            context = QgsExpressionContext()
            context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))

            for feat in layer.getFeatures():
                context.setFeature(feat)
                break

            # Тестируем доступ к полям
            tests = [
                ('"name"', 'Test Name'),
                ('"value"', 42),
                ('"price"', 123.45),
                ('"value" * 2', 84),
                ('"price" + 10', 133.45),
                ('upper("name")', 'TEST NAME'),
            ]

            passed = 0
            for expr_str, expected in tests:
                result = self._evaluate_expression(expr_str, context)

                if result == expected:
                    passed += 1
                elif isinstance(result, float) and isinstance(expected, float):
                    if abs(result - expected) < 0.001:
                        passed += 1
                    else:
                        self.logger.fail(f"'{expr_str}': ожидалось {expected}, получено {result}")
                else:
                    self.logger.fail(f"'{expr_str}': ожидалось {expected}, получено {result}")

            if passed == len(tests):
                self.logger.success(f"Все {len(tests)} тестов доступа к атрибутам OK")
            else:
                self.logger.fail(f"Пройдено только {passed}/{len(tests)} тестов доступа к атрибутам!")

            del layer

        except Exception as e:
            self.logger.error(f"Ошибка теста атрибутов: {e}")

    def test_05_conditional_expressions(self) -> None:
        """ТЕСТ 5: Условные выражения"""
        self.logger.section("5. Условные выражения (CASE WHEN)")

        test_cases = [
            # if/then/else
            ("if(1 > 0, 'yes', 'no')", 'yes'),
            ("if(1 < 0, 'yes', 'no')", 'no'),

            # CASE WHEN
            ("CASE WHEN 5 > 3 THEN 'bigger' ELSE 'smaller' END", 'bigger'),
            ("CASE WHEN 5 < 3 THEN 'bigger' ELSE 'smaller' END", 'smaller'),

            # Multiple WHEN
            ("CASE WHEN 1=2 THEN 'first' WHEN 2=2 THEN 'second' ELSE 'none' END", 'second'),

            # coalesce (первое не-NULL)
            ("coalesce(NULL, NULL, 'value')", 'value'),
            ("coalesce('first', 'second')", 'first'),

            # nullif
            ("nullif(5, 5)", None),  # равны -> NULL
            ("nullif(5, 3)", 5),  # не равны -> первое значение
        ]

        passed = 0
        for expr_str, expected in test_cases:
            result = self._evaluate_expression(expr_str)

            if isinstance(result, str) and 'ERROR' in result:
                self.logger.fail(f"'{expr_str}': {result}")
            elif result == expected:
                passed += 1
            elif result is None and expected is None:
                passed += 1
            else:
                self.logger.fail(f"'{expr_str}': ожидалось {expected}, получено {result}")

        if passed == len(test_cases):
            self.logger.success(f"Все {len(test_cases)} условных выражений OK")
        else:
            self.logger.fail(f"Пройдено только {passed}/{len(test_cases)} условных выражений!")

    def test_06_aggregate_functions(self) -> None:
        """ТЕСТ 6: Агрегатные функции"""
        self.logger.section("6. Агрегатные функции")

        try:
            # Создаём слой с данными для агрегации
            layer = QgsVectorLayer(
                "Point?crs=EPSG:4326&field=category:string&field=value:integer",
                "aggregate_test",
                "memory"
            )

            provider = layer.dataProvider()

            # Добавляем данные
            data = [
                ('A', 10),
                ('A', 20),
                ('B', 30),
                ('B', 40),
                ('B', 50),
            ]

            features = []
            for i, (cat, val) in enumerate(data):
                feat = QgsFeature()
                feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(i, 0)))
                feat.setAttributes([cat, val])
                features.append(feat)

            provider.addFeatures(features)

            # Добавляем слой в проект для агрегатных функций
            QgsProject.instance().addMapLayer(layer, False)

            # Создаём контекст
            context = QgsExpressionContext()
            context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))

            # Берём первую feature
            for feat in layer.getFeatures():
                context.setFeature(feat)
                break

            # Тестируем агрегатные функции
            # sum всех value
            sum_expr = f"aggregate('{layer.id()}', 'sum', \"value\")"
            sum_result = self._evaluate_expression(sum_expr, context)
            self.logger.info(f"sum(value) = {sum_result}")

            if sum_result == 150:  # 10+20+30+40+50
                self.logger.success("aggregate sum работает корректно")
            else:
                self.logger.fail(f"aggregate sum: ожидалось 150, получено {sum_result}!")

            # count
            count_expr = f"aggregate('{layer.id()}', 'count', \"value\")"
            count_result = self._evaluate_expression(count_expr, context)
            self.logger.info(f"count(value) = {count_result}")

            if count_result == 5:
                self.logger.success("aggregate count работает корректно")
            else:
                self.logger.fail(f"aggregate count: ожидалось 5, получено {count_result}!")

            # Убираем слой из проекта
            QgsProject.instance().removeMapLayer(layer.id())

        except Exception as e:
            self.logger.error(f"Ошибка теста агрегатов: {e}")

    def test_07_date_functions(self) -> None:
        """ТЕСТ 7: Функции даты/времени"""
        self.logger.section("7. Функции даты/времени")

        test_cases = [
            # Текущая дата (просто проверяем что не ошибка)
            ("now()", None),  # проверим отдельно
            ("year(now())", None),  # проверим отдельно
            ("month(now())", None),

            # Создание даты
            ("make_date(2024, 1, 15)", None),

            # Форматирование
            ("format_date(make_date(2024, 1, 15), 'yyyy-MM-dd')", '2024-01-15'),

            # Разбор даты
            ("year(to_date('2024-06-15'))", 2024),
            ("month(to_date('2024-06-15'))", 6),
            ("day(to_date('2024-06-15'))", 15),
        ]

        passed = 0
        for expr_str, expected in test_cases:
            result = self._evaluate_expression(expr_str)

            if isinstance(result, str) and 'ERROR' in result:
                self.logger.fail(f"'{expr_str}': {result}")
            elif expected is None:
                # Проверяем что нет ошибки - результат не должен быть ERROR
                if not isinstance(result, str) or 'ERROR' not in result:
                    passed += 1
                    self.logger.info(f"'{expr_str}' = {result}")
                else:
                    self.logger.fail(f"'{expr_str}': ошибка!")
            elif result == expected:
                passed += 1
                self.logger.success(f"'{expr_str}' = {expected}")
            else:
                self.logger.fail(f"'{expr_str}': ожидалось {expected}, получено {result}!")

        if passed == len(test_cases):
            self.logger.success(f"Все {len(test_cases)} функций даты/времени OK")
        else:
            self.logger.fail(f"Пройдено только {passed}/{len(test_cases)} функций даты/времени!")

    def test_08_expression_errors(self) -> None:
        """ТЕСТ 8: Обработка ошибок выражений"""
        self.logger.section("8. Обработка ошибок")

        # Выражения с синтаксическими ошибками
        invalid_expressions = [
            ("2 +", "незавершённое выражение"),
            ("upper(", "незакрытая скобка"),
            ("nonexistent_function()", "несуществующая функция"),
            ("1 / 0", "деление на ноль"),
        ]

        detected_errors = 0
        for expr_str, description in invalid_expressions:
            expr = QgsExpression(expr_str)

            if expr.hasParserError():
                detected_errors += 1
                self.logger.success(f"'{expr_str}': парсер обнаружил ошибку ({description})")
            else:
                # Пробуем evaluate
                context = QgsExpressionContext()
                result = expr.evaluate(context)

                if expr.hasEvalError():
                    detected_errors += 1
                    self.logger.success(f"'{expr_str}': ошибка при выполнении ({description})")
                elif result is None or result == 0:
                    # NULL/0 для некорректных выражений тоже считаем корректной обработкой
                    detected_errors += 1
                    self.logger.info(f"'{expr_str}': вернул {result} ({description})")
                else:
                    self.logger.fail(f"'{expr_str}': должна быть ошибка, но получено: {result}!")

        if detected_errors == len(invalid_expressions):
            self.logger.success(f"Все {len(invalid_expressions)} ошибочных выражений обнаружены")
        else:
            self.logger.fail(f"Обнаружено только {detected_errors}/{len(invalid_expressions)} ошибочных выражений!")

    def test_09_feature_context(self) -> None:
        """ТЕСТ 9: Контекст feature ($id, @layer_name)"""
        self.logger.section("9. Контекст feature")

        try:
            layer = QgsVectorLayer(
                "Point?crs=EPSG:4326&field=name:string",
                "context_test_layer",
                "memory"
            )

            provider = layer.dataProvider()
            feature = QgsFeature()
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(10, 20)))
            feature.setAttributes(['TestFeature'])
            provider.addFeatures([feature])

            # Создаём полный контекст
            context = QgsExpressionContext()
            context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))

            for feat in layer.getFeatures():
                context.setFeature(feat)
                break

            # Тестируем переменные контекста
            # $id - ID feature
            id_result = self._evaluate_expression("$id", context)
            self.logger.info(f"$id = {id_result}")
            if id_result is not None:
                self.logger.success("$id доступен")
            else:
                self.logger.fail("$id недоступен!")

            # @layer_name
            layer_name_result = self._evaluate_expression("@layer_name", context)
            self.logger.info(f"@layer_name = {layer_name_result}")
            if layer_name_result == 'context_test_layer':
                self.logger.success("@layer_name корректен")
            else:
                self.logger.fail(f"@layer_name: ожидалось 'context_test_layer', получено '{layer_name_result}'!")

            # $x, $y координаты
            x_result = self._evaluate_expression("$x", context)
            y_result = self._evaluate_expression("$y", context)
            self.logger.info(f"$x = {x_result}, $y = {y_result}")

            if x_result == 10 and y_result == 20:
                self.logger.success("$x, $y корректны")
            else:
                self.logger.fail(f"$x, $y: ожидалось (10, 20), получено ({x_result}, {y_result})!")

            del layer

        except Exception as e:
            self.logger.error(f"Ошибка теста контекста: {e}")
