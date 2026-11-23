/* BashLexer leaves executable names and CLI options as plain text. Preserve
   its strings, comments, substitutions, whitespace and per-line anchors. */
for (const code of document.querySelectorAll(".article :is(.language-bash, .language-sh, .language-shell).highlight pre > code")) {
  let continued = false;
  for (const line of code.querySelectorAll(":scope > span[id]")) {
    const command = continued ? null : /^\s*([\w./-]+)(?=\s|$)/.exec(line.textContent)?.[1];
    continued = /\\\s*$/.test(line.textContent);
    let wordIndex = 0;
    for (const node of [...line.childNodes]) {
      if (!node.textContent.trim()) continue;
      const word = node.textContent.trim();
      let kind;
      if (wordIndex === 0 && word === command) kind = "command";
      else if (/^--?[a-zA-Z]/.test(word)) kind = "option";
      else if (wordIndex === 1 && ["pip", "pip3", "ptl", "uv", "git"].includes(command) && /^[a-z][\w-]*$/.test(word)) kind = "subcommand";
      wordIndex++;
      if (!kind || node.nodeType !== Node.TEXT_NODE) continue;
      const token = document.createElement("span");
      token.className = "shell-" + kind;
      node.replaceWith(token);
      token.append(node);
    }
  }
}

// Jupyter exports !pip as a Python error followed by name tokens.
for (const escape of document.querySelectorAll(".highlight-ipynb pre .err")) {
  const command = escape.nextElementSibling;
  if (escape.textContent !== "!" || !command?.matches(".n") || escape.nextSibling !== command) continue;
  command.classList.add("shell-command");
  const action = command.nextElementSibling;
  if (["pip", "pip3", "uv"].includes(command.textContent) && action?.matches(".n")) action.classList.add("shell-subcommand");
}
