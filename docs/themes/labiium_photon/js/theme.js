/** PyTestLab documentation interactions. */
document.addEventListener("DOMContentLoaded", () => {
  const body = document.body;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const header = document.querySelector(".site-header");
  const frame = document.querySelector(".docs-frame");
  const menuToggle = document.querySelector(".menu-toggle");
  const primaryNav = document.querySelector(".nav-primary");
  const docsToggle = document.querySelector(".docs-nav-toggle");
  const sidebarBackdrop = document.querySelector(".sidebar-backdrop");

  const setPrimaryNav = (open) => {
    primaryNav?.classList.toggle("open", open);
    menuToggle?.setAttribute("aria-expanded", String(open));
  };

  const setDocsNav = (open) => {
    body.classList.toggle("docs-nav-open", open);
    docsToggle?.setAttribute("aria-expanded", String(open));
  };

  menuToggle?.addEventListener("click", () => setPrimaryNav(!primaryNav?.classList.contains("open")));
  docsToggle?.addEventListener("click", () => setDocsNav(!body.classList.contains("docs-nav-open")));
  sidebarBackdrop?.addEventListener("click", () => setDocsNav(false));
  window.addEventListener("resize", () => {
    if (window.innerWidth > 900) {
      setDocsNav(false);
      setPrimaryNav(false);
    }
  });
  window.addEventListener("scroll", () => header?.classList.toggle("scrolled", window.scrollY > 8), { passive: true });

  if (!reducedMotion) {
    const beams = document.getElementById("background-beams");
    document.addEventListener("pointermove", (event) => {
      const x = Math.round((event.clientX / window.innerWidth) * 100);
      const y = Math.round((event.clientY / window.innerHeight) * 100);
      window.requestAnimationFrame(() => beams?.style.setProperty("--beam-position", `${x}% ${y}%`));
    });
  }

  const modal = document.querySelector(".search-modal");
  const searchTrigger = document.querySelector(".search-trigger");
  const searchClose = document.querySelector(".search-close");
  const searchInput = document.querySelector(".search-input");
  const searchStatus = document.querySelector(".search-status");
  const searchResults = document.querySelector(".search-results");
  let searchDocuments = [];
  let selectedResult = -1;
  let returnFocus = null;
  let debounceTimer = 0;

  const setPageInert = (inert) => {
    [header, frame].forEach((element) => {
      if (element) element.inert = inert;
    });
  };

  const updateSelectedResult = (nextIndex) => {
    const results = [...(searchResults?.querySelectorAll(".search-result") || [])];
    if (!results.length) {
      selectedResult = -1;
      searchInput?.removeAttribute("aria-activedescendant");
      return;
    }
    selectedResult = (nextIndex + results.length) % results.length;
    results.forEach((result, index) => {
      const selected = index === selectedResult;
      result.classList.toggle("selected", selected);
      result.setAttribute("aria-selected", String(selected));
      if (selected) {
        searchInput?.setAttribute("aria-activedescendant", result.id);
        result.scrollIntoView({ block: "nearest" });
      }
    });
  };

  const openSearch = async () => {
    if (!modal) return;
    returnFocus = document.activeElement;
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    searchInput?.setAttribute("aria-expanded", "true");
    body.classList.add("modal-open");
    setPageInert(true);
    window.setTimeout(() => searchInput?.focus(), 30);
    if (searchDocuments.length || !modal.dataset.searchIndex) return;
    if (searchStatus) searchStatus.textContent = "Loading search index…";
    try {
      const response = await fetch(modal.dataset.searchIndex);
      if (!response.ok) throw new Error(`Search index returned ${response.status}`);
      const index = await response.json();
      searchDocuments = index.docs || [];
      if (searchStatus) searchStatus.textContent = "Type to start searching";
    } catch (_) {
      if (searchStatus) searchStatus.textContent = "Search is temporarily unavailable.";
    }
  };

  const closeSearch = () => {
    if (!modal?.classList.contains("open")) return;
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
    searchInput?.setAttribute("aria-expanded", "false");
    searchInput?.removeAttribute("aria-activedescendant");
    body.classList.remove("modal-open");
    setPageInert(false);
    if (searchInput) searchInput.value = "";
    searchResults?.replaceChildren();
    if (searchStatus) searchStatus.textContent = "Type to start searching";
    selectedResult = -1;
    if (returnFocus instanceof HTMLElement) returnFocus.focus();
  };

  const excerptFor = (text, terms) => {
    const normalized = text.replace(/\s+/g, " ").trim();
    const firstMatch = terms.map((term) => normalized.toLowerCase().indexOf(term)).filter((index) => index >= 0).sort((a, b) => a - b)[0] || 0;
    const start = Math.max(0, firstMatch - 55);
    const excerpt = normalized.slice(start, start + 190);
    return `${start > 0 ? "…" : ""}${excerpt}${start + 190 < normalized.length ? "…" : ""}`;
  };

  const appendHighlighted = (element, text, terms) => {
    const escaped = terms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).filter(Boolean);
    if (!escaped.length) {
      element.textContent = text;
      return;
    }
    const pattern = new RegExp(`(${escaped.join("|")})`, "gi");
    text.split(pattern).forEach((part) => {
      if (escaped.some((term) => term.toLowerCase() === part.toLowerCase())) {
        const mark = document.createElement("mark");
        mark.textContent = part;
        element.append(mark);
      } else {
        element.append(document.createTextNode(part));
      }
    });
  };

  const renderResults = (query) => {
    if (!searchResults || !searchStatus) return;
    searchResults.replaceChildren();
    selectedResult = -1;
    if (query.length < 2) {
      searchStatus.textContent = "Type at least two characters";
      return;
    }
    const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
    const results = searchDocuments
      .map((document) => {
        const title = (document.title || "").toLowerCase();
        const text = (document.text || "").toLowerCase();
        const location = (document.location || "").toLowerCase();
        const score = terms.reduce((total, term) => total + (title.includes(term) ? 12 : 0) + (location.includes(term) ? 4 : 0) + (text.includes(term) ? 1 : 0), 0);
        const completeMatch = terms.every((term) => title.includes(term) || text.includes(term) || location.includes(term));
        return { document, score: completeMatch ? score + 6 : score };
      })
      .filter((result) => result.score > 0)
      .sort((a, b) => b.score - a.score || (a.document.title || "").localeCompare(b.document.title || ""))
      .slice(0, 12);

    searchStatus.textContent = results.length ? `${results.length} result${results.length === 1 ? "" : "s"}` : "No results found";
    results.forEach(({ document: result }, index) => {
      const link = document.createElement("a");
      link.className = "search-result";
      link.id = `search-result-${index}`;
      link.setAttribute("role", "option");
      link.setAttribute("aria-selected", "false");
      const siteRoot = document.querySelector(".site-logo")?.href || window.location.origin;
      link.href = new URL(result.location || "", siteRoot).href;
      const context = document.createElement("small");
      const readableLocation = decodeURIComponent((result.location || "").replace(/\/$/, "").replace(/[-_/#+]+/g, " ").trim());
      context.textContent = readableLocation || "Documentation";
      const title = document.createElement("strong");
      appendHighlighted(title, result.title || "Untitled", terms);
      const excerpt = document.createElement("span");
      appendHighlighted(excerpt, excerptFor(result.text || "", terms), terms);
      link.append(context, title, excerpt);
      link.addEventListener("pointermove", () => updateSelectedResult(index));
      searchResults.append(link);
    });
  };

  searchTrigger?.addEventListener("click", openSearch);
  searchClose?.addEventListener("click", closeSearch);
  modal?.addEventListener("click", (event) => { if (event.target === modal) closeSearch(); });
  searchInput?.addEventListener("input", (event) => {
    window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(() => renderResults(event.target.value.trim()), 120);
  });
  searchInput?.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      updateSelectedResult(selectedResult + 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      updateSelectedResult(selectedResult - 1);
    } else if (event.key === "Enter" && selectedResult >= 0) {
      event.preventDefault();
      searchResults?.querySelectorAll(".search-result")[selectedResult]?.click();
    }
  });

  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      openSearch();
    }
    if (event.key === "Escape") {
      closeSearch();
      setDocsNav(false);
      setPrimaryNav(false);
    }
    if (event.key === "Tab" && modal?.classList.contains("open")) {
      const focusable = [...modal.querySelectorAll('button:not([disabled]), input:not([disabled]), a[href]')];
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });

  document.querySelector(".copy-page")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const label = button.querySelector("span");
    try {
      await navigator.clipboard.writeText(`${document.title}\n${window.location.href}`);
      if (label) label.textContent = "Link copied";
      window.setTimeout(() => { if (label) label.textContent = "Copy link"; }, 1600);
    } catch (_) {
      if (label) label.textContent = "Copy failed";
    }
  });
  document.querySelector("[data-history-back]")?.addEventListener("click", () => window.history.back());

  const article = document.querySelector(".article");
  const pageTools = document.querySelector(".page-tools");
  const firstTitle = article?.querySelector(":scope > h1:first-child");
  const introduction = firstTitle?.nextElementSibling?.matches("p") ? firstTitle.nextElementSibling : firstTitle;
  if (article && pageTools && introduction) introduction.insertAdjacentElement("afterend", pageTools);

  document.querySelectorAll(".article pre").forEach((block) => {
    if (block.querySelector(".copy-code")) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "copy-code";
    button.textContent = "Copy";
    button.addEventListener("click", async () => {
      await navigator.clipboard.writeText(block.querySelector("code")?.textContent || block.textContent || "");
      button.textContent = "Copied";
      window.setTimeout(() => { button.textContent = "Copy"; }, 1600);
    });
    block.append(button);
  });

  const outlineLinks = [...document.querySelectorAll(".page-outline a")];
  const headings = [...document.querySelectorAll(".article h1[id], .article h2[id], .article h3[id], .article .doc-heading[id]")];
  if (outlineLinks.length && headings.length) {
    const activate = (id) => {
      const exactIndex = outlineLinks.findIndex((link) => decodeURIComponent(link.hash.slice(1)) === id);
      let target = exactIndex >= 0 ? outlineLinks[exactIndex] : null;
      if (!target?.offsetParent) {
        for (let index = exactIndex; index >= 0; index -= 1) {
          if (outlineLinks[index]?.offsetParent) {
            target = outlineLinks[index];
            break;
          }
        }
      }
      outlineLinks.forEach((link) => link.classList.toggle("active", link === target));
    };
    const observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (visible?.target.id) activate(visible.target.id);
    }, { rootMargin: "-12% 0px -76% 0px" });
    headings.forEach((heading) => observer.observe(heading));
  }
});
