#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

"""
读取 Excel 文件，按指定 HTML 模板填充占位符，在第三列写入描述、第四列写入结果
"""

import argparse
import os
import sys

import openpyxl

DEFAULT_TEMPLATE = """<p>{desc}</p><p>{name}</p><p>{price}</p><p>【具体价格请咨询商家】</p><p><br></p><p>不只是卖花，更是传递思念与欢喜，让每一份情感都有处安放。</p><p><br></p><p><img alt="图片上传" src="https://jmy-pic.baidu.com/0/pic/-1385074748_501952671_1241745945.jpg" class="fr-fic fr-dii"></p><p><img alt="图片上传" src="https://jmy-pic.baidu.com/0/pic/1850010481_-13527842_504047256.jpg" class="fr-fic fr-dii"></p><p><img alt="图片上传" src="https://jmy-pic.baidu.com/0/pic/-484983576_678918380_-191833468.jpg" class="fr-fic fr-dii"></p>"""


def _load_template_from_file(template_path: str) -> str:
    if not os.path.exists(template_path):
        print(f"错误：模板文件 '{template_path}' 不存在！")
        sys.exit(1)
    try:
        with open(template_path, "r", encoding="utf-8") as file:
            return file.read()
    except Exception as exc:  # noqa: BLE001
        print(f"错误：读取模板文件失败: {exc}")
        sys.exit(1)


def _resolve_template(template_text: str | None, template_path: str | None) -> str:
    if template_text is not None:
        trimmed = template_text.strip()
        if trimmed:
            return template_text
    if template_path:
        return _load_template_from_file(template_path)
    return DEFAULT_TEMPLATE


def _ensure_desc_column(sheet) -> bool:
    """确保第3列用于描述，如第3列已有HTML结果则插入新列。"""
    has_html = False
    sample_rows = min(sheet.max_row, 50) or 1
    for row in range(1, sample_rows + 1):
        value = sheet.cell(row=row, column=3).value
        if isinstance(value, str) and "<" in value:
            has_html = True
            break

    if has_html:
        sheet.insert_cols(3)
        if sheet.cell(row=1, column=3).value in (None, ""):
            sheet.cell(row=1, column=3, value="描述")
        return True

    if sheet.cell(row=1, column=3).value in (None, ""):
        sheet.cell(row=1, column=3, value="描述")
    return False


def process_excel(input_file, output_file=None, template_file=None, template_text=None):
    """
    处理 Excel 文件，替换模板中的占位符

    Args:
        input_file: 输入文件路径
        output_file: 输出文件路径（可选，默认覆盖原文件）
        template_file: HTML 模板文件路径（可选）
        template_text: HTML 模板文本内容（可选，高优先级）
    """
    # 检查输入文件是否存在
    if not os.path.exists(input_file):
        print(f"错误：文件 '{input_file}' 不存在！")
        sys.exit(1)

    # 如果没有指定输出文件，则覆盖原文件
    if output_file is None:
        output_file = input_file

    print(f"正在读取文件: {input_file}")

    try:
        # 读取 Excel 文件
        workbook = openpyxl.load_workbook(input_file)
        sheet = workbook.active

        template_content = _resolve_template(template_text, template_file)
        inserted_desc = _ensure_desc_column(sheet)
        if inserted_desc:
            print("提示：已自动插入“描述”列，原结果列已后移。")

        processed_count = 0

        # 遍历所有行（从第1行开始）
        for row in range(1, sheet.max_row + 1):
            name = sheet.cell(row=row, column=1).value
            price = sheet.cell(row=row, column=2).value
            desc = sheet.cell(row=row, column=3).value

            if name is None and price is None and desc is None:
                continue

            # 替换模板中的占位符（缺失值视为"")
            result = (
                template_content.replace("{name}", "" if name is None else str(name))
                .replace("{price}", "" if price is None else str(price))
                .replace("{desc}", "" if desc is None else str(desc))
            )

            # 将结果写入第四列
            sheet.cell(row=row, column=4, value=result)
            print(f"处理第 {row} 行: name={name}, price={price}, desc={desc}")
            processed_count += 1

        # 保存文件
        workbook.save(output_file)
        print(f"\n✅ 处理完成！")
        print(f"   - 共处理 {processed_count} 行数据")
        print(f"   - 结果已保存到: {output_file}")

    except Exception as e:
        print(f"错误：处理文件时出现异常: {e}")
        sys.exit(1)


def main():
    """主函数，处理命令行参数"""
    parser = argparse.ArgumentParser(
        description="读取 Excel 文件，替换 HTML 模板中的占位符，第三列写入描述，第四列写入结果",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  %(prog)s input.xlsx                    # 处理 input.xlsx，结果覆盖原文件
  %(prog)s input.xlsx -o output.xlsx     # 处理 input.xlsx，结果保存到 output.xlsx
  %(prog)s /path/to/doc.xlsx             # 使用完整路径
        """,
    )

    parser.add_argument("input", help="输入 Excel 文件路径")

    parser.add_argument(
        "-o",
        "--output",
        help="输出 Excel 文件路径（可选，默认覆盖输入文件）",
        default=None,
    )

    parser.add_argument(
        "-t",
        "--template",
        help="HTML 模板文件路径（可选，默认使用内置模板）",
        default=None,
    )
    parser.add_argument(
        "--template-text",
        help="直接传入 HTML 模板内容（优先于 --template）",
        default=None,
    )

    args = parser.parse_args()

    # 处理文件
    process_excel(args.input, args.output, args.template, args.template_text)


if __name__ == "__main__":
    main()
