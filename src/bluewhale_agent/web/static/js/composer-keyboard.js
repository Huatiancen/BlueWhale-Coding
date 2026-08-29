export function shouldSubmitComposer(event, compositionActive = false) {
  const isImeConfirmation = event.keyCode === 229 || event.which === 229;
  return (
    event.key === "Enter" &&
    !event.shiftKey &&
    !event.isComposing &&
    !compositionActive &&
    !isImeConfirmation
  );
}
