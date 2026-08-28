export async function detectDesktopBridge(timeoutMs = 1500) {
  if (window.pywebview?.api) return window.pywebview.api;
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => resolve(null), timeoutMs);
    window.addEventListener(
      "pywebviewready",
      () => {
        window.clearTimeout(timer);
        resolve(window.pywebview?.api || null);
      },
      { once: true },
    );
  });
}

async function requireSuccess(promise) {
  const result = await promise;
  if (!result?.ok) throw new Error(result?.error || "桌面操作失败");
  return result;
}

export function selectDesktopWorkspace(bridge) {
  return requireSuccess(bridge.select_workspace());
}

export function getDesktopWorkspaceState(bridge) {
  return requireSuccess(bridge.workspace_state());
}

export function getDesktopSecretState(bridge) {
  return requireSuccess(bridge.secret_state());
}

export function saveDesktopApiKey(bridge, value) {
  return requireSuccess(bridge.save_api_key(value));
}

export function clearDesktopApiKey(bridge) {
  return requireSuccess(bridge.clear_api_key());
}
