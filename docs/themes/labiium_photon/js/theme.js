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

  // --- Enhanced Mobile Navigation Toggle ---
  const menuToggle = document.querySelector(".menu-toggle");
  const navPrimary = document.querySelector(".nav-primary");

  if (menuToggle && navPrimary) {
    const openNav = () => {
      menuToggle.classList.add("active");
      navPrimary.classList.add("active");
      document.body.style.overflow = "hidden";
    };

    const closeNav = () => {
      menuToggle.classList.remove("active");
      navPrimary.classList.remove("active");
      document.body.style.overflow = "";

      // Close any open dropdowns
      document.querySelectorAll(".dropdown.active").forEach((dropdown) => {
        dropdown.classList.remove("active");
      });
    };

    // Ensure hamburger menu works in production
    const handleMenuClick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      console.log("Menu toggle clicked");
      if (navPrimary.classList.contains("active")) {
        closeNav();
      } else {
        openNav();
      }
    };

    menuToggle.addEventListener("click", handleMenuClick);
    menuToggle.addEventListener("touchstart", handleMenuClick, {
      passive: true,
    });

    // Close menu when clicking on the nav background (not nav content)
    navPrimary.addEventListener("click", (e) => {
      // Only close if clicking directly on the nav container, not its children
      if (e.target === navPrimary) {
        closeNav();
      }
    });

    // Close menu when clicking outside nav content
    document.addEventListener("click", (e) => {
      if (
        navPrimary.classList.contains("active") &&
        !navPrimary.contains(e.target) &&
        !menuToggle.contains(e.target)
      ) {
        closeNav();
      }
    });

    // Close menu on escape key
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && navPrimary.classList.contains("active")) {
        closeNav();
      }
    });

    // Close menu when clicking on nav links
    const navLinks = document.querySelectorAll(".nav-links a");
    navLinks.forEach((link) => {
      link.addEventListener("click", () => {
        if (!link.classList.contains("dropdown-toggle")) {
          closeNav();
        }
      });
    });

    // Handle dropdown toggles
    const dropdownToggles = document.querySelectorAll(".dropdown-toggle");
    dropdownToggles.forEach((toggle) => {
      toggle.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();

        const dropdown = toggle.closest(".dropdown");
        const isActive = dropdown.classList.contains("active");

        // Close all other dropdowns
        document
          .querySelectorAll(".dropdown.active")
          .forEach((otherDropdown) => {
            if (otherDropdown !== dropdown) {
              otherDropdown.classList.remove("active");
            }
          });

        // Toggle current dropdown
        dropdown.classList.toggle("active", !isActive);
      });
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
    let searchIndex = null;

    // Load search index - try multiple paths for production compatibility
    const baseUrl =
      window.location.origin + window.location.pathname.replace(/[^/]*$/, "");
    const searchPaths = [
      baseUrl + "search/search_index.json",
      "./search/search_index.json",
      "search/search_index.json",
      "../search/search_index.json",
      "/search/search_index.json",
      window.location.origin + "/search/search_index.json",
    ];

    async function loadSearchIndex() {
      for (const path of searchPaths) {
        try {
          console.log("Trying search index path:", path);
          const response = await fetch(path);
          if (response.ok) {
            const data = await response.json();
            searchIndex = data;
            console.log("Search index loaded successfully from:", path);
            return;
          }
        } catch (error) {
          console.log("Failed to load search index from:", path, error);
        }
      }
      console.log("Search index could not be loaded from any path");
    }

    loadSearchIndex();

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

      // Clear search results
      const searchResults = document.getElementById("searchResults");
      const searchResultsMeta = document.getElementById("searchResultsMeta");
      if (searchResults) searchResults.innerHTML = "";
      if (searchResultsMeta)
        searchResultsMeta.textContent = "Type to start searching";
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

    // Search functionality
    searchInput.addEventListener("input", (e) => {
      const query = e.target.value.trim().toLowerCase();
      const searchResultsMeta = document.getElementById("searchResultsMeta");
      const searchResults = document.getElementById("searchResults");

      if (query.length > 1) {
        if (searchResultsMeta) searchResultsMeta.textContent = "Searching...";
        if (searchResults) searchResults.innerHTML = "";

        if (searchIndex) {
          console.log(
            "Search index is available, performing search for:",
            query,
          );
          const results = performSearch(query, searchIndex);
          console.log("Search results:", results);
          displaySearchResults(results, searchResultsMeta, searchResults);
        } else {
          console.log("Search index is null, showing error message");
          if (searchResultsMeta)
            searchResultsMeta.textContent = "Search index not loaded";
          if (searchResults) {
            searchResults.innerHTML =
              '<p style="color: rgba(255, 255, 255, 0.7); padding: 1rem; text-align: center;">Search functionality requires the MkDocs search plugin to be enabled and the site to be built.</p>';
          }
        }
      } else {
        if (searchResultsMeta)
          searchResultsMeta.textContent = "Type to start searching";
        if (searchResults) searchResults.innerHTML = "";
      }
    });

    function performSearch(query, index) {
      const results = [];
      const docs = index.docs || [];

      docs.forEach((doc, i) => {
        const title = (doc.title || "").toLowerCase();
        const text = (doc.text || "").toLowerCase();

        if (title.includes(query) || text.includes(query)) {
          const titleIndex = title.indexOf(query);
          const textIndex = text.indexOf(query);
          const score = (titleIndex >= 0 ? 10 : 0) + (textIndex >= 0 ? 1 : 0);

          results.push({
            title: doc.title,
            location: doc.location,
            text: doc.text,
            score: score,
          });
        }
      });

      return results.sort((a, b) => b.score - a.score).slice(0, 10);
    }

    function displaySearchResults(results, metaElement, resultsElement) {
      if (!metaElement || !resultsElement) return;

      if (results.length > 0) {
        metaElement.textContent = `${results.length} result${results.length > 1 ? "s" : ""} found`;

        resultsElement.innerHTML = results
          .map((result) => {
            // Handle relative URLs properly
            let resultUrl = result.location;
            if (
              resultUrl &&
              !resultUrl.startsWith("http") &&
              !resultUrl.startsWith("#")
            ) {
              if (!resultUrl.startsWith("/")) {
                resultUrl = "../" + resultUrl;
              }
            }

            return `
              <div class="search-result-item">
                <a href="${resultUrl}" class="search-result-link">
                  <div class="search-result-title">${result.title}</div>
                  <div class="search-result-text">${result.text.substring(0, 150)}...</div>
                </a>
              </div>
            `;
          })
          .join("");
      } else {
        metaElement.textContent = "No results found";
        resultsElement.innerHTML = "";
      }
    }
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
