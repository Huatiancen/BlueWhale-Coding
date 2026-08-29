export function clampPanelSize(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

export function nextPanelSizeFromKey(current, key, options) {
  const { min, max, step, growKey } = options;
  const shrinkKey = growKey === "ArrowRight" ? "ArrowLeft" : "ArrowRight";
  if (key === growKey) return clampPanelSize(current + step, min, max);
  if (key === shrinkKey) return clampPanelSize(current - step, min, max);
  return current;
}

export function setupPanelResizer(options) {
  const {
    handle,
    getSize,
    setSize,
    sizeFromPointer,
    min,
    max,
    growKey,
    step = 16,
  } = options;
  let dragging = false;

  const currentMax = () => (typeof max === "function" ? max() : max);
  const apply = (value) => {
    const size = clampPanelSize(value, min, currentMax());
    setSize(size);
    handle.setAttribute("aria-valuenow", String(Math.round(size)));
  };

  function move(event) {
    if (!dragging) return;
    apply(sizeFromPointer(event));
  }

  function finish() {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove("dragging");
    document.body.classList.remove("resizing-panels");
  }

  handle.addEventListener("pointerdown", (event) => {
    dragging = true;
    handle.classList.add("dragging");
    document.body.classList.add("resizing-panels");
    handle.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  });
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", finish);
  window.addEventListener("pointercancel", finish);
  handle.addEventListener("keydown", (event) => {
    const size = nextPanelSizeFromKey(getSize(), event.key, {
      min,
      max: currentMax(),
      step,
      growKey,
    });
    if (size === getSize()) return;
    apply(size);
    event.preventDefault();
  });
  apply(getSize());
}
