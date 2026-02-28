# -*- coding: utf-8 -*-
"""
Fsm_6_2_3: Объединение PDF файлов в тома.

Использует pypdf для слияния индивидуальных PDF
в итоговые файлы по томам.
"""

import os
import glob
import shutil
from typing import List, Tuple, Optional, Callable

from Daman_QGIS.utils import log_info, log_error, log_warning


class PdfVolumeMerger:
    """Объединение PDF файлов в тома."""

    def merge_volume(
        self, pdf_paths: List[str], output_path: str
    ) -> bool:
        """
        Объединить несколько PDF в один файл тома.

        Файлы сортируются по имени (1_xxx, 2_xxx, ...).

        Args:
            pdf_paths: Список путей к PDF файлам
            output_path: Путь к выходному файлу

        Returns:
            True при успехе
        """
        try:
            from pypdf import PdfWriter

            sorted_paths = sorted(
                pdf_paths,
                key=lambda p: os.path.basename(p).lower()
            )

            writer = PdfWriter()
            for path in sorted_paths:
                try:
                    writer.append(path)
                except Exception as e:
                    log_warning(
                        f"Fsm_6_2_3 (merge_volume): "
                        f"Пропущен {os.path.basename(path)}: {e}"
                    )

            if len(writer.pages) == 0:
                log_warning(
                    f"Fsm_6_2_3 (merge_volume): "
                    f"Нет страниц для объединения в {output_path}"
                )
                writer.close()
                return False

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'wb') as f:
                writer.write(f)
            writer.close()

            log_info(
                f"Fsm_6_2_3: Создан {os.path.basename(output_path)} "
                f"({len(sorted_paths)} файлов, {len(writer.pages)} стр.)"
            )
            return True

        except Exception as e:
            log_error(
                f"Fsm_6_2_3 (merge_volume): "
                f"Ошибка объединения {output_path}: {e}"
            )
            return False

    def process_all_volumes(
        self,
        working_dir: str,
        output_dir: str,
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> List[Tuple[str, bool]]:
        """
        Обработать все тома и графику.

        Графика: копировать отдельные PDF в output_dir (без объединения).
        Том N: объединить все PDF в "Том N.pdf".

        Args:
            working_dir: Путь к _pdf рабочие/
            output_dir: Путь к pdf/
            progress_callback: callback(volume_name, current, total)

        Returns:
            Список (output_path, success)
        """
        results: List[Tuple[str, bool]] = []
        os.makedirs(output_dir, exist_ok=True)

        # Собрать список папок для обработки
        entries = []
        if os.path.isdir(working_dir):
            entries = sorted([
                e for e in os.listdir(working_dir)
                if os.path.isdir(os.path.join(working_dir, e))
            ])

        total = len(entries)

        for idx, entry in enumerate(entries):
            if progress_callback:
                progress_callback(entry, idx + 1, total)

            entry_dir = os.path.join(working_dir, entry)
            pdfs = sorted(glob.glob(os.path.join(entry_dir, "*.pdf")))

            if not pdfs:
                continue

            if entry == "Графика":
                # Графика: копировать отдельные PDF без объединения
                for pdf_file in pdfs:
                    dest = os.path.join(
                        output_dir, os.path.basename(pdf_file)
                    )
                    try:
                        shutil.copy2(pdf_file, dest)
                        results.append((dest, True))
                        log_info(
                            f"Fsm_6_2_3: Скопирован "
                            f"{os.path.basename(pdf_file)}"
                        )
                    except Exception as e:
                        results.append((dest, False))
                        log_error(
                            f"Fsm_6_2_3: Ошибка копирования "
                            f"{os.path.basename(pdf_file)}: {e}"
                        )
            else:
                # Том N: объединить в один файл
                output_path = os.path.join(output_dir, f"{entry}.pdf")
                success = self.merge_volume(pdfs, output_path)
                results.append((output_path, success))

        return results
