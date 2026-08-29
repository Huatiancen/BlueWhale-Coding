const COPY_LABEL = "复制消息";
const COPIED_LABEL = "已复制";
const COPY_ICON = "⧉";
const COPIED_ICON = "✓";

export function createMessageCopyButton(text, options = {}) {
  const documentRef = options.documentRef || document;
  const clipboard = options.clipboard || navigator.clipboard;
  const onError = options.onError || (() => {});
  const setTimer = options.setTimer || setTimeout;
  const clearTimer = options.clearTimer || clearTimeout;
  const button = documentRef.createElement("button");
  let restoreTimer = null;

  button.type = "button";
  button.className = "message-copy-button";
  restoreCopyState(button);

  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      if (!clipboard?.writeText) throw new Error("Clipboard API unavailable");
      await clipboard.writeText(text);
      if (restoreTimer !== null) clearTimer(restoreTimer);
      button.textContent = COPIED_ICON;
      button.setAttribute("aria-label", COPIED_LABEL);
      button.title = COPIED_LABEL;
      restoreTimer = setTimer(() => {
        restoreCopyState(button);
        restoreTimer = null;
      }, 1400);
    } catch (_error) {
      restoreCopyState(button);
      onError("无法复制消息，请检查剪贴板权限。");
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

function restoreCopyState(button) {
  button.textContent = COPY_ICON;
  button.setAttribute("aria-label", COPY_LABEL);
  button.title = COPY_LABEL;
}
