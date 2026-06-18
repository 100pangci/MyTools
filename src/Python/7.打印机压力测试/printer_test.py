"""
打印机压力测试脚本
- 每隔指定时间（默认30分钟）向指定打印机发送打印任务
- 每次打印指定份数（默认3份）
- 可自定义打印机名称
- 支持打印同目录下的指定 PDF 文件
- 自动在 PDF 每页添加水印（打印机信息、时间、份数等）
"""

import os
import sys
import time
import json
import datetime
import subprocess
import glob
import re
import ctypes
from io import BytesIO
from ctypes import wintypes
from pathlib import Path
from pypdf import PdfReader, PdfWriter

CONFIG_FILE = Path(__file__).parent / "printer_config.json"


# ──────────────────────────────────────────────
#  PDF 水印引擎（reportlab 生成 + pypdf 叠加，支持中文）
# ──────────────────────────────────────────────

def _find_chinese_font():
    """查找系统中可用的中文字体"""
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",      # 微软雅黑
        r"C:\Windows\Fonts\msyhbd.ttc",    # 微软雅黑粗体
        r"C:\Windows\Fonts\simhei.ttf",    # 黑体
        r"C:\Windows\Fonts\simsun.ttc",    # 宋体
        r"C:\Windows\Fonts\simfang.ttf",   # 仿宋
        r"C:\Windows\Fonts\simkai.ttf",    # 楷体
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return None


def _create_watermark_page(watermark_lines, width, height):
    """
    使用 reportlab 创建水印 PDF 页面（支持中文）。
    水印效果：黑色文字，45 度倾斜，居中显示。
    返回 BytesIO 流，可作为 pypdf 的 PdfReader 输入。
    """
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(width, height))

    # 注册中文字体
    font_path = _find_chinese_font()
    font_name = "Helvetica"  # 默认降级
    if font_path:
        try:
            pdfmetrics.registerFont(TTFont("ChineseFont", font_path))
            font_name = "ChineseFont"
        except Exception:
            pass

    # 黑色 + 半透明（避免完全遮挡原内容，但视觉上是黑色水印）
    c.setFillColorRGB(0, 0, 0)          # 纯黑
    try:
        c.setFillAlpha(0.4)              # 40% 不透明度
    except Exception:
        pass  # 旧版 reportlab 不支持透明度时降级为纯黑

    # 移动到页面中心，旋转 45 度，逐行绘制水印
    cx, cy = width / 2, height / 2
    c.saveState()
    c.translate(cx, cy)
    c.rotate(45)

    # 计算多行文本总高度，使整体垂直居中
    total_h = sum(
        (s if isinstance(s, (int, float)) else 10) + 6
        for _, s in [(t, s) for t, s in (item if isinstance(item, tuple) else (item, 10) for item in watermark_lines)]
    )
    y_pos = total_h / 2

    for item in watermark_lines:
        text, size = item if isinstance(item, tuple) else (item, 10)
        c.setFont(font_name, size)
        c.drawCentredString(0, y_pos, text)
        y_pos -= size + 6

    c.restoreState()
    c.save()
    buffer.seek(0)
    return buffer


def add_watermark_to_pdf(input_path, output_path, watermark_lines):
    """
    给 PDF 每页添加水印文本（支持中文）。
    watermark_lines: [(文本, 字号), ...]

    流程：reportlab 生成水印页（嵌入中文字体） → pypdf merge_page 叠加到每页。
    reportlab 正确嵌入中文字体子集，pypdf 合并时保留字体，确保任何阅读器都能渲染。
    """
    reader = PdfReader(input_path)
    writer = PdfWriter()

    # 检查是否有页面
    if len(reader.pages) == 0:
        writer.append(reader)
        with open(output_path, "wb") as f:
            writer.write(f)
        return 0

    # 获取原页面尺寸
    first_page = reader.pages[0]
    mediabox = first_page.mediabox
    width = float(mediabox[2]) - float(mediabox[0])
    height = float(mediabox[3]) - float(mediabox[1])

    # 创建水印 PDF
    watermark_buffer = _create_watermark_page(watermark_lines, width, height)
    watermark_reader = PdfReader(watermark_buffer)
    watermark_page = watermark_reader.pages[0]

    modified_count = 0
    for page in reader.pages:
        # 叠加水印页
        page.merge_page(watermark_page)
        writer.add_page(page)
        modified_count += 1

    with open(output_path, "wb") as f:
        writer.write(f)

    return modified_count


# ──────────────────────────────────────────────
#  打印功能
# ──────────────────────────────────────────────


def load_config():
    """加载配置文件"""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(config):
    """保存配置文件"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    print(f"配置已保存到: {CONFIG_FILE}")


def get_printers():
    """获取系统可用打印机列表"""
    try:
        result = subprocess.run(
            [
                "powershell",
                "-Command",
                "Get-CimInstance -ClassName Win32_Printer | Select-Object Name | Format-Table -HideTableHeaders -AutoSize",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        printers = [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip() and not line.strip().startswith("----")
        ]
        return printers
    except subprocess.SubprocessError as e:
        print(f"获取打印机列表失败: {e}")
        return []


def find_pdf_files():
    """查找同目录下的所有 PDF 文件"""
    pdf_files = sorted(glob.glob(str(Path(__file__).parent / "*.pdf")))
    return pdf_files


def get_pdf_info(pdf_path):
    """简易获取 PDF 信息（页数、文件名等）"""
    pdf_path = Path(pdf_path)
    size = pdf_path.stat().st_size
    size_str = f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.2f} MB"

    # 尝试从 PDF 解析页数（精确匹配 /Type /Page，排除 /Type /Pages）
    pages = "?"
    try:
        with open(pdf_path, "rb") as f:
            content = f.read()
        text = content.decode("latin-1")
        page_matches = re.findall(r'/Type\s+/Page(?:\s|/|$)', text)
        pages = str(len(page_matches))
    except Exception:
        pass

    return {
        "name": pdf_path.name,
        "size": size_str,
        "pages": pages,
    }


def select_pdf_file():
    """让用户选择要打印的 PDF 文件"""
    pdf_files = find_pdf_files()
    if not pdf_files:
        print("\n⚠ 未在同目录下找到任何 PDF 文件。")
        print("请将 PDF 文件放在脚本所在目录，或选择以测试页方式打印。")
        return None

    print("\n📄 同目录下找到以下 PDF 文件:")
    for i, pdf in enumerate(pdf_files, 1):
        info = get_pdf_info(pdf)
        print(f"  {i}. {info['name']}  ({info['size']}, {info['pages']}页)")

    print(f"  {len(pdf_files) + 1}. 不使用PDF，打印测试页")

    choice = input(f"\n请选择要打印的 PDF（1-{len(pdf_files) + 1}）: ").strip()
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(pdf_files):
            return pdf_files[idx]
        elif idx == len(pdf_files):
            return None  # 选择测试页
        print("序号无效")
        return None

    # 尝试直接按文件名匹配
    choice_lower = choice.lower()
    for pdf in pdf_files:
        if choice_lower in Path(pdf).name.lower():
            return pdf

    print("未找到匹配的 PDF 文件")
    return None


def print_test_page(printer_name, copies=1):
    """打印纯文本测试页（通过记事本打印）"""
    test_file = Path(__file__).parent / "print_test.txt"
    test_content = f"""========================================
          打印机测试页
========================================
打印机: {printer_name}
时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
份数: {copies}
========================================
这是打印机测试脚本生成的测试页——by ywpc05
========================================
"""
    test_file.write_text(test_content, encoding="utf-8")

    success = True
    for i in range(copies):
        try:
            subprocess.run(
                [
                    "powershell",
                    "-Command",
                    f'Start-Process -FilePath "notepad.exe" -ArgumentList "/pt ""{test_file}"" ""{printer_name}""" -NoNewWindow -Wait',
                ],
                check=True,
                timeout=30,
            )
            print(f"  [{i+1}/{copies}] 测试页打印任务已发送")
        except subprocess.TimeoutExpired:
            print(f"  [{i+1}/{copies}] 打印超时（可能已正常打印）")
        except subprocess.SubprocessError as e:
            print(f"  [{i+1}/{copies}] 打印测试页失败: {e}")
            success = False
        time.sleep(1)

    # 清理测试文件
    if test_file.exists():
        test_file.unlink()

    return success


SUMATRA_PATH = str(Path(__file__).parent / "SumatraPDF-64.exe")
FIREFOX_PATH = "D:\\Software\\Mozilla Firefox\\firefox.exe"


def print_pdf_via_sumatra(pdf_path, printer_name, copies=1):
    """
    使用 SumatraPDF 命令行静默打印 PDF（推荐方式）。
    SumatraPDF 是专为命令行打印设计的阅读器，无窗口、无弹窗。
    参数：
      -print-to <printer>  → 指定打印机
      -silent              → 静默模式
    """
    sumatra = Path(SUMATRA_PATH)
    if not sumatra.exists():
        print(f"  ⚠ SumatraPDF 未找到: {SUMATRA_PATH}")
        return False

    success = True
    for i in range(copies):
        try:
            cmd = [
                str(sumatra),
                "-print-to", printer_name,
                "-silent",
                str(pdf_path),
            ]
            ret = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )

            if ret.returncode == 0:
                print(f"  [{i+1}/{copies}] ✅ SumatraPDF 打印任务已发送到 [{printer_name}]")
            else:
                stderr = ret.stderr.strip()
                stdout = ret.stdout.strip()
                detail = stderr or stdout or "(无输出)"
                print(f"  [{i+1}/{copies}] SumatraPDF 返回: {detail}")
                # SumatraPDF 非0返回可能只是警告，不算失败
                print(f"  [{i+1}/{copies}] 打印任务已发送（返回码: {ret.returncode}）")
        except subprocess.TimeoutExpired:
            print(f"  [{i+1}/{copies}] SumatraPDF 超时（可能已提交）")
        except Exception as e:
            print(f"  [{i+1}/{copies}] SumatraPDF 异常: {e}")
            success = False
        time.sleep(1)

    return success


def _get_default_printer():
    """获取系统当前默认打印机"""
    try:
        ps = (
            'Get-CimInstance -ClassName Win32_Printer '
            '-Filter "Default=$true" | Select-Object -ExpandProperty Name'
        )
        r = subprocess.run(
            ["powershell", "-Command", ps],
            capture_output=True, text=True, timeout=10,
        )
        name = r.stdout.strip()
        return name if name else None
    except Exception:
        return None


def _set_default_printer(printer_name):
    """设置系统默认打印机"""
    try:
        ps = (
            f'$p = Get-CimInstance -ClassName Win32_Printer '
            f'-Filter "Name=\'{printer_name}\'"; '
            f'Invoke-CimMethod -InputObject $p -MethodName SetDefaultPrinter | Out-Null'
        )
        r = subprocess.run(
            ["powershell", "-Command", ps],
            capture_output=True, text=True, timeout=15,
        )
        return r.returncode == 0
    except Exception:
        return False


def print_pdf_via_firefox(pdf_path, printer_name, copies=1):
    """
    使用 Firefox 命令行静默打印 PDF。
    策略：临时将目标打印机设为系统默认 → Firefox -print 会自动发到默认打印机 → 恢复原默认。
    Firefox 没有 '指定打印机' 的 CLI 参数，这是唯一可靠的方式。
    """
    firefox = Path(FIREFOX_PATH)
    if not firefox.exists():
        print(f"  ⚠ Firefox 未找到: {FIREFOX_PATH}")
        return False

    # 保存当前默认打印机
    original_default = _get_default_printer()
    if original_default:
        print(f"  当前默认打印机: [{original_default}]")

    # 设置目标打印机为默认
    print(f"  临时切换到默认打印机: [{printer_name}]...")
    if not _set_default_printer(printer_name):
        print(f"  ⚠ 设置默认打印机失败，尝试继续...")

    # 将 PDF 路径转为 file:// URL
    pdf_url = pdf_path.replace("\\", "/")
    if pdf_url[1:2] == ":":
        pdf_url = f"file:///{pdf_url}"
    else:
        pdf_url = f"file://{pdf_url}"

    success = True
    try:
        for i in range(copies):
            # Firefox 打印参数组合 - 多尝试几种语法
            cmd_variants = [
                # 方式1: -print URL (老语法)
                [str(firefox), "-print", pdf_url, "-silent"],
                # 方式2: URL + -print -printmode pdf
                [str(firefox), pdf_url, "-print", "-printmode", "pdf", "-silent"],
                # 方式3: -headless -print
                [str(firefox), "-headless", pdf_url, "-print"],
            ]

            printed = False
            for idx, cmd in enumerate(cmd_variants):
                try:
                    ret = subprocess.run(
                        cmd,
                        capture_output=True, text=True, timeout=40,
                        creationflags=0x08000000,  # CREATE_NO_WINDOW
                    )
                    if ret.returncode == 0:
                        print(f"  [{i+1}/{copies}] ✅ Firefox 打印任务已发送 (方式{idx+1})")
                        printed = True
                        break
                    stderr = ret.stderr.strip()
                    if stderr:
                        print(f"  [方式{idx+1}] Firefox: {stderr[:100]}")
                except subprocess.TimeoutExpired:
                    # 超时通常意味着任务已提交到打印机后台，标记成功
                    print(f"  [{i+1}/{copies}] ✅ Firefox 打印超时，任务可能已提交 (方式{idx+1})")
                    printed = True
                    break
                except Exception as e:
                    print(f"  [方式{idx+1}] 异常: {e}")

            if not printed:
                print(f"  [{i+1}/{copies}] ❌ Firefox 所有打印方式均未成功")
                success = False

            time.sleep(2)

    finally:
        # 恢复原默认打印机
        if original_default and original_default != printer_name:
            print(f"  恢复默认打印机: [{original_default}]...")
            _set_default_printer(original_default)

    return success


def print_pdf_via_shell(pdf_path, printer_name, copies=1):
    """
    使用 Windows Shell API (ShellExecuteW) 打印 PDF
    - 使用 "printto" 动词，将文件发送到指定打印机
    如果系统未安装 PDF 阅读器，此方式会失败（返回错误31）。
    """
    success = True
    for i in range(copies):
        try:
            ret = ctypes.windll.shell32.ShellExecuteW(
                None,
                "printto",
                str(pdf_path),
                f'"{printer_name}",,',
                None,
                0,  # SW_HIDE
            )

            if ret <= 32:
                error_msg = {
                    0: "内存不足",
                    2: "文件未找到",
                    3: "路径未找到",
                    5: "访问被拒绝",
                    8: "内存不足",
                    26: "RPC 失败",
                    27: "文件不是有效的 Win32 应用程序",
                    28: "操作不支持",
                    29: "没有关联的程序",
                    30: "Shell DLL 加载失败",
                    31: "无默认关联程序",
                    32: "DLL 加载失败",
                }.get(ret, f"未知错误({ret})")
                print(f"  [{i+1}/{copies}] 打印失败: {error_msg}")
                success = False
            else:
                print(f"  [{i+1}/{copies}] PDF 打印任务已发送到 [{printer_name}]")
        except Exception as e:
            print(f"  [{i+1}/{copies}] 打印异常: {e}")
            success = False
        time.sleep(1)

    return success


def print_pdf_via_raw(pdf_path, printer_name, copies=1):
    """
    使用 Windows Print Spooler API (winspool.drv) 直接发送 PDF RAW 数据到打印机。
    不依赖任何系统 PDF 阅读器，直接将文件二进制内容发送给打印机。
    
    注意：此方式要求打印机硬件/驱动支持解析 PDF 数据流。
         大部分现代 PCL6/PostScript 打印机都支持直接打印 PDF。
    """
    try:
        winspool = ctypes.WinDLL("winspool.drv")
    except Exception as e:
        print(f"  ❌ 无法加载 winspool.drv: {e}")
        return False

    # 定义函数签名
    winspool.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), wintypes.LPVOID]
    winspool.OpenPrinterW.restype = wintypes.BOOL
    winspool.ClosePrinter.argtypes = [wintypes.HANDLE]
    winspool.ClosePrinter.restype = wintypes.BOOL
    winspool.StartDocPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID]
    winspool.StartDocPrinterW.restype = wintypes.BOOL
    winspool.StartPagePrinter.argtypes = [wintypes.HANDLE]
    winspool.StartPagePrinter.restype = wintypes.BOOL
    winspool.WritePrinter.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    winspool.WritePrinter.restype = wintypes.BOOL
    winspool.EndPagePrinter.argtypes = [wintypes.HANDLE]
    winspool.EndPagePrinter.restype = wintypes.BOOL
    winspool.EndDocPrinter.argtypes = [wintypes.HANDLE]
    winspool.EndDocPrinter.restype = wintypes.BOOL

    # 打开打印机
    printer_handle = wintypes.HANDLE()
    ret = winspool.OpenPrinterW(printer_name, ctypes.byref(printer_handle), None)
    if not ret:
        error = ctypes.GetLastError()
        print(f"  ❌ 无法打开打印机 (错误码: {error})")
        return False

    success = True
    try:
        with open(pdf_path, "rb") as f:
            pdf_data = f.read()

        for i in range(copies):
            doc_name = f"PDF_Print_{Path(pdf_path).name}_{datetime.datetime.now().strftime('%H%M%S')}"
            doc_name_w = ctypes.create_unicode_buffer(doc_name)
            datatype_w = ctypes.create_unicode_buffer("RAW")

            # DOC_INFO_1 结构
            doc_info = (ctypes.c_wchar_p * 3)(
                ctypes.addressof(doc_name_w),
                None,
                ctypes.addressof(datatype_w),
            )

            ret = winspool.StartDocPrinterW(printer_handle, 1, doc_info)
            if not ret:
                error = ctypes.GetLastError()
                print(f"  [{i+1}/{copies}] StartDocPrinter 失败 (错误码: {error})")
                success = False
                continue

            ret = winspool.StartPagePrinter(printer_handle)
            if not ret:
                error = ctypes.GetLastError()
                print(f"  [{i+1}/{copies}] StartPagePrinter 失败 (错误码: {error})")
                winspool.EndDocPrinter(printer_handle)
                success = False
                continue

            bytes_written = wintypes.DWORD()
            ret = winspool.WritePrinter(
                printer_handle,
                pdf_data,
                len(pdf_data),
                ctypes.byref(bytes_written),
            )
            if not ret:
                error = ctypes.GetLastError()
                print(f"  [{i+1}/{copies}] WritePrinter 失败 (错误码: {error})")
                success = False
            else:
                print(f"  [{i+1}/{copies}] PDF 原始数据已发送 ({bytes_written.value / 1024:.1f} KB)")

            winspool.EndPagePrinter(printer_handle)
            winspool.EndDocPrinter(printer_handle)
            time.sleep(1)

    except Exception as e:
        print(f"  ❌ 打印异常: {e}")
        success = False
    finally:
        winspool.ClosePrinter(printer_handle)

    return success


def print_pdf(pdf_path, printer_name, copies=1):
    """打印 PDF 文件，自动添加水印。
    自动选择打印方式：
    1. ShellExecuteW (需要系统注册了 PDF 阅读器)
    2. WritePrinter RAW 直打 (不需要 PDF 阅读器)
    """
    pdf_file = Path(pdf_path)
    now = datetime.datetime.now()

    # 构建水印文本行（斜向居中显示）
    watermark_lines = [
        ("打印机测试页", 20),
        (f"打印机: {printer_name}", 12),
        (f"时间: {now.strftime('%Y-%m-%d %H:%M:%S')}", 12),
        (f"份数: {copies}", 12),
        ("——by ywpc05", 10),
    ]

    # 临时水印文件路径
    watermarked_path = pdf_file.parent / f"~watermarked_{pdf_file.stem}.pdf"

    try:
        # 添加水印
        print(f"  正在添加水印...")
        modified_count = add_watermark_to_pdf(
            str(pdf_file), str(watermarked_path), watermark_lines
        )
        print(f"  水印处理完成")

        # 尝试方式1: SumatraPDF（最可靠，静默无窗口，直接指定打印机）
        print(f"  → 尝试 SumatraPDF 静默打印...")
        if print_pdf_via_sumatra(str(watermarked_path), printer_name, copies):
            return True

        # 尝试方式2: ShellExecuteW
        print(f"  → 尝试 Shell API 打印...")
        if print_pdf_via_shell(str(watermarked_path), printer_name, copies):
            return True

        # 尝试方式3: Firefox 静默打印
        print(f"  → 尝试 Firefox 无界面打印...")
        if print_pdf_via_firefox(str(watermarked_path), printer_name, copies):
            return True

        # 尝试方式4: WritePrinter RAW 直打
        print(f"  → 尝试 RAW 直打（直接将 PDF 数据发送到打印机）...")
        if print_pdf_via_raw(str(watermarked_path), printer_name, copies):
            return True

        # 都失败了
        print(f"  ❌ 所有打印方式均失败")
        return False
    finally:
        # 清理临时文件
        if watermarked_path.exists():
            try:
                watermarked_path.unlink()
            except PermissionError:
                pass  # 文件可能仍在使用中


def print_file(config):
    """根据配置执行打印：测试页 或 PDF 文件"""
    printer_name = config["printer_name"]
    copies = config["copies"]
    pdf_file = config.get("pdf_file", "")

    if pdf_file and Path(pdf_file).exists():
        print_pdf(pdf_file, printer_name, copies)
    else:
        print("  打印测试页（无 PDF 文件配置）")
        print_test_page(printer_name, copies)


def select_printer():
    """选择打印机，支持序号和名称输入"""
    printers = get_printers()
    if not printers:
        print("未检测到可用打印机，请手动输入名称。")
        return input("请输入打印机名称: ").strip()

    print("\n可用打印机列表:")
    for i, p in enumerate(printers, 1):
        print(f"  {i}. {p}")

    choice = input("\n请选择打印机（输入序号或名称）: ").strip()
    if not choice:
        print("输入不能为空！")
        return None

    # 尝试按序号匹配
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(printers):
            return printers[idx]
        print(f"序号无效，请输入 1-{len(printers)} 之间的数字")
        return None

    # 按名称匹配
    return choice


def setup_config():
    """交互式配置"""
    print("\n===== 打印机测试脚本配置 =====")

    printer_name = select_printer()
    if not printer_name:
        return None

    # 询问是否打印 PDF
    pdf_file = select_pdf_file()

    interval_str = input("请输入打印间隔（分钟，默认30）: ").strip()
    try:
        interval = int(interval_str) if interval_str else 30
        if interval < 1:
            print("间隔时间必须大于0，使用默认值30分钟")
            interval = 30
    except ValueError:
        print("输入无效，使用默认值30分钟")
        interval = 30

    copies_str = input("请输入每次打印份数（默认3）: ").strip()
    try:
        copies = int(copies_str) if copies_str else 3
        if copies < 1:
            print("份数必须大于0，使用默认值3份")
            copies = 3
    except ValueError:
        print("输入无效，使用默认值3份")
        copies = 3

    config = {
        "printer_name": printer_name,
        "interval_minutes": interval,
        "copies": copies,
    }
    if pdf_file:
        config["pdf_file"] = pdf_file

    save_config(config)
    return config


def run_tests(config):
    """开始循环测试"""
    printer = config["printer_name"]
    interval = config["interval_minutes"]
    copies = config["copies"]
    pdf_file = config.get("pdf_file", "")

    print(f"\n{'=' * 50}")
    print(f"  打印机压力测试")
    print(f"{'=' * 50}")
    print(f"  目标打印机: {printer}")
    print(f"  打印间隔:   {interval} 分钟")
    print(f"  每次份数:   {copies} 份")
    if pdf_file and Path(pdf_file).exists():
        print(f"  打印文件:   {Path(pdf_file).name}")
        print(f"  水印:       已启用（打印机信息、时间、份数）")
    else:
        print(f"  打印类型:   测试页（文本）")
    print(f"{'=' * 50}")

    count = 0
    while True:
        count += 1
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{now}] 第 {count} 轮测试开始（{copies}份）...")

        print_file(config)

        next_time = datetime.datetime.now() + datetime.timedelta(minutes=interval)
        next_str = next_time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"  等待 {interval} 分钟，下一轮预计: {next_str}")

        try:
            time.sleep(interval * 60)
        except KeyboardInterrupt:
            print(f"\n\n测试已手动停止（共完成 {count} 轮）")
            break


def main():
    print("打印机压力测试工具")
    print("-" * 30)

    config = load_config()
    if config:
        print(f"\n已找到保存的配置:")
        print(f"  打印机: {config.get('printer_name', '未设置')}")
        print(f"  间隔:   {config.get('interval_minutes', 30)} 分钟")
        print(f"  份数:   {config.get('copies', 3)} 份")
        pdf_file = config.get("pdf_file", "")
        if pdf_file and Path(pdf_file).exists():
            info = get_pdf_info(pdf_file)
            print(f"  PDF文件: {info['name']} ({info['size']}, {info['pages']}页)")
            print(f"  水印:    已启用")
        else:
            print(f"  打印类型: 测试页")

        choice = input("\n使用此配置？(y/n，默认为y): ").strip().lower()
        if choice not in ("n", "no"):
            run_tests(config)
            return

    # 重新配置
    config = setup_config()
    if config:
        run_tests(config)
    else:
        print("配置失败，退出。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n程序已退出。")
        sys.exit(0)