import { renderUnifiedDiff } from "./diff-view.js";
import { renderMarkdown } from "./markdown.js";

export function renderArtifactInspector(elements, artifact, { onClose }) {
  elements.inspector.hidden = !artifact;
  elements.inspectorToolbar.replaceChildren();
  elements.inspectorContent.replaceChildren();
  if (!artifact) return;

  elements.inspectorTitle.textContent = artifact.path;
  const markdown = /\.(md|markdown)$/i.test(artifact.path);
  const modes = markdown ? ["预览", "源码", "差异"] : ["差异", "源码"];
  let active = modes[0];

  function draw() {
    elements.inspectorToolbar.replaceChildren();
    for (const mode of modes) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `inspector-mode${mode === active ? " active" : ""}`;
      button.textContent = mode;
      button.addEventListener("click", () => {
        active = mode;
        draw();
      });
      elements.inspectorToolbar.append(button);
    }
    elements.inspectorContent.replaceChildren();
    if (active === "预览") {
      const preview = renderMarkdown(artifact.after || artifact.currentContent || "");
      preview.classList.add("artifact-markdown");
      elements.inspectorContent.append(preview);
      return;
    }
    if (active === "差异") {
      elements.inspectorContent.append(
        renderUnifiedDiff(artifact.diff || "此历史记录没有保存差异。"),
      );
      return;
    }
    const pre = document.createElement("pre");
    pre.className = "artifact-code";
    pre.textContent = artifact.currentContent ?? artifact.after ?? "文件内容不可用。";
    elements.inspectorContent.append(pre);
  }

  elements.closeInspector.onclick = onClose;
  draw();
}
