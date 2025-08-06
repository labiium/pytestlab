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
    mobileNavToggle.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();

      mobileNavToggle.classList.toggle("active");
      navLinks.classList.toggle("active");

      // Update aria attributes
      const expanded = navLinks.classList.contains("active");
      mobileNavToggle.setAttribute("aria-expanded", expanded);
    });

    // Close mobile nav when clicking outside
    document.addEventListener("click", (e) => {
      if (!navLinks.contains(e.target) && !mobileNavToggle.contains(e.target)) {
        mobileNavToggle.classList.remove("active");
        navLinks.classList.remove("active");
        mobileNavToggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  // --- Enhanced Table of Contents ---
  const tocLinks = document.querySelectorAll(".toc a");
  const headings = document.querySelectorAll("h1, h2, h3, h4, h5, h6");

  if (tocLinks.length && headings.length) {
    const observerOptions = {
      root: null,
      rootMargin: "-10% 0px -85% 0px",
      threshold: [0, 0.25, 0.5, 0.75, 1],
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

  // --- Code Block Enhancement (User Guide Only) ---
  // Only target code blocks in user guide pages, completely avoid notebook pages
  console.log(
    "Checking for jupyter-wrapper:",
    document.querySelector(".jupyter-wrapper"),
  );
  if (!document.querySelector(".jupyter-wrapper")) {
    const codeBlocks = document.querySelectorAll(
      "pre.highlight, pre[class*='language-'], .codehilite pre",
    );
    console.log("Found code blocks:", codeBlocks.length);
    codeBlocks.forEach((block) => {
      console.log("Processing block:", block);
      // Skip if already has a copy button (avoid duplicates)
      if (block.querySelector(".copy-button")) return;

      // Add simple copy button
      const copyButton = document.createElement("button");
      copyButton.className = "copy-button";
      copyButton.textContent = "Copy";
      copyButton.setAttribute("aria-label", "Copy code to clipboard");
      copyButton.style.cssText = `
        position: absolute;
        top: 0.75rem;
        right: 0.75rem;
        background: #5333ed;
        color: white;
        border: none;
        border-radius: 4px;
        padding: 0.4rem 0.8rem;
        font-size: 0.75rem;
        cursor: pointer;
        opacity: 0;
        transition: opacity 0.3s;
        z-index: 10;
      `;

      // Make sure parent is positioned relative
      if (getComputedStyle(block).position === "static") {
        block.style.position = "relative";
      }

      // Show button on hover
      block.addEventListener("mouseenter", () => {
        copyButton.style.opacity = "1";
      });
      block.addEventListener("mouseleave", () => {
        copyButton.style.opacity = "0";
      });

      copyButton.addEventListener("click", () => {
        const code =
          block.querySelector("code")?.textContent || block.textContent;

        navigator.clipboard
          .writeText(code)
          .then(() => {
            copyButton.classList.add("copied");
            copyButton.textContent = "Copied!";
            copyButton.style.background = "#00c98d";

            setTimeout(() => {
              copyButton.classList.remove("copied");
              copyButton.textContent = "Copy";
              copyButton.style.background = "#5333ed";
            }, 2000);
          })
          .catch((err) => {
            console.error("Failed to copy:", err);
            copyButton.textContent = "Error!";
            copyButton.style.background = "#ef4444";
            setTimeout(() => {
              copyButton.textContent = "Copy";
              copyButton.style.background = "#5333ed";
            }, 2000);
          });
      });

      block.appendChild(copyButton);
      console.log("Added copy button to block");
    });
  } else {
    console.log("Skipping copy buttons - this is a notebook page");
  }

  // --- Enhanced Search Modal ---
  const searchButton = document.querySelector(".search-button");
  const searchModal = document.querySelector(".search-modal");
  const searchClose = document.querySelector(".search-close");
  const searchInput = document.querySelector(".search-input");

  if (searchButton && searchModal && searchInput) {
    const openSearch = () => {
      searchModal.classList.add("active");
      document.body.style.overflow = "hidden";

      // Focus search input after animation
      setTimeout(() => {
        searchInput.focus();
      }, 100);
    };

    const closeSearch = () => {
      searchModal.classList.remove("active");
      document.body.style.overflow = "";
      searchInput.value = "";
    };

    searchButton.addEventListener("click", openSearch);
    searchClose?.addEventListener("click", closeSearch);

    // Close on backdrop click
    searchModal.addEventListener("click", (e) => {
      if (e.target === searchModal) {
        closeSearch();
      }
    });

    // Keyboard shortcuts
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        openSearch();
      }

      if (e.key === "Escape" && searchModal.classList.contains("active")) {
        closeSearch();
      }
    });

    // Search functionality placeholder
    searchInput.addEventListener("input", (e) => {
      const query = e.target.value;
      // Search implementation would go here
      console.log("Search query:", query);
    });
  }

  // --- Dynamic Page Transitions ---
  const addPageTransitions = () => {
    const mainContent = document.querySelector(".main-content");
    if (!mainContent) return;

    // Add fade-in class to trigger animations
    setTimeout(() => {
      mainContent.classList.add("fade-in");
    }, 100);

    // Handle internal link transitions
    const internalLinks = document.querySelectorAll(
      'a[href^="/"], a[href^="./"], a[href^="../"]',
    );

    internalLinks.forEach((link) => {
      link.addEventListener("click", (e) => {
        // Allow default navigation but add visual feedback
        link.style.transform = "scale(0.98)";
        setTimeout(() => {
          link.style.transform = "";
        }, 150);
      });
    });
  };

  addPageTransitions();

  // --- Accessibility Enhancements ---
  const enhanceAccessibility = () => {
    // Add skip-to-content link
    const skipLink = document.createElement("a");
    skipLink.href = "#main-content";
    skipLink.textContent = "Skip to main content";
    skipLink.className = "skip-link";
    skipLink.style.cssText = `
      position: absolute;
      top: -40px;
      left: 6px;
      background: var(--lab-violet);
      color: white;
      padding: 8px;
      text-decoration: none;
      border-radius: 4px;
      z-index: 1000;
      transition: top 0.3s;
    `;

    skipLink.addEventListener("focus", () => {
      skipLink.style.top = "6px";
    });

    skipLink.addEventListener("blur", () => {
      skipLink.style.top = "-40px";
    });

    document.body.insertBefore(skipLink, document.body.firstChild);

    // Add main content ID if missing
    const mainContent = document.querySelector(".main-content, .page-content");
    if (mainContent && !mainContent.id) {
      mainContent.id = "main-content";
    }

    // Enhance focus indicators
    const focusableElements = document.querySelectorAll(
      'a, button, input, textarea, select, [tabindex]:not([tabindex="-1"])',
    );

    focusableElements.forEach((element) => {
      element.addEventListener("focus", () => {
        element.style.outline = "3px solid var(--lab-violet)";
        element.style.outlineOffset = "2px";
      });

      element.addEventListener("blur", () => {
        element.style.outline = "";
        element.style.outlineOffset = "";
      });
    });
  };

  enhanceAccessibility();

  // --- Performance Monitoring ---
  const monitorPerformance = () => {
    if (window.performance && window.performance.mark) {
      window.performance.mark("theme-enhancement-complete");

      // Log performance metrics in development
      if (window.location.hostname === "localhost") {
        setTimeout(() => {
          const navigation = performance.getEntriesByType("navigation")[0];
          console.log("Page Load Performance:", {
            domContentLoaded:
              navigation.domContentLoadedEventEnd -
              navigation.domContentLoadedEventStart,
            loadComplete: navigation.loadEventEnd - navigation.loadEventStart,
            totalTime: navigation.loadEventEnd - navigation.fetchStart,
          });
        }, 0);
      }
    }
  };

  monitorPerformance();
});
