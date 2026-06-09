# =================================================================================
# 【FFmpeg 视频一键压缩脚本 - v4.2 自定义输出格式】
#
# 更新日志:
# v4.2: 新增自定义输出格式功能（支持 mp4, mkv, wmv 等），并修复 MP4 字幕流报错问题。
# v4.1: 固定输出文件扩展名为 .mkv，以获得最佳兼容性。
# v4.0: 新增 NVIDIA CUDA 硬件加速支持。
# v3.0: 智能检测 ffmpeg (优先使用环境变量)。
# v2.0: 修复了扫描根目录文件的 Bug。
#
# 使用说明：
# 1. 确保您的电脑有 NVIDIA 显卡并已安装最新的驱动程序。
# 2. (推荐) 确保 ffmpeg 已添加到系统环境变量。
# 3. (备用) 或者，把 ffmpeg.exe 放在这个脚本的同一个文件夹里。
# 4. 把要压缩的视频放进此文件夹或其子文件夹。
# 5. 双击 "双击我运行压缩.bat" 文件来启动。
# =================================================================================
# ---【用户配置区：请根据需要修改这里的设置】---

# 1. 编码模式选择: 'CPU' 或 'CUDA'
$ENCODE_MODE = "CPU" # 在这里切换 'CPU' 或 'CUDA'

# 2. 要处理的视频文件类型 (扩展名)
$EXTENSIONS = @(".mp4", ".mov", ".mkv", ".avi", ".mts", ".mpg", ".mpeg", ".flv", ".wmv", ".ts")

# 3. 输出文件夹名称
$OUTPUT_FOLDER_NAME = "【压缩完成】"

# 4. 自定义输出视频格式 (请带上点号，例如: ".mp4", ".mkv", ".wmv", ".avi")
$OUTPUT_FORMAT = ".mp4" 

# --- CPU 编码配置 (当 $ENCODE_MODE = 'CPU' 时生效) ---
$CPU_CRF_VALUE = 25      # CRF值 (23-28)，越小画质越好
$CPU_PRESET = "medium"   # 压缩速度预设 (例如: medium, slow)

# --- NVIDIA CUDA 编码配置 (当 $ENCODE_MODE = 'CUDA' 时生效) ---
$CUDA_SCALE_HEIGHT = 0    # 限制输出视频的最大高度 (例如 1080, 720)。设为 0 表示不缩放。
$CUDA_CQ_VALUE = 22       # CQ 质量值 (18-28)，越小画质越好
$CUDA_MAX_BITRATE = "8M"  # 限制最大码率 (例如 "5M", "8M")。设为 "0" 表示不限制。
$CUDA_PRESET = "p5"       # 预设 (p1-p7), p5=slow, p6=medium, p7=fast。推荐 p5。
$CUDA_TUNE = "hq"         # 调优 (hq=高质量, ll=低延迟, ull=超低延迟)。推荐 hq。
$CUDA_AUDIO_BITRATE = "192k" # 音频比特率 (例如 "128k", "192k", "256k")

# ---【脚本核心逻辑：通常无需修改】---
try {
    # 获取脚本所在的当前目录
    $SourceDir = $PSScriptRoot; if (-not $SourceDir) { $SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Definition }
    $OutputDir = Join-Path -Path $SourceDir -ChildPath $OUTPUT_FOLDER_NAME
    if (-not (Test-Path -Path $OutputDir)) { New-Item -ItemType Directory -Path $OutputDir | Out-Null }
    
    # 智能检查 ffmpeg
    $ffmpegPath = ""; if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { $ffmpegPath = "ffmpeg"; Write-Host "成功: 在系统环境变量中找到 ffmpeg。" -ForegroundColor Green } else { $localFfmpegPath = Join-Path -Path $SourceDir -ChildPath "ffmpeg.exe"; if (Test-Path -Path $localFfmpegPath) { $ffmpegPath = $localFfmpegPath; Write-Host "提示: 使用脚本同目录的 ffmpeg.exe。" -ForegroundColor Yellow } else { Write-Host "错误：找不到 ffmpeg！" -ForegroundColor Red; pause; exit } }
    
    # 扫描文件
    Write-Host "开始扫描视频文件..." -ForegroundColor Cyan
    $videoFiles = Get-ChildItem -Path $SourceDir -Recurse | Where-Object { $EXTENSIONS -contains $_.Extension.ToLower() -and $_.PSIsContainer -eq $false }
    $videoFiles = $videoFiles | Where-Object { $_.DirectoryName -notlike "$OutputDir*" }
    
    if ($videoFiles.Count -eq 0) { Write-Host "没有找到任何需要处理的视频文件。" -ForegroundColor Yellow; pause; exit }
    Write-Host "共找到 $($videoFiles.Count) 个视频文件，使用 $ENCODE_MODE 模式处理..." -ForegroundColor Green
    
    # 遍历处理
    foreach ($file in $videoFiles) {
        Write-Host "------------------------------------------------------------"
        Write-Host "正在处理: $($file.Name)" -ForegroundColor White
        
        # ---【核心修改处】---
        # 动态拼接用户自定义的扩展名
        $outputFile = Join-Path -Path $OutputDir -ChildPath "$($file.BaseName)$OUTPUT_FORMAT"
        
        if (Test-Path -Path $outputFile) {
            Write-Host "跳过: 输出文件 $($file.BaseName)$OUTPUT_FORMAT 已存在。" -ForegroundColor Yellow
            continue
        }

        # --- 字幕兼容性处理 ---
        # 解释：MP4/WMV 格式不支持直接复制复杂字幕流(如PGS/SRT)。如果不加判断强行复制，ffmpeg 会报错终止。
        $subtitleArg = ""
        if ($OUTPUT_FORMAT.ToLower() -eq ".mkv") {
            $subtitleArg = "-c:s copy" # 只有 mkv 格式才保留字幕流
        }
        
        # 根据选择的模式构建 ffmpeg 参数
        $ffmpegArgs = ""
        if ($ENCODE_MODE -eq "CUDA") {
            # --- 构建 CUDA 命令 ---
            $vf_filter = "format=yuv420p" # 基础滤镜，确保像素格式正确
            if ($CUDA_SCALE_HEIGHT -gt 0) {
                $vf_filter = "scale=-2:$CUDA_SCALE_HEIGHT," + $vf_filter
            }
            
            $ffmpegArgs = "-hwaccel cuda -i `"$($file.FullName)`" -vf `"$vf_filter`" -c:v h264_nvenc -preset $CUDA_PRESET -tune $CUDA_TUNE -rc vbr -cq $CUDA_CQ_VALUE -b:v 0"
            
            if ($CUDA_MAX_BITRATE -ne "0") {
                $ffmpegArgs += " -maxrate $CUDA_MAX_BITRATE"
            }
            $ffmpegArgs += " -c:a aac -b:a $CUDA_AUDIO_BITRATE $subtitleArg"
            
        } else {
            # --- 构建 CPU 命令 ---
            $ffmpegArgs = "-i `"$($file.FullName)`" -c:v libx264 -preset $CPU_PRESET -crf $CPU_CRF_VALUE -c:a copy $subtitleArg"
        }
        
        $ffmpegArgs += " `"$outputFile`""
        
        # 执行命令
        Write-Host "执行模式: $ENCODE_MODE, 输出为: $($file.BaseName)$OUTPUT_FORMAT"
        $process = Start-Process -FilePath $ffmpegPath -ArgumentList $ffmpegArgs -NoNewWindow -Wait -PassThru
        
        if ($process.ExitCode -eq 0) {
            Write-Host "成功: $($file.Name) 已压缩完成！" -ForegroundColor Green
        } else {
            Write-Host "失败: 处理 $($file.Name) 时发生错误！请检查 ffmpeg 输出日志。" -ForegroundColor Red
        }
    }
    
    Write-Host "------------------------------------------------------------"
    Write-Host "全部任务已完成！" -ForegroundColor Magenta
} catch {
    Write-Host "脚本执行过程中发生未知错误：" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
}
pause