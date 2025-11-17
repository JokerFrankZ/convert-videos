#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
读取 Excel 文件，替换 HTML 模板中的占位符，并将结果写入第三列
"""

import openpyxl
import argparse
import os
import sys

# HTML 模板
template = """<p>{name}</p><p>{price}</p><p>【具体价格请咨询商家】</p><p><br></p><p>不只是卖花，更是传递思念与欢喜，让每一份情感都有处安放。</p><p><br></p><p><img alt="图片上传" src="https://jmy-pic.baidu.com/0/pic/-1385074748_501952671_1241745945.jpg" class="fr-fic fr-dii"></p><p><img alt="图片上传" src="https://jmy-pic.baidu.com/0/pic/1850010481_-13527842_504047256.jpg" class="fr-fic fr-dii"></p><p><img alt="图片上传" src="https://jmy-pic.baidu.com/0/pic/-484983576_678918380_-191833468.jpg" class="fr-fic fr-dii"></p>"""


def process_excel(input_file, output_file=None):
    """
    处理 Excel 文件，替换模板中的占位符

    Args:
        input_file: 输入文件路径
        output_file: 输出文件路径（可选，默认覆盖原文件）
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

        processed_count = 0

        # 遍历所有行（从第1行开始）
        for row in range(1, sheet.max_row + 1):
            name = sheet.cell(row=row, column=1).value
            price = sheet.cell(row=row, column=2).value

            # 替换模板中的占位符（缺失值视为"")
            result = template.replace('{name}', '' if name is None else str(name)).replace(
                '{price}', '' if price is None else str(price)
            )

            # 将结果写入第三列
            sheet.cell(row=row, column=3, value=result)
            print(f"处理第 {row} 行: name={name}, price={price}")
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
        description='读取 Excel 文件，替换 HTML 模板中的占位符，并将结果写入第三列',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  %(prog)s input.xlsx                    # 处理 input.xlsx，结果覆盖原文件
  %(prog)s input.xlsx -o output.xlsx     # 处理 input.xlsx，结果保存到 output.xlsx
  %(prog)s /path/to/doc.xlsx             # 使用完整路径
        """
    )

    parser.add_argument(
        'input',
        help='输入 Excel 文件路径'
    )

    parser.add_argument(
        '-o', '--output',
        help='输出 Excel 文件路径（可选，默认覆盖输入文件）',
        default=None
    )

    args = parser.parse_args()

    # 处理文件
    process_excel(args.input, args.output)


if __name__ == '__main__':
    main()
