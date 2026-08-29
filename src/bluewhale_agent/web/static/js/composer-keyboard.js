export function shouldSubmitComposer(event) {
  return event.key === "Enter" && !event.shiftKey && !event.isComposing;
}
