import assert from "node:assert/strict";
import test from "node:test";

import { isSafeLink, renderMarkdown } from "../../../src/bluewhale_agent/web/static/js/markdown.js";

class FakeNode {
  constructor(tagName = null, text = "") {
    this.tagName = tagName;
    this.text = text;
    this.children = [];
    this.attributes = {};
    this.className = "";
  }

  append(...children) {
    this.children.push(...children);
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  set textContent(value) {
    this.text = String(value);
    this.children = [];
  }

  get textContent() {
    return this.text + this.children.map((child) => child.textContent).join("");
  }
}

const documentRef = {
  createElement(tagName) {
    return new FakeNode(tagName);
  },
  createTextNode(text) {
    return new FakeNode(null, text);
  },
};

function tags(node) {
  return [node.tagName, ...node.children.flatMap(tags)].filter(Boolean);
}

test("renders common Markdown blocks and inline formatting", () => {
  const rendered = renderMarkdown(
    "# 标题\n\n**粗体**、*斜体*、`code` 和 ~~删除~~\n\n- 一\n- 二\n\n> 引用\n\n```js\nalert('text')\n```",
    documentRef,
  );

  assert.deepEqual(tags(rendered), ["div", "h1", "p", "strong", "em", "code", "del", "ul", "li", "li", "blockquote", "p", "pre", "code"]);
  assert.match(rendered.textContent, /标题.*粗体.*删除.*引用.*alert/s);
});

test("keeps raw HTML as text and blocks unsafe links", () => {
  const rendered = renderMarkdown(
    "<script>alert(1)</script> [危险](javascript:alert(1)) [安全](https://example.com)",
    documentRef,
  );
  const anchors = collect(rendered, "a");

  assert.match(rendered.textContent, /<script>alert\(1\)<\/script>/);
  assert.equal(anchors.length, 1);
  assert.equal(anchors[0].attributes.href, "https://example.com");
  assert.equal(anchors[0].attributes.rel, "noreferrer noopener");
});

test("accepts only safe link schemes and relative paths", () => {
  assert.equal(isSafeLink("https://example.com"), true);
  assert.equal(isSafeLink("mailto:hello@example.com"), true);
  assert.equal(isSafeLink("./docs/readme.md"), true);
  assert.equal(isSafeLink("javascript:alert(1)"), false);
  assert.equal(isSafeLink("java\tscript:alert(1)"), false);
  assert.equal(isSafeLink("data:text/html,bad"), false);
  assert.equal(isSafeLink("//evil.example"), false);
});

function collect(node, tagName) {
  return [
    ...(node.tagName === tagName ? [node] : []),
    ...node.children.flatMap((child) => collect(child, tagName)),
  ];
}
