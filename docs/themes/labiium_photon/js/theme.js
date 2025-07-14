/**
 * LABIIUM Photon Theme - JavaScript
 * For PyTestLab Documentation
 */

document.addEventListener("DOMContentLoaded", () => {
  // --- Interactive Background Beams ---
  const backgroundBeams = document.getElementById("background-beams");
  if (backgroundBeams) {
    document.addEventListener("mousemove", (e) => {
      const { clientX, clientY } = e;
      const { innerWidth, innerHeight } = window;
      const xPercent = (clientX / innerWidth) * 100;
      const yPercent = (clientY / innerHeight) * 100;

      window.requestAnimationFrame(() => {
        backgroundBeams.style.background = `
                    radial-gradient(ellipse 80% 80% at ${xPercent - 10}% ${yPercent - 20}%, rgba(83, 51, 237, 0.15), transparent),
                    radial-gradient(ellipse 60% 80% at ${xPercent + 10}% ${yPercent + 20}%, rgba(4, 226, 220, 0.15), transparent)
                `;
      });
    });
  }

  // --- Navbar Scroll Effect ---
  const siteHeader = document.querySelector(".site-header");
  if (siteHeader) {
    let lastScrollY = window.scrollY;

    const handleScroll = () => {
      const currentScrollY = window.scrollY;

      if (currentScrollY > 50) {
        siteHeader.classList.add("scrolled");
      } else {
        siteHeader.classList.remove("scrolled");
      }

      lastScrollY = currentScrollY;
    };

    window.addEventListener("scroll", handleScroll, { passive: true });

    // Initial check
    handleScroll();
  }

  // --- Mobile Navigation Toggle ---
  const mobileNavToggle = document.querySelector(".mobile-nav-toggle");
  const navLinks = document.querySelector(".nav-links");

  if (mobileNavToggle && navLinks) {
    mobileNavToggle.addEventListener("click", () => {
      navLinks.classList.toggle("active");

      // Animate hamburger to X
      const lines = mobileNavToggle.querySelectorAll(".line");
      lines[0].style.transform = navLinks.classList.contains("active")
        ? "rotate(45deg) translate(5px, 5px)"
        : "";
      lines[1].style.opacity = navLinks.classList.contains("active")
        ? "0"
        : "1";
      lines[2].style.transform = navLinks.classList.contains("active")
        ? "rotate(-45deg) translate(5px, -5px)"
        : "";
    });
  }

  // --- Dropdown Navigation on Mobile ---
  const dropdowns = document.querySelectorAll(".dropdown");
  if (window.innerWidth < 768) {
    dropdowns.forEach((dropdown) => {
      const toggle = dropdown.querySelector(".dropdown-toggle");
      if (toggle) {
        toggle.addEventListener("click", (e) => {
          e.preventDefault();
          dropdown.classList.toggle("active");
        });
      }
    });
  }

  // --- Table of Contents Active State ---
  const tocLinks = document.querySelectorAll(".toc-item a");
  const headings = document.querySelectorAll(
    "h1[id], h2[id], h3[id], h4[id], h5[id], h6[id]",
  );

  if (tocLinks.length && headings.length) {
    const observerOptions = {
      rootMargin: "-80px 0px -40% 0px",
      threshold: 0,
    };

    const highlightTocLink = (id) => {
      tocLinks.forEach((link) => {
        link.classList.remove("active");
        const href = link.getAttribute("href");
        if (href && href.substring(href.indexOf("#") + 1) === id) {
          link.classList.add("active");
        }
      });
    };

    const headingObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting && entry.target.id) {
          highlightTocLink(entry.target.id);
        }
      });
    }, observerOptions);

    headings.forEach((heading) => headingObserver.observe(heading));
  }

  // --- Code Block Enhancement with Photonic Animation ---
  const codeBlocks = document.querySelectorAll("pre");
  codeBlocks.forEach((block) => {
    // Add enhanced copy button
    const copyButton = document.createElement("button");
    copyButton.className = "copy-button";
    copyButton.innerHTML = "Copy"; // We'll add the icon via CSS ::before
    copyButton.setAttribute("aria-label", "Copy code to clipboard");

    copyButton.addEventListener("click", () => {
      const code =
        block.querySelector("code")?.textContent || block.textContent;

      // Add a small ripple effect
      const ripple = document.createElement("span");
      ripple.className = "copy-ripple";
      copyButton.appendChild(ripple);

      // Animate the ripple
      setTimeout(() => {
        ripple.remove();
      }, 600);

      navigator.clipboard
        .writeText(code)
        .then(() => {
          // Success animation
          copyButton.classList.add("copied");
          copyButton.textContent = "Copied!";

          // Create and show success pulse
          const pulse = document.createElement("span");
          pulse.className = "success-pulse";
          block.appendChild(pulse);

          setTimeout(() => {
            pulse.remove();
          }, 1000);

          // Reset button after delay
          setTimeout(() => {
            copyButton.classList.remove("copied");
            copyButton.textContent = "Copy";
          }, 2000);
        })
        .catch((err) => {
          console.error("Failed to copy:", err);
          copyButton.classList.add("error");
          copyButton.textContent = "Error!";

          setTimeout(() => {
            copyButton.classList.remove("error");
            copyButton.textContent = "Copy";
          }, 2000);
        });
    });

    block.appendChild(copyButton);

    // Add language indicator with enhanced styling
    const language = block
      .querySelector("code")
      ?.className.match(/language-(\w+)/)?.[1];

    if (language) {
      const langBadge = document.createElement("div");
      langBadge.className = "lang-badge";

      // Format language name to be more readable
      let displayLang = language;
      // Map common language codes to nicer display names
      const langMap = {
        py: "Python",
        js: "JavaScript",
        ts: "TypeScript",
        html: "HTML",
        css: "CSS",
        yaml: "YAML",
        json: "JSON",
        bash: "Shell",
        sh: "Shell",
        sql: "SQL",
        cpp: "C++",
      };

      if (langMap[language]) {
        displayLang = langMap[language];
      } else {
        // Capitalize first letter for other languages
        displayLang = language.charAt(0).toUpperCase() + language.slice(1);
      }

      langBadge.textContent = displayLang;
      block.appendChild(langBadge);
    }
  });

  // --- Enhanced Code Block Processing (All Types) ---
  // Process all code blocks with modern glassmorphism design
  const processAllCodeBlocks = () => {
    // Enhanced code block processing for all pre elements
    document.querySelectorAll("pre:not(.enhanced)").forEach((block) => {
      enhanceCodeBlock(block);
      block.classList.add("enhanced");
    });

    // Process notebook cells and convert them to our enhanced structure
    document.querySelectorAll(".jp-Cell, .cell").forEach((cell) => {
      if (!cell.classList.contains("processed")) {
        enhanceNotebookCell(cell);
        cell.classList.add("processed");
      }
    });

    // Also handle legacy notebook structures
    document.querySelectorAll(".nb-input, .nb-output").forEach((container) => {
      if (!container.classList.contains("enhanced")) {
        enhanceNotebookContainer(container);
        container.classList.add("enhanced");
      }
    });

    // Handle direct pre blocks in notebooks
    document
      .querySelectorAll(".nb-input pre, .nb-output pre")
      .forEach((block) => {
        if (!block.closest(".nb-input-content, .nb-output-content")) {
          wrapNotebookBlock(block);
        }
      });

    // Apply syntax highlighting to all code blocks
    applySyntaxHighlighting();
  };

  const enhanceNotebookCell = (cell) => {
    const cellType =
      cell.classList.contains("jp-CodeCell") ||
      cell.classList.contains("code_cell")
        ? "code"
        : "markdown";

    if (cellType === "code") {
      const inputArea = cell.querySelector(".jp-InputArea, .input_area");
      const outputArea = cell.querySelector(".jp-OutputArea, .output_area");

      if (inputArea) {
        enhanceInputArea(inputArea);
      }
      if (outputArea) {
        enhanceOutputArea(outputArea);
      }
    }
  };

  const enhanceNotebookContainer = (container) => {
    const isInput = container.classList.contains("nb-input");
    const pre = container.querySelector("pre");

    if (pre) {
      // Create enhanced structure
      const prompt = document.createElement("div");
      prompt.className = isInput ? "nb-input-prompt" : "nb-output-prompt";
      prompt.textContent = isInput ? "In [●]:" : "Out[●]:";

      const content = document.createElement("div");
      content.className = isInput ? "nb-input-content" : "nb-output-content";

      // Move pre to content div
      content.appendChild(pre);

      // Clear container and add new structure
      container.innerHTML = "";
      container.appendChild(prompt);
      container.appendChild(content);

      // Add interactive features
      addNotebookInteractivity(content, isInput);
    }
  };

  const enhanceInputArea = (inputArea) => {
    const container = document.createElement("div");
    container.className = "nb-input";

    const prompt = document.createElement("div");
    prompt.className = "nb-input-prompt";
    prompt.innerHTML = 'In [<span class="execution-count">●</span>]:';

    const content = document.createElement("div");
    content.className = "nb-input-content";

    // Move existing content
    while (inputArea.firstChild) {
      content.appendChild(inputArea.firstChild);
    }

    container.appendChild(prompt);
    container.appendChild(content);
    inputArea.parentNode.replaceChild(container, inputArea);

    addNotebookInteractivity(content, true);
  };

  const enhanceOutputArea = (outputArea) => {
    const outputs = outputArea.querySelectorAll(
      ".jp-OutputArea-output, .output",
    );

    outputs.forEach((output, index) => {
      const container = document.createElement("div");
      container.className = "nb-output";

      const prompt = document.createElement("div");
      prompt.className = "nb-output-prompt";
      prompt.innerHTML = 'Out[<span class="execution-count">●</span>]:';

      const content = document.createElement("div");
      content.className = "nb-output-content";

      // Move output content
      while (output.firstChild) {
        content.appendChild(output.firstChild);
      }

      container.appendChild(prompt);
      container.appendChild(content);
      output.parentNode.replaceChild(container, output);

      addNotebookInteractivity(content, false);
    });
  };

  const wrapNotebookBlock = (block) => {
    const isInput = block.closest(".nb-input");
    const content = document.createElement("div");
    content.className = isInput ? "nb-input-content" : "nb-output-content";

    block.parentNode.insertBefore(content, block);
    content.appendChild(block);

    addNotebookInteractivity(content, isInput);
  };

  const addNotebookInteractivity = (contentDiv, isInput) => {
    const pre = contentDiv.querySelector("pre");
    if (!pre) return;

    // Add copy button with enhanced styling
    const copyButton = document.createElement("button");
    copyButton.className = "copy-button";
    copyButton.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
        <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"></path>
      </svg>
      Copy
    `;
    copyButton.setAttribute("aria-label", "Copy code to clipboard");

    copyButton.addEventListener("click", async () => {
      const code = pre.querySelector("code")?.textContent || pre.textContent;

      try {
        await navigator.clipboard.writeText(code);

        // Success animation
        copyButton.classList.add("copied");
        copyButton.innerHTML = `
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="20,6 9,17 4,12"></polyline>
          </svg>
          Copied!
        `;

        // Add success pulse
        const pulse = document.createElement("div");
        pulse.className = "success-pulse";
        contentDiv.appendChild(pulse);

        setTimeout(() => pulse.remove(), 1000);

        // Reset button
        setTimeout(() => {
          copyButton.classList.remove("copied");
          copyButton.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
              <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"></path>
            </svg>
            Copy
          `;
        }, 2000);
      } catch (err) {
        console.error("Failed to copy:", err);
        copyButton.textContent = "Error!";
        setTimeout(() => {
          copyButton.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
              <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012-2h9a2 2 0 012 2v1"></path>
            </svg>
            Copy
          `;
        }, 2000);
      }
    });

    contentDiv.appendChild(copyButton);

    // Add language badge
    const langBadge = document.createElement("div");
    langBadge.className = "lang-badge";

    let language = "Text";
    if (isInput) {
      language = "Python";
    } else {
      // Try to detect from code element
      const codeEl = pre.querySelector('code[class*="language-"]');
      if (codeEl) {
        const match = codeEl.className.match(/language-(\w+)/);
        if (match) {
          language = match[1];
        }
      }

      // Check for error outputs
      if (
        contentDiv.closest(".nb-error") ||
        pre.textContent.includes("Traceback")
      ) {
        language = "Error";
      }
    }

    // Format language display
    const langMap = {
      py: "Python",
      python: "Python",
      js: "JavaScript",
      javascript: "JavaScript",
      ts: "TypeScript",
      html: "HTML",
      css: "CSS",
      yaml: "YAML",
      json: "JSON",
      bash: "Shell",
      sh: "Shell",
      sql: "SQL",
      cpp: "C++",
      r: "R",
      error: "Error",
    };

    const displayLang =
      langMap[language.toLowerCase()] ||
      language.charAt(0).toUpperCase() + language.slice(1);

    langBadge.textContent = displayLang;
    contentDiv.appendChild(langBadge);
  };

  const enhanceCodeBlock = (pre) => {
    if (!pre || pre.hasAttribute("data-enhanced")) return;

    // Add copy button
    const copyButton = document.createElement("button");
    copyButton.className = "copy-button";
    copyButton.innerHTML = "Copy";
    copyButton.setAttribute("aria-label", "Copy code to clipboard");

    copyButton.addEventListener("click", () => {
      const code = pre.querySelector("code")?.textContent || pre.textContent;

      navigator.clipboard
        .writeText(code)
        .then(() => {
          copyButton.classList.add("copied");
          copyButton.textContent = "Copied!";

          setTimeout(() => {
            copyButton.classList.remove("copied");
            copyButton.textContent = "Copy";
          }, 2000);
        })
        .catch((err) => {
          console.error("Failed to copy:", err);
          copyButton.textContent = "Error!";
          setTimeout(() => {
            copyButton.textContent = "Copy";
          }, 2000);
        });
    });

    pre.appendChild(copyButton);

    // Add language badge
    const code = pre.querySelector("code");
    if (code) {
      let language = detectLanguage(code, pre);

      const langBadge = document.createElement("div");
      langBadge.className = "lang-badge";
      langBadge.textContent = formatLanguageName(language);
      pre.appendChild(langBadge);
    }

    pre.setAttribute("data-enhanced", "true");
  };

  const detectLanguage = (codeEl, pre) => {
    // Check existing language classes
    const existingLang = codeEl.className.match(/language-(\w+)/);
    if (existingLang) return existingLang[1];

    // Check parent div classes
    const parentDiv = codeEl.closest(
      'div[class*="highlight"], div[class*="codehilite"]',
    );
    if (parentDiv) {
      const classMatch = parentDiv.className.match(
        /highlight-(\w+)|language-(\w+)|codehilite-(\w+)/,
      );
      if (classMatch) return classMatch[1] || classMatch[2] || classMatch[3];
    }

    const content = codeEl.textContent;

    // YAML detection (enhanced)
    if (
      content.includes(":") &&
      (content.includes("command:") ||
        content.includes("parameters:") ||
        content.includes("settings:") ||
        content.match(/^\s*\w+:\s*$/m) ||
        content.match(/^\s*-\s+\w+:/m))
    ) {
      return "yaml";
    }

    // Python detection
    if (
      content.includes("def ") ||
      content.includes("import ") ||
      content.includes("from ") ||
      content.includes("print(") ||
      content.includes("class ") ||
      codeEl.closest(".nb-input, .jp-InputArea")
    ) {
      return "python";
    }

    // JSON detection
    if (
      (content.trim().startsWith("{") && content.trim().endsWith("}")) ||
      (content.trim().startsWith("[") && content.trim().endsWith("]"))
    ) {
      return "json";
    }

    // Shell/Bash detection
    if (
      content.includes("$ ") ||
      content.includes("#!/bin/bash") ||
      content.includes("cd ") ||
      content.includes("pip install")
    ) {
      return "bash";
    }

    // Default fallback
    if (codeEl.closest(".nb-input, .jp-InputArea")) return "python";
    return "text";
  };

  const formatLanguageName = (language) => {
    const langMap = {
      py: "Python",
      python: "Python",
      js: "JavaScript",
      javascript: "JavaScript",
      ts: "TypeScript",
      yaml: "YAML",
      yml: "YAML",
      json: "JSON",
      bash: "Shell",
      sh: "Shell",
      html: "HTML",
      css: "CSS",
      sql: "SQL",
      cpp: "C++",
      text: "Text",
    };
    return (
      langMap[language] || language.charAt(0).toUpperCase() + language.slice(1)
    );
  };

  const applySyntaxHighlighting = () => {
    // Wait for DOM to be ready and Prism to be loaded
    if (!window.Prism || !document.body) {
      setTimeout(applySyntaxHighlighting, 100);
      return;
    }

    // Target all code elements that haven't been highlighted
    const codeElements = document.querySelectorAll(
      "pre code:not([data-highlighted])",
    );

    codeElements.forEach((codeEl) => {
      const pre = codeEl.closest("pre");
      if (!pre) return;

      // Detect and apply language
      const language = detectLanguage(codeEl, pre);

      // Add language classes if not already present
      if (!codeEl.className.includes("language-")) {
        codeEl.classList.add(`language-${language}`);
        pre.classList.add(`language-${language}`);
      }

      // Mark as processed
      codeEl.setAttribute("data-highlighted", "true");

      // Apply Prism highlighting
      try {
        if (window.Prism && window.Prism.highlightElement) {
          window.Prism.highlightElement(codeEl);
        }
      } catch (e) {
        console.warn("Prism highlighting failed for", language, ":", e);
      }
    });
  };

  // Process all code blocks on load and when new content is added
  processAllCodeBlocks();

  // Use MutationObserver to handle dynamically loaded notebook content
  const notebookObserver = new MutationObserver((mutations) => {
    let shouldProcess = false;
    mutations.forEach((mutation) => {
      if (mutation.type === "childList" && mutation.addedNodes.length > 0) {
        mutation.addedNodes.forEach((node) => {
          if (
            node.nodeType === 1 &&
            (node.classList?.contains("jp-Cell") ||
              node.classList?.contains("cell") ||
              node.classList?.contains("nb-input") ||
              node.classList?.contains("nb-output") ||
              node.querySelector?.(".jp-Cell, .cell, .nb-input, .nb-output"))
          ) {
            shouldProcess = true;
          }
        });
      }
    });

    if (shouldProcess) {
      setTimeout(processAllCodeBlocks, 100);
    }
  });

  notebookObserver.observe(document.body, {
    childList: true,
    subtree: true,
  });

  // Enhanced Prism loading and application
  const initializeSyntaxHighlighting = () => {
    // Apply highlighting immediately if Prism is loaded
    if (window.Prism) {
      applySyntaxHighlighting();
    }

    // Also apply after delays to catch dynamically loaded content
    setTimeout(applySyntaxHighlighting, 300);
    setTimeout(applySyntaxHighlighting, 1000);
    setTimeout(applySyntaxHighlighting, 2000);
  };

  // Initialize when DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeSyntaxHighlighting);
  } else {
    initializeSyntaxHighlighting();
  }

  // Re-apply when Prism loads (if it loads after this script)
  window.addEventListener("load", () => {
    setTimeout(applySyntaxHighlighting, 200);
    setTimeout(processAllCodeBlocks, 300);
  });

  // Force reprocessing on page visibility change (helps with dynamic content)
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      setTimeout(processAllCodeBlocks, 100);
    }
  });

  // --- Glass card hover effects ---
  const glassCards = document.querySelectorAll(".glass-card");
  glassCards.forEach((card) => {
    card.addEventListener("mouseenter", () => {
      card.style.transform = "translateY(-4px)";
      card.style.boxShadow = "0 16px 32px rgba(0, 0, 0, 0.2)";
    });

    card.addEventListener("mouseleave", () => {
      card.style.transform = "";
      card.style.boxShadow = "";
    });
  });

  // --- Fade-in animations on scroll ---
  const fadeInElements = document.querySelectorAll(".fade-in");
  if (fadeInElements.length) {
    const fadeInObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("visible");
            fadeInObserver.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.1 },
    );

    fadeInElements.forEach((element) => fadeInObserver.observe(element));
  }

  // --- Handle external links ---
  const links = document.querySelectorAll("a");
  links.forEach((link) => {
    const url = link.getAttribute("href");
    if (
      url &&
      url.startsWith("http") &&
      !url.includes(window.location.hostname)
    ) {
      link.setAttribute("target", "_blank");
      link.setAttribute("rel", "noopener noreferrer");

      // Add external link icon if not already present
      if (!link.querySelector(".external-icon")) {
        const icon = document.createElement("span");
        icon.className = "external-icon";
        icon.innerHTML = " ↗";
        icon.style.fontSize = "0.8em";
        link.appendChild(icon);
      }
    }
  });

  // --- Keyboard navigation ---
  document.addEventListener("keydown", (e) => {
    // Next/Prev page with arrow keys when combined with Alt
    if (e.altKey) {
      if (e.key === "ArrowRight") {
        const nextLink = document.querySelector(".next-link");
        if (nextLink) window.location.href = nextLink.getAttribute("href");
      } else if (e.key === "ArrowLeft") {
        const prevLink = document.querySelector(".prev-link");
        if (prevLink) window.location.href = prevLink.getAttribute("href");
      }
    }

    // Focus search with '/' key
    if (e.key === "/" && !e.ctrlKey && !e.metaKey) {
      const searchInput = document.querySelector(".search-input");
      if (searchInput) {
        e.preventDefault();
        searchInput.focus();
      }
    }
  });

  // --- Enhanced Dynamic Styling for Modern UI ---
  const dynamicStyles = document.createElement("style");
  dynamicStyles.textContent = `
        /* Enhanced Scrollbar Styling */
        ::-webkit-scrollbar {
            width: 12px;
            height: 12px;
        }
        ::-webkit-scrollbar-track {
            background: rgba(30, 33, 38, 0.3);
            border-radius: 10px;
        }
        ::-webkit-scrollbar-thumb {
            background: var(--graphite-70, #42454A);
            border-radius: 10px;
            border: 3px solid rgba(30, 33, 38, 0.3);
            transition: all 0.3s ease;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: var(--lab-violet, #5333ed);
            border-color: rgba(83, 51, 237, 0.2);
        }

        /* Enhanced Copy and Success Animations */
        .success-pulse {
            position: absolute;
            top: -2px;
            left: -2px;
            right: -2px;
            bottom: -2px;
            border-radius: var(--border-radius-md, 8px);
            border: 2px solid var(--status-success, #00b27c);
            opacity: 0.8;
            animation: success-pulse 1s cubic-bezier(0.16, 1, 0.3, 1);
            pointer-events: none;
            z-index: 100;
        }

        @keyframes success-pulse {
            0% {
                transform: scale(1);
                opacity: 0.8;
            }
            50% {
                transform: scale(1.02);
                opacity: 0.6;
            }
            100% {
                transform: scale(1.05);
                opacity: 0;
            }
        }

        /* Enhanced Prism.js Integration for Notebooks */
        .nb-input-content .token.comment,
        .nb-output-content .token.comment,
        .jp-InputArea .token.comment,
        .jp-OutputArea .token.comment {
            color: #6b7280 !important;
            font-style: italic;
        }

        .nb-input-content .token.keyword,
        .nb-output-content .token.keyword,
        .jp-InputArea .token.keyword,
        .jp-OutputArea .token.keyword {
            color: var(--lab-violet, #5333ed) !important;
            font-weight: 600;
        }

        .nb-input-content .token.string,
        .nb-output-content .token.string,
        .jp-InputArea .token.string,
        .jp-OutputArea .token.string {
            color: var(--lab-aqua, #04e2dc) !important;
        }

        .nb-input-content .token.number,
        .nb-output-content .token.number,
        .jp-InputArea .token.number,
        .jp-OutputArea .token.number {
            color: #f59e0b !important;
        }

        .nb-input-content .token.function,
        .nb-output-content .token.function,
        .jp-InputArea .token.function,
        .jp-OutputArea .token.function {
            color: #8b5cf6 !important;
        }

        .nb-input-content .token.operator,
        .nb-output-content .token.operator,
        .jp-InputArea .token.operator,
        .jp-OutputArea .token.operator {
            color: #ef4444 !important;
        }

        .nb-input-content .token.builtin,
        .nb-output-content .token.builtin,
        .jp-InputArea .token.builtin,
        .jp-OutputArea .token.builtin {
            color: #10b981 !important;
        }

        /* YAML-specific syntax highlighting */
        .language-yaml .token.key {
            color: var(--lab-violet, #5333ed) !important;
            font-weight: 600;
        }

        .language-yaml .token.punctuation {
            color: var(--photon-white, #f5f7fa) !important;
        }

        .language-yaml .token.string {
            color: var(--lab-aqua, #04e2dc) !important;
        }

        .language-yaml .token.scalar {
            color: #f59e0b !important;
        }

        /* Responsive Design Enhancements */
        @media (max-width: 768px) {
            .nb-input, .nb-output {
                flex-direction: column;
            }

            .nb-input-prompt, .nb-output-prompt {
                min-width: auto;
                text-align: left;
                border-right: none;
                border-bottom: 2px solid;
                padding: 0.5rem 1rem;
            }

            .nb-input-content .copy-button,
            .nb-output-content .copy-button {
                top: 0.5rem;
                right: 0.5rem;
                font-size: 0.7rem;
                padding: 0.3rem 0.5rem;
            }

            .nb-input-content .lang-badge,
            .nb-output-content .lang-badge {
                bottom: 0.5rem;
                right: 0.5rem;
                font-size: 0.65rem;
            }
        }

        /* Dark mode enhancements */
        @media (prefers-color-scheme: dark) {
            .nb-output img {
                filter: brightness(0.9) contrast(1.1);
            }
        }

        /* Print styles for notebooks */
        @media print {
            .nb-input, .nb-output {
                break-inside: avoid;
                background: white !important;
                border: 1px solid #ccc !important;
                box-shadow: none !important;
                backdrop-filter: none !important;
            }

            .nb-input-content .copy-button,
            .nb-output-content .copy-button,
            .nb-input-content .lang-badge,
            .nb-output-content .lang-badge {
                display: none !important;
            }

            .nb-input-prompt, .nb-output-prompt {
                background: #f3f4f6 !important;
                color: #374151 !important;
                border-color: #d1d5db !important;
            }
        }

        /* Accessibility enhancements */
        @media (prefers-reduced-motion: reduce) {
            .nb-input, .nb-output {
                transition: none !important;
            }

            .nb-input-content .copy-button,
            .nb-output-content .copy-button {
                transition: none !important;
            }

            .success-pulse {
                animation: none !important;
                opacity: 0 !important;
            }
        }

        /* High contrast mode support */
        @media (prefers-contrast: high) {
            .nb-input, .nb-output {
                border-width: 2px !important;
                border-color: currentColor !important;
            }

            .nb-input-prompt, .nb-output-prompt {
                border-width: 3px !important;
            }
        }
    `;
  document.head.appendChild(dynamicStyles);
  // --- 404 Page Enhancements ---
  const is404Page = document.body.classList.contains("error-page-body");

  if (is404Page) {
    // Enhanced background effect for 404 page
    const enhancedBeamEffect = () => {
      if (!backgroundBeams) return;

      // Create more dynamic beam animation
      let progress = 0;
      const animateBeams = () => {
        progress += 0.005;
        const x = Math.sin(progress) * 30 + 50;
        const y = Math.cos(progress * 0.8) * 30 + 50;

        backgroundBeams.style.background = `
                    radial-gradient(ellipse 80% 80% at ${x}% ${y - 10}%, rgba(83, 51, 237, 0.2), transparent),
                    radial-gradient(ellipse 60% 60% at ${100 - x}% ${100 - y}%, rgba(4, 226, 220, 0.15), transparent)
                `;

        requestAnimationFrame(animateBeams);
      };

      animateBeams();
    };

    // Interactive particles on mouse move
    const errorIllustration = document.querySelector(".error-illustration");
    if (errorIllustration) {
      const particles = errorIllustration.querySelectorAll(".particle");

      document.addEventListener("mousemove", (e) => {
        const { clientX, clientY } = e;
        const rect = errorIllustration.getBoundingClientRect();

        // Calculate mouse position relative to the illustration
        const x = (clientX - rect.left) / rect.width;
        const y = (clientY - rect.top) / rect.height;

        // Move particles slightly based on mouse position
        particles.forEach((particle, i) => {
          const offsetX = (x - 0.5) * 20 * (i % 2 ? 1 : -1);
          const offsetY = (y - 0.5) * 20 * (i % 2 ? -1 : 1);

          particle.style.transform = `translate(${offsetX}px, ${offsetY}px)`;
          particle.style.boxShadow = `0 0 ${10 + Math.abs(offsetX + offsetY) / 2}px var(--lab-aqua)`;
        });

        // Affect wave animation speed based on cursor position
        const waves = errorIllustration.querySelectorAll(".wave");
        waves.forEach((wave, i) => {
          const speedFactor = 1 + (y - 0.5) * 0.5;
          wave.style.animationDuration = `${6 + i * 2 * speedFactor}s`;
        });
      });

      // Add click effect - create burst particles
      errorIllustration.addEventListener("click", (e) => {
        const rect = errorIllustration.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;

        // Create burst effect
        for (let i = 0; i < 8; i++) {
          const burstParticle = document.createElement("div");
          burstParticle.className = "burst-particle";
          burstParticle.style.left = `${x}px`;
          burstParticle.style.top = `${y}px`;

          // Random direction
          const angle = Math.random() * Math.PI * 2;
          const distance = 30 + Math.random() * 40;
          const duration = 0.6 + Math.random() * 0.8;

          // Set styles for the burst particle
          burstParticle.style.background =
            i % 2 ? "var(--lab-aqua)" : "var(--lab-violet)";
          burstParticle.style.animation = `burst ${duration}s forwards cubic-bezier(0.1, 0.8, 0.3, 1)`;

          // Set the transform with the random angle
          burstParticle.style.setProperty("--angle", `${angle}rad`);
          burstParticle.style.setProperty("--distance", `${distance}px`);

          errorIllustration.appendChild(burstParticle);

          // Remove particle after animation
          setTimeout(() => {
            errorIllustration.removeChild(burstParticle);
          }, duration * 1000);
        }
      });

      // Add CSS for burst particles
      const burstStyle = document.createElement("style");
      burstStyle.textContent = `
                .burst-particle {
                    position: absolute;
                    width: 6px;
                    height: 6px;
                    border-radius: 50%;
                    pointer-events: none;
                    opacity: 0.8;
                    z-index: 10;
                }

                @keyframes burst {
                    0% {
                        transform: translate(0, 0) scale(1);
                        opacity: 1;
                    }
                    100% {
                        transform:
                            translate(
                                calc(cos(var(--angle)) * var(--distance)),
                                calc(sin(var(--angle)) * var(--distance))
                            )
                            scale(0);
                        opacity: 0;
                    }
                }
            `;
      document.head.appendChild(burstStyle);
    }

    // Initialize enhanced background effect
    enhancedBeamEffect();
  }
});
