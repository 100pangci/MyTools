# 此仓库用来收纳我自用的脚本小工具。

- PowerShell
  1. 一键压缩视频 - 需系统环境中/同目录下包含FFmpeg。
- Bat
  1. 图种生成 - 来源不详
  2. 删除🍐👁红的🐴 - 用来删掉（）网盘的智能看图。感谢：`https://xzonn.top/posts/Remove-Intelligent-Image-Viewer.html`
- Python
  1. 图片批量等比例缩小
  2. 将chatvveai的导出格式转为Open WebUI的导入格式
  3. excel多文件拆分合并
  4. 扫描文件树，可扫描everything支持的格式或自有格式。
  5. jp2转png
  6. Firefox书签转Tree，使用方法见：`https://github.com/100pangci/My-Firefox-Bookmark-Tree`
  7. 打印机压力测试脚本，可以定期发送打印任务，以测试打印机，PDF打印效果不佳，需搭配SumatraPDF使用。
   8. [token浪费器](src/Python/8.token浪费器/token_shit.py) - 用于压力测试 AI 模型 API，消耗 Token 资源
      - 支持多线程并发请求
      - 线程安全的统计信息（总消耗 token、tokens/秒、请求/秒）
      - 内置多种垃圾 prompt，随机选择并扩写
      - 支持 Ctrl+C 优雅关闭，输出最终统计
      - 使用示例：
        ```bash
        python token_shit.py -k "your-api-key" -m "qwen-turbo"
        python token_shit.py -k "your-api-key" -m "qwen-turbo" -c 10 --max-tokens 8000
        python token_shit.py -k "your-api-key" -u "https://api.example.com" -m "gpt-4"
        ```
- JS
  1. 飞牛OS路径穿越文件链接补全
  2. 内存替换运行内存
