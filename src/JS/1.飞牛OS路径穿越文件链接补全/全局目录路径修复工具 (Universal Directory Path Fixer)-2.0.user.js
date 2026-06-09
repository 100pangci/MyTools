// ==UserScript==
// @name         全局目录路径修复工具 (Universal Directory Path Fixer)
// @namespace    http://tampermonkey.net/
// @version      2.0
// @description  全局匹配：检测 URL 中是否包含 path/size 参数，自动修复目录遍历时的 404 问题。
// @author       YourName
// @match        *://*/*
// @grant        none
// @run-at       document-end
// ==/UserScript==

(function() {
    'use strict';

    // === 核心配置与检测 ===

    // 1. 获取当前 URL 参数
    const urlParams = new URLSearchParams(window.location.search);
    const currentSize = urlParams.get('size'); // 检测是否存在 size 参数

    // 2. 安全锁：如果当前 URL 没有 size 参数，直接停止运行。
    // 这防止了脚本破坏没有该特征的正常网站（如百度、B站等）。
    if (!currentSize) {
        return;
    }

    console.log('目录浏览脚本已激活：检测到 size 参数，正在修正链接...');

    // === 链接修复逻辑 ===

    const basePath = window.location.pathname; // 获取基础路径，例如 /app-center-static/...
    const links = document.querySelectorAll('a'); // 获取页面所有链接

    links.forEach(link => {
        const href = link.getAttribute('href');

        // 排除无效链接、锚点(#)、JS代码、以及已经是完整 http 开头的绝对路径
        if (!href || href.startsWith('#') || href.startsWith('javascript:') || href.startsWith('http') || href.startsWith('mailto:')) {
            return;
        }

        // --- 情况 A: 返回上一级 (Parent Directory) ---
        // 通常表现为链接是 "../" 或者文本内容包含 "Parent Directory"
        if (href === '../' || link.innerText.includes('Parent Directory') || link.innerText.includes('上一级')) {
            // 逻辑：删除 currentSize 末尾的一层目录
            // 例如: ../vol1/1004/ -> ../vol1/

            // 移除末尾斜杠（如果有），再移除最后一个目录
            let parentSize = currentSize.replace(/\/$/, '').replace(/[^/]+$/, '');

            // 修正后的 parentSize 如果末尾没有斜杠且不为空，最好补上（视具体服务器规则而定，这里保持原样通常比较安全）
            if(parentSize === '') parentSize = '/'; // 防止变成空导致参数丢失

            link.href = basePath + '?size=' + parentSize;
            return;
        }

        // --- 情况 B: 进入子文件夹或打开文件 ---

        // 1. 确保基础路径以 "/" 结尾
        let baseSize = currentSize;
        if (!baseSize.endsWith('/')) {
            baseSize += '/';
        }

        // 2. 拼接新的路径
        // 这里的 href 就是文件夹名，例如 "1004/" 或 "file.txt"
        let newSize = baseSize + href;

        // 3. 构造最终链接
        link.href = basePath + '?size=' + newSize;

        // 可选：为了视觉上确认脚本生效，可以将修改过的链接颜色变一下（如果不需要可删除下面这行）
        // link.style.color = 'green';
    });

})();
