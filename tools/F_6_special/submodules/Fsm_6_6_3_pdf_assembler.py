# -*- coding: utf-8 -*-
"""
Fsm_6_6_3: Склейка PDF файлов мастер-плана в один документ.

Использует pypdf для объединения индивидуальных PDF-страниц
схем мастер-плана в итоговый файл.
"""

import os
from typing import List

from Daman_QGIS.utils import log_info, log_error, log_warning


class Fsm_6_6_3_PdfAssembler:
    """Склейка PDF файлов мастер-плана."""

    def merge(self, pdf_paths: List[str], output_path: str) -> bool:
        """
        Объединить несколько PDF в один файл.

        Файлы добавляются в порядке списка (уже отсортированы по индексу).

        Args:
            pdf_paths: Список путей к PDF файлам
            output_path: Путь к выходному файлу

        Returns:
            True при успехе
        """
        if not pdf_paths:
            log_warning("Fsm_6_6_3: Нет PDF файлов для объединения")
            return False

        try:
            from pypdf import PdfWriter

            writer = PdfWriter()

            for path in pdf_paths:
                if not os.path.exists(path):
                    log_warning(
                        f"Fsm_6_6_3: Файл не найден, пропущен: "
                        f"{os.path.basename(path)}"
                    )
                    continue

                try:
                    writer.append(path)
                except Exception as e:
                    log_warning(
                        f"Fsm_6_6_3: Пропущен {os.path.basename(path)}: {e}"
                    )

            if len(writer.pages) == 0:
                log_error("Fsm_6_6_3: Нет страниц для объединения")
                writer.close()
                return False

            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            with open(output_path, 'wb') as f:
                writer.write(f)

            page_count = len(writer.pages)
            writer.close()

            log_info(
                f"Fsm_6_6_3: Создан {os.path.basename(output_path)} "
                f"({len(pdf_paths)} файлов, {page_count} стр.)"
            )
            return True

        except ImportError:
            log_error(
                "Fsm_6_6_3: pypdf не установлен. "
                "Установите: pip install pypdf"
            )
            return False

        except Exception as e:
            log_error(f"Fsm_6_6_3: Ошибка объединения PDF: {e}")
            return False
