async function copyDocsText(text) {
  try {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Some browsers restrict the clipboard API in embedded previews.
  }
  const previousFocus = document.activeElement;
  const field = document.createElement("textarea");
  field.style.position = "fixed";
  field.style.opacity = "0";
  field.value = text;
  document.body.append(field);
  field.select();
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    field.remove();
    previousFocus?.focus({ preventScroll: true });
  }
}
