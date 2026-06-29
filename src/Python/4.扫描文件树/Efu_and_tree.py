#!/usr/bin/env python3
import os
import csv
import time
from datetime import datetime

# ================= 配置区域 =================
MOUNT_MAP = {
    "/mnt/example-1": "V:",
    "/mnt/example-2": "W:",
    "/mnt/example-3": "X:",
    "/mnt/example-4": "Y:"
}

IGNORE_DIRS = {
    '$recycle.bin', 'system volume information', '__pycache__', 
    '.git', '.idea', '.vscode', 'node_modules', 'recovery', 
    '#recycle', '@eadir', 'found.000', 'found.001',
    '.stfolder', '.stversions'
}

LEVEL_LIMIT = 4

# 输出路径
EFU_PATH = "/mnt/example/nas_files.efu"
TREE_OUTPUT_DIR = "/mnt/example/Tree"
TREE_OUTPUT_FILE = os.path.join(TREE_OUTPUT_DIR, "TreeScan_Latest.txt")

# ================= Trie 树结构（用于内存生成 Tree） =================
class TrieNode:
    def __init__(self):
        self.dirs = {}  # name -> TrieNode
        self.files = set()

def insert_to_trie(trie, rel_path, name, is_dir):
    if rel_path == ".":
        components = []
    else:
        components = rel_path.split(os.sep)
        
    if len(components) >= LEVEL_LIMIT:
        return  # 超过 4 层深度，直接忽略，不占内存
        
    node = trie
    for comp in components:
        if comp not in node.dirs:
            node.dirs[comp] = TrieNode()
        node = node.dirs[comp]
        
    if is_dir:
        if name not in node.dirs:
            node.dirs[name] = TrieNode()
    else:
        node.files.add(name)

def generate_tree_output(node, file_handle, prefix=''):
    sorted_dirs = sorted(node.dirs.keys(), key=lambda s: s.lower())
    sorted_files = sorted(node.files, key=lambda s: s.lower())
    
    entries = [(d, True) for d in sorted_dirs] + [(f, False) for f in sorted_files]
    count = len(entries)
    
    for i, (name, is_dir) in enumerate(entries):
        is_last = (i == count - 1)
        pointer = '└── ' if is_last else '├── '
        display_name = (name + '/') if is_dir else name
        file_handle.write(f"{prefix}{pointer}{display_name}\n")
        
        if is_dir:
            extension = '    ' if is_last else '│   '
            generate_tree_output(node.dirs[name], file_handle, prefix + extension)

def get_win_filetime(unix_time):
    return int((unix_time + 11644473600) * 10000000)

# ================= 主运行逻辑 =================
def main():
    print("=== [一箭双雕] 引擎启动 ===")
    start_time = time.time()
    total_count = 0
    
    # 确保输出目录存在
    os.makedirs(os.path.dirname(EFU_PATH), exist_ok=True)
    os.makedirs(TREE_OUTPUT_DIR, exist_ok=True)
    
    # 初始化 Trie 树
    tries = {linux_path: TrieNode() for linux_path in MOUNT_MAP.keys()}
    
    # 1. 扫描并同时写入 EFU
    with open(EFU_PATH, 'w', encoding='utf-8', newline='') as f_efu:
        writer = csv.writer(f_efu, doublequote=True)
        writer.writerow(["Filename", "Size", "Date Modified", "Attributes"])
        
        for linux_path, win_drive in MOUNT_MAP.items():
            if not os.path.exists(linux_path):
                print(f"警告: 目录 {linux_path} 不存在，跳过。")
                continue
            
            print(f"正在扫描: {linux_path} ...")
            for root, dirs, files in os.walk(linux_path):
                # 🚀 物理强力剪枝：直接修改 dirs 列表，防止 os.walk 进入垃圾目录，扫盘速度暴涨！
                dirs[:] = [d for d in dirs if d.lower() not in IGNORE_DIRS]
                
                rel_path = os.path.relpath(root, linux_path)
                
                # 写入文件夹并插入 Trie
                for d in dirs:
                    full_linux_path = os.path.join(root, d)
                    try:
                        stat = os.stat(full_linux_path)
                        win_path = os.path.join(win_drive + "\\", rel_path, d).replace("/", "\\") if rel_path != "." else os.path.join(win_drive + "\\", d).replace("/", "\\")
                        writer.writerow([win_path, 0, get_win_filetime(stat.st_mtime), 16])
                        
                        # 插入 Trie
                        insert_to_trie(tries[linux_path], rel_path, d, is_dir=True)
                        total_count += 1
                    except:
                        pass
                
                # 写入文件并插入 Trie
                for file in files:
                    full_linux_path = os.path.join(root, file)
                    try:
                        stat = os.stat(full_linux_path)
                        win_path = os.path.join(win_drive + "\\", rel_path, file).replace("/", "\\") if rel_path != "." else os.path.join(win_drive + "\\", file).replace("/", "\\")
                        writer.writerow([win_path, stat.st_size, get_win_filetime(stat.st_mtime), 32])
                        
                        # 插入 Trie
                        insert_to_trie(tries[linux_path], rel_path, file, is_dir=False)
                        total_count += 1
                        if total_count % 500000 == 0:
                            print(f"已扫描 {total_count} 个项目...")
                    except:
                        pass

    # 2. 内存生成完美格式的 Tree 文件（不带 Windows 盘符，纯 Linux 路径展示）
    print("正在从内存 Trie 中导出 Tree 报告...")
    with open(TREE_OUTPUT_FILE, 'w', encoding='utf-8') as f_tree:
        f_tree.write("=" * 50 + "\n")
        f_tree.write(" 文件树扫描报告\n")
        f_tree.write(f" 扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f_tree.write(f" 扫描位置: {', '.join(MOUNT_MAP.keys())}\n")
        f_tree.write(f" 深度限制: {LEVEL_LIMIT} 层\n")
        f_tree.write("=" * 50 + "\n\n")
        
        for i, linux_path in enumerate(sorted(MOUNT_MAP.keys())):
            if i > 0:
                f_tree.write("\n" + "=" * 50 + "\n\n")
            f_tree.write(f"磁盘/挂载点: {linux_path}\n\n")
            f_tree.write(f"{linux_path}\n")
            generate_tree_output(tries[linux_path], f_tree)

    # 3. 纠正所有权
    try:
        os.chown(EFU_PATH, 1000, 1000)
        os.chown(TREE_OUTPUT_FILE, 1000, 1000)
    except:
        pass

    end_time = time.time()
    print(f"=== 运行成功 ===")
    print(f"EFU 保存至: {EFU_PATH}")
    print(f"Tree 保存至: {TREE_OUTPUT_FILE}")
    print(f"总处理项目: {total_count}")
    print(f"总共耗时: {end_time - start_time:.2f} 秒")

if __name__ == "__main__":
    main()
