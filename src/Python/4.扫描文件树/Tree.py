import os
import sys
import psutil
from datetime import datetime
from contextlib import redirect_stdout

# ================= 配置区域 =================

# 1. 扫描深度限制
LEVEL_LIMIT = 4

# 2. 忽略的文件夹列表 (全小写匹配)
IGNORE_DIRS = {
    '$recycle.bin',             # Windows 回收站
    'system volume information', # Windows 系统卷信息
    '__pycache__',              # Python 缓存
    '.git',                     # Git 版本控制
    '.idea',                    # IDE 配置
    '.vscode',                  # VSCode 配置
    'node_modules',             # Node 依赖
    'recovery',                 # 恢复分区
    '#recycle',                 # NAS/Samba 回收站
    '@eadir',                   # 群晖缩略图索引目录
    'found.000',                # 磁盘碎片修复目录
    'found.001'
}

# ================= 核心逻辑 =================

def normalize_display_path(path):
    """统一给用户展示的路径分隔符，去掉目录尾部分隔符（根路径除外）"""
    normalized = path.replace('\\', '/')
    if normalized.endswith(':'):
        normalized += '/'
    if len(normalized) > 1:
        normalized = normalized.rstrip('/')
        if normalized.endswith(':'):
            normalized += '/'
    return normalized

def get_drives_to_scan():
    """获取除C盘系统根目录外的所有磁盘（支持文件夹挂载点）"""
    drives = []
    print("正在检测系统中的磁盘...")
    try:
        # all=True 必须开启，否则无法读取挂载在文件夹下的分区
        partitions = psutil.disk_partitions(all=True)
        for p in partitions:
            mount_point = p.mountpoint
            
            # 路径标准化处理
            norm_mount = os.path.normpath(mount_point).upper()
            
            # 逻辑：只跳过 C 盘根目录，保留 C:\Disk\xxx 这种挂载点
            if norm_mount == 'C:\\' or norm_mount == 'C:':
                print(f"  - 已跳过系统盘: {mount_point}")
                continue
            
            # 过滤掉不存在的路径或 CD-ROM
            if 'cdrom' in p.opts or not os.path.exists(mount_point):
                continue

            # 只有通过检查的才加入列表
            drives.append(mount_point)
            print(f"  + 已找到待扫描磁盘: {normalize_display_path(mount_point)}")
                
    except Exception as e:
        print(f"获取磁盘列表时出错: {e}")
    
    if not drives:
        print("\n未找到除C盘根目录以外的其他磁盘/挂载点。")
        
    return drives

def generate_tree(directory, prefix='', level=0):
    """
    [高性能版] 递归生成目录树
    使用 os.scandir 获取文件属性，大幅减少硬盘磁头寻道
    """
    if level >= LEVEL_LIMIT:
        return

    try:
        # os.scandir 是性能优化的关键
        with os.scandir(directory) as it:
            # 过滤并排序：先按文件名排序确保输出稳定
            all_entries = [e for e in it if e.name.lower() not in IGNORE_DIRS]
            dirs = sorted([e for e in all_entries if e.is_dir(follow_symlinks=False)], key=lambda e: e.name.lower())
            files = sorted([e for e in all_entries if not e.is_dir(follow_symlinks=False)], key=lambda e: e.name.lower())
            entries = dirs + files

            count = len(entries)
            for i, entry in enumerate(entries):
                is_last = (i == count - 1)
                pointer = '└── ' if is_last else '├── '
                display_name = entry.name + '/' if entry.is_dir(follow_symlinks=False) else entry.name
                print(f"{prefix}{pointer}{display_name}")
                
                # entry.is_dir() 利用了缓存的元数据，无需再次请求操作系统
                if entry.is_dir(follow_symlinks=False):
                    extension = '    ' if is_last else '│   '
                    generate_tree(entry.path, prefix + extension, level + 1)

    except PermissionError:
        print(f"{prefix}└── [权限不足，无法访问]")
    except FileNotFoundError:
        print(f"{prefix}└── [目录不存在]")
    except OSError:
        print(f"{prefix}└── [系统错误，跳过]")

def run_scan_and_print(drives):
    """执行扫描并打印"""
    for i, drive_path in enumerate(drives):
        if i > 0:
            print("\n" + "=" * 50 + "\n") 
        
        display_drive_path = normalize_display_path(drive_path)
        print(f"磁盘/挂载点: {display_drive_path}\n")
        print(display_drive_path)
        # 从 Level 0 开始递归
        generate_tree(drive_path, level=0)

def generate_output_filename(drives):
    """
    生成固定格式的文件名，方便覆盖旧文件
    格式: TreeScan_Latest_DriveInfo.txt
    """
    name_parts = []
    for d in drives:
        clean_path = d.rstrip(os.path.sep)
        # 如果是 C:\Disk\Data，取 Data；如果是 D:，取 D
        if len(clean_path) <= 2 and clean_path[1] == ':':
            name_parts.append(clean_path[0])
        else:
            folder_name = os.path.basename(clean_path)
            name_parts.append(folder_name[:10]) # 限制长度
    
    name_str = '_'.join(name_parts)
    if len(name_str) > 50:
        name_str = "Multi_Drives"

    # 修改点：不再在文件名中包含 timestamp，改为 Latest
    return f"TreeScan_Latest_{name_str}.txt"

def main():
    print("=" * 40)
    print("   极速目录树扫描工具 (Fixed Filename)")
    print("=" * 40)
    
    drives_to_scan = get_drives_to_scan()
    
    if not drives_to_scan:
        return

    output_filename = generate_output_filename(drives_to_scan)
    print(f"\n扫描结果将保存(覆盖)到: {output_filename}")
    print("正在扫描中，请稍候...")
    
    try:
        # 使用 contextlib 优雅地处理文件重定向
        with open(output_filename, 'w', encoding='utf-8') as f:
            with redirect_stdout(f):
                print("=" * 50)
                print(f" 文件树扫描报告")
                # 时间戳保留在这里，打开文件依然能看到是什么时候扫的
                print(f" 扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f" 扫描位置: {', '.join(normalize_display_path(path) for path in drives_to_scan)}")
                print(f" 深度限制: {LEVEL_LIMIT} 层")
                print("=" * 50 + "\n")
                
                run_scan_and_print(drives_to_scan)
                
        print(f"\n扫描成功！已更新 '{output_filename}'")
        
    except Exception as e:
        # 恢复标准输出以便打印错误
        sys.stdout = sys.__stdout__
        print(f"\n发生错误: {e}")

if __name__ == "__main__":
    main()
