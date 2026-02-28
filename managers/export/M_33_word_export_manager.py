# -*- coding: utf-8 -*-
"""
M_33_WordExportManager - Менеджер экспорта документов в Word.

Отвечает за:
- Загрузку и кэширование .docx шаблонов с Jinja2-тегами
- Рендеринг шаблонов с данными (docxtpl)
- Экранирование XML-спецсимволов
- Повторное использование шаблонов через deepcopy

Требует: docxtpl>=0.19.0 (включает python-docx)

Использование:
    from Daman_QGIS.managers import registry

    manager = registry.get('M_33')
    context = {"название": "Проект А", "дата": "19.01.2026"}
    manager.render("шаблон.docx", context, "output/документ.docx")
"""

from copy import deepcopy
from pathlib import Path
from typing import Dict, Any, List, Optional

from Daman_QGIS.utils import log_info, log_error, log_warning

__all__ = ['WordExportManager']


class WordExportManager:
    """
    Менеджер экспорта документов в Word.

    Использует docxtpl для рендеринга .docx шаблонов с Jinja2-синтаксисом.
    Поддерживает:
    - Переменные: {{ переменная }}
    - Циклы: {% for item in list %}...{% endfor %}
    - Условия: {% if условие %}...{% endif %}
    - Таблицы: {%tr for row in rows %}...{%tr endfor %}
    - Вертикальное объединение: {% vm %}
    """

    def __init__(self, template_dir: Optional[str] = None):
        """
        Инициализация менеджера.

        Args:
            template_dir: Путь к директории с .docx шаблонами.
                          Если None, используется data/templates/word

        Raises:
            ValueError: Если директория не существует
        """
        if template_dir is None:
            # Определяем путь относительно плагина
            plugin_dir = Path(__file__).parent.parent
            template_dir = str(plugin_dir / "data" / "templates" / "word")
        self.template_dir = Path(template_dir)
        if not self.template_dir.exists():
            log_warning(f"M_33: Директория шаблонов не существует: {template_dir}")
            # Не падаем - директория может быть создана позже
            self.template_dir.mkdir(parents=True, exist_ok=True)
            log_info(f"M_33: Создана директория шаблонов: {template_dir}")

        self._template_cache: Dict[str, Any] = {}  # Кэш загруженных шаблонов
        self._docxtpl_available: Optional[bool] = None

        log_info(f"M_33: WordExportManager инициализирован. Шаблоны: {template_dir}")

    def _check_docxtpl(self) -> bool:
        """
        Проверить доступность библиотеки docxtpl.

        Returns:
            bool: True если библиотека доступна
        """
        if self._docxtpl_available is None:
            try:
                from docxtpl import DocxTemplate
                self._docxtpl_available = True
                log_info("M_33: Библиотека docxtpl доступна")
            except ImportError:
                self._docxtpl_available = False
                log_error("M_33: Библиотека docxtpl не установлена. "
                          "Установите: pip install docxtpl>=0.19.0")
        return self._docxtpl_available

    def list_templates(self, subdirectory: Optional[str] = None) -> List[str]:
        """
        Получить список доступных шаблонов.

        Args:
            subdirectory: Опциональная поддиректория (например, "hlu")

        Returns:
            List[str]: Список имён .docx файлов
        """
        search_dir = self.template_dir
        if subdirectory:
            search_dir = search_dir / subdirectory

        if not search_dir.exists():
            return []

        templates = []
        for docx_file in search_dir.glob("**/*.docx"):
            # Возвращаем относительный путь от template_dir
            rel_path = docx_file.relative_to(self.template_dir)
            templates.append(str(rel_path))

        templates.sort()
        return templates

    def template_exists(self, template_name: str) -> bool:
        """
        Проверить существование шаблона.

        Args:
            template_name: Имя файла шаблона (относительно template_dir)

        Returns:
            bool: True если шаблон существует
        """
        template_path = self.template_dir / template_name
        return template_path.exists() and template_path.suffix.lower() == '.docx'

    def _load_template(self, template_name: str) -> Any:
        """
        Загрузить шаблон с кэшированием.

        Args:
            template_name: Имя файла шаблона

        Returns:
            DocxTemplate: Загруженный шаблон

        Raises:
            FileNotFoundError: Если шаблон не найден
            ValueError: Если docxtpl недоступен
        """
        if not self._check_docxtpl():
            raise ValueError("Библиотека docxtpl не установлена")

        from docxtpl import DocxTemplate

        # Проверяем кэш
        if template_name in self._template_cache:
            return self._template_cache[template_name]

        template_path = self.template_dir / template_name

        if not template_path.exists():
            raise FileNotFoundError(f"Шаблон не найден: {template_path}")

        if not template_path.suffix.lower() == '.docx':
            raise ValueError(f"Файл не является .docx шаблоном: {template_path}")

        try:
            template = DocxTemplate(str(template_path))
            self._template_cache[template_name] = template
            log_info(f"M_33: Шаблон загружен: {template_name}")
            return template

        except Exception as e:
            log_error(f"M_33: Ошибка загрузки шаблона {template_name}: {e}")
            raise

    def render(
        self,
        template_name: str,
        context: Dict[str, Any],
        output_path: str,
        autoescape: bool = True
    ) -> bool:
        """
        Рендеринг шаблона с данными.

        Args:
            template_name: Имя файла шаблона (относительно template_dir)
            context: Данные для подстановки в шаблон
            output_path: Путь для сохранения результата
            autoescape: Экранировать XML-спецсимволы <, >, &, "
                        Рекомендуется True для безопасности

        Returns:
            bool: True если успешно

        Raises:
            FileNotFoundError: Если шаблон не найден
            ValueError: Если docxtpl недоступен
        """
        if not self._check_docxtpl():
            log_error("M_33: docxtpl не установлен")
            return False

        try:
            # Загружаем шаблон
            template = self._load_template(template_name)

            # ВАЖНО: deepcopy для повторного использования
            # Issue #381: render() нельзя вызывать дважды на одном объекте
            doc = deepcopy(template)

            # Рендерим
            if autoescape:
                from jinja2 import Environment
                jinja_env = Environment(autoescape=True)
                doc.render(context, jinja_env)
            else:
                doc.render(context)

            # Создаём директорию для output если нужно
            output_dir = Path(output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)

            # Сохраняем
            doc.save(output_path)
            log_info(f"M_33: Документ сохранён: {output_path}")
            return True

        except FileNotFoundError as e:
            log_error(f"M_33: Шаблон не найден: {e}")
            return False

        except Exception as e:
            log_error(f"M_33: Ошибка рендеринга: {e}")
            return False

    def render_to_bytes(
        self,
        template_name: str,
        context: Dict[str, Any],
        autoescape: bool = True
    ) -> Optional[bytes]:
        """
        Рендеринг шаблона в байты (без сохранения в файл).

        Полезно для HTTP-ответов или обработки в памяти.

        Args:
            template_name: Имя файла шаблона
            context: Данные для подстановки
            autoescape: Экранировать спецсимволы

        Returns:
            bytes: Содержимое документа или None при ошибке
        """
        if not self._check_docxtpl():
            return None

        try:
            from io import BytesIO

            template = self._load_template(template_name)
            doc = deepcopy(template)

            if autoescape:
                from jinja2 import Environment
                jinja_env = Environment(autoescape=True)
                doc.render(context, jinja_env)
            else:
                doc.render(context)

            buffer = BytesIO()
            doc.save(buffer)
            buffer.seek(0)
            return buffer.read()

        except Exception as e:
            log_error(f"M_33: Ошибка рендеринга в байты: {e}")
            return None

    def validate_template(self, template_name: str) -> Dict[str, Any]:
        """
        Проверить валидность шаблона.

        Проверяет:
        - Существование файла
        - Корректность .docx структуры
        - Загружаемость через docxtpl

        Args:
            template_name: Имя файла шаблона

        Returns:
            dict: {"valid": bool, "error": str или None}
        """
        template_path = self.template_dir / template_name

        if not template_path.exists():
            return {"valid": False, "error": f"Файл не найден: {template_path}"}

        if not template_path.suffix.lower() == '.docx':
            return {"valid": False, "error": "Файл не является .docx"}

        if not self._check_docxtpl():
            return {"valid": False, "error": "docxtpl не установлен"}

        try:
            from docxtpl import DocxTemplate
            DocxTemplate(str(template_path))
            return {"valid": True, "error": None}

        except Exception as e:
            return {"valid": False, "error": str(e)}

    def validate_all_templates(self) -> Dict[str, Any]:
        """
        Проверить все шаблоны в директории.

        Returns:
            dict: {"valid": [list], "invalid": [list]}
        """
        templates = self.list_templates()
        results = {"valid": [], "invalid": []}

        for template_name in templates:
            result = self.validate_template(template_name)
            if result["valid"]:
                results["valid"].append(template_name)
            else:
                results["invalid"].append({
                    "template": template_name,
                    "error": result["error"]
                })

        return results

    def clear_cache(self):
        """Очистить кэш загруженных шаблонов."""
        self._template_cache.clear()
        log_info("M_33: Кэш шаблонов очищен")

    def get_template_path(self, template_name: str) -> Path:
        """
        Получить полный путь к шаблону.

        Args:
            template_name: Имя файла шаблона

        Returns:
            Path: Полный путь к файлу шаблона
        """
        return self.template_dir / template_name

    @staticmethod
    def format_area(value: float, decimals: int = 4) -> str:
        """
        Форматирование площади с запятой (русская локаль).

        Args:
            value: Значение площади
            decimals: Количество знаков после запятой (по умолчанию 4)

        Returns:
            str: Форматированное значение (например, "0,0231")
        """
        if value is None:
            return "-"
        return f"{value:.{decimals}f}".replace(".", ",")

    @staticmethod
    def format_area_zapas(area: float, zapas: int) -> str:
        """
        Форматирование площади/запаса для таблиц ХЛУ.

        Args:
            area: Площадь в га
            zapas: Запас древесины в куб.м

        Returns:
            str: Форматированное значение (например, "0,0231 / 15")
        """
        if area is None or area == 0:
            return "-"
        area_str = f"{area:.4f}".replace(".", ",")
        return f"{area_str} / {zapas or 0}"
