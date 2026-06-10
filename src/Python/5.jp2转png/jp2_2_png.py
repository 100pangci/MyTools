import os
import argparse
from PIL import Image

def convert_jp2_to_png_in_directory(directory_path):
    """
    Scans a directory for JP2 files and converts them to PNG format.

    Args:
        directory_path (str): The path to the directory containing JP2 files.
    """
    # 1. 验证目录是否存在
    if not os.path.isdir(directory_path):
        print(f"错误：目录 '{directory_path}' 不存在。")
        return

    print(f"正在扫描目录: '{directory_path}'...")
    converted_count = 0
    
    # 2. 遍历目录中的所有文件
    for filename in os.listdir(directory_path):
        # 3. 检查文件扩展名是否为 .jp2 或 .j2k (不区分大小写)
        if filename.lower().endswith(('.jp2', '.j2k')):
            # 构建完整的文件路径
            jp2_path = os.path.join(directory_path, filename)
            
            # 创建新的 PNG 文件名
            base_filename = os.path.splitext(filename)[0]
            png_filename = base_filename + '.png'
            png_path = os.path.join(directory_path, png_filename)

            # 4. 执行转换
            try:
                # 使用 'with' 语句确保文件被正确关闭
                with Image.open(jp2_path) as img:
                    print(f"正在转换: '{filename}' -> '{png_filename}'")
                    img.save(png_path, 'PNG')
                    converted_count += 1
            except Exception as e:
                print(f"转换 '{filename}' 时发生错误: {e}")
    
    # 5. 打印总结信息
    if converted_count > 0:
        print(f"\n转换完成！成功转换 {converted_count} 个文件。")
    else:
        print("未在目录中找到任何 .jp2 或 .j2k 文件。")

if __name__ == "__main__":
    # 设置命令行参数解析
    parser = argparse.ArgumentParser(description="将指定目录下的所有 JP2 文件转换为 PNG 格式。")
    parser.add_argument("directory", help="包含 JP2 文件的目录路径。")
    
    args = parser.parse_args()
    
    # 调用主函数
    convert_jp2_to_png_in_directory(args.directory)

