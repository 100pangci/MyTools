import os
from PIL import Image

def resize_images_in_folder(input_folder=".", scale_factor=0.5):
    # 创建一个新文件夹用来存放缩小后的图片，避免覆盖原图
    output_folder = os.path.join(input_folder, "resized_images")
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # 支持的图片格式
    valid_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    count = 0

    print("开始处理图片...\n" + "-"*40)

    # 遍历文件夹下的所有文件
    for filename in os.listdir(input_folder):
        ext = os.path.splitext(filename)[1].lower()
        
        # 检查是否为图片文件
        if ext in valid_extensions:
            file_path = os.path.join(input_folder, filename)
            try:
                # 打开图片
                with Image.open(file_path) as img:
                    # 获取原图尺寸并计算新尺寸（等比例缩小一半）
                    new_width = int(img.width * scale_factor)
                    new_height = int(img.height * scale_factor)

                    # 使用 LANCZOS 算法进行高质量缩放
                    # 兼容不同版本的 Pillow
                    resample_filter = getattr(Image, 'Resampling', Image).LANCZOS
                    resized_img = img.resize((new_width, new_height), resample_filter)

                    # 保存缩小后的图片
                    output_path = os.path.join(output_folder, filename)
                    resized_img.save(output_path)
                    
                    print(f"✅ 成功缩小: {filename}")
                    print(f"   尺寸变化: {img.width}x{img.height} -> {new_width}x{new_height}")
                    count += 1
            except Exception as e:
                print(f"❌ 处理 {filename} 时出错: {e}")

    print("-" * 40)
    if count > 0:
        print(f"🎉 处理完成！共成功缩小了 {count} 张图片。")
        print(f"📁 图片已保存在当前目录的文件夹中: {os.path.abspath(output_folder)}")
    else:
        print("⚠️ 未在当前目录找到支持的图片文件。")

if __name__ == "__main__":
    # 默认处理脚本所在的当前目录，缩小比例为 0.5
    resize_images_in_folder(".", scale_factor=0.5)