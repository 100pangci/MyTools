// ==UserScript==
// @name         内存替换运行内存
// @namespace    http://tampermonkey.net/
// @version      1.0.1
// @description  将网页界面中的“运行内存”自动替换为“内存”。
// @author       100pangci
// @match        *://*/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function () {
    'use strict';

    const TARGET_TEXT = '内存';
    const REPLACEMENTS = [
        ['运行内存', TARGET_TEXT],
        ['运存', TARGET_TEXT]
    ];
    const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEXTAREA', 'INPUT']);

    function replaceInTextNode(node) {
        if (!node || !node.nodeValue) {
            return;
        }

        let text = node.nodeValue;
        let changed = false;

        for (const [sourceText, targetText] of REPLACEMENTS) {
            if (text.includes(sourceText)) {
                text = text.split(sourceText).join(targetText);
                changed = true;
            }
        }

        if (changed) {
            node.nodeValue = text;
        }
    }

    function walkAndReplace(root) {
        if (!root) {
            return;
        }

        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
            acceptNode(node) {
                const parent = node.parentElement;
                if (!parent || SKIP_TAGS.has(parent.tagName)) {
                    return NodeFilter.FILTER_REJECT;
                }

                if (!node.nodeValue) {
                    return NodeFilter.FILTER_SKIP;
                }

                return REPLACEMENTS.some(([sourceText]) => node.nodeValue.includes(sourceText))
                    ? NodeFilter.FILTER_ACCEPT
                    : NodeFilter.FILTER_SKIP;
            }
        });

        const textNodes = [];
        while (walker.nextNode()) {
            textNodes.push(walker.currentNode);
        }

        textNodes.forEach(replaceInTextNode);
    }

    function handleMutations(mutations) {
        for (const mutation of mutations) {
            if (mutation.type === 'characterData') {
                replaceInTextNode(mutation.target);
                continue;
            }

            for (const node of mutation.addedNodes) {
                if (node.nodeType === Node.TEXT_NODE) {
                    replaceInTextNode(node);
                    continue;
                }

                if (node.nodeType === Node.ELEMENT_NODE) {
                    if (!SKIP_TAGS.has(node.tagName)) {
                        walkAndReplace(node);
                    }
                }
            }
        }
    }

    walkAndReplace(document.body);

    const observer = new MutationObserver(handleMutations);
    observer.observe(document.body, {
        childList: true,
        subtree: true,
        characterData: true
    });
})();