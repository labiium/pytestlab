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

  // --- Enhanced Jupyter Notebook Cell Processing ---
  const notebookCodeBlocks = document.querySelectorAll(
    ".nb-input pre, .nb-output pre",
  );
  notebookCodeBlocks.forEach((block) => {
    // Add enhanced copy button
    const copyButton = document.createElement("button");
    copyButton.className = "copy-button";
    copyButton.innerHTML =
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"></path></svg>Copy';
    copyButton.setAttribute("aria-label", "Copy code to clipboard");

    copyButton.addEventListener("click", () => {
      const code =
        block.querySelector("code")?.textContent || block.textContent;

      // Add ripple effect
      const ripple = document.createElement("span");
      ripple.className = "copy-ripple";
      copyButton.appendChild(ripple);

      setTimeout(() => {
        ripple.remove();
      }, 600);

      navigator.clipboard
        .writeText(code)
        .then(() => {
          copyButton.classList.add("copied");
          copyButton.innerHTML =
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20,6 9,17 4,12"></polyline></svg>Copied!';

          // Success pulse effect
          const pulse = document.createElement("span");
          pulse.className = "success-pulse";
          block.appendChild(pulse);

          setTimeout(() => {
            pulse.remove();
          }, 1000);

          setTimeout(() => {
            copyButton.classList.remove("copied");
            copyButton.innerHTML =
              '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"></path></svg>Copy';
          }, 2000);
        })
        .catch((err) => {
          console.error("Failed to copy:", err);
          copyButton.classList.add("error");
          copyButton.textContent = "Error!";

          setTimeout(() => {
            copyButton.classList.remove("error");
            copyButton.innerHTML =
              '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"></path></svg>Copy';
          }, 2000);
        });
    });

    block.appendChild(copyButton);

    // Add language badge
    const codeElement = block.querySelector("code");
    if (codeElement) {
      let language = null;

      // Try to detect language from class
      const classList = codeElement.className.match(/language-(\w+)/);
      if (classList) {
        language = classList[1];
      } else if (block.closest(".nb-input")) {
        // Default to Python for input cells
        language = "python";
      }

      if (language) {
        const langBadge = document.createElement("div");
        langBadge.className = "lang-badge";

        // Format language name
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
        };

        const displayLang =
          langMap[language.toLowerCase()] ||
          language.charAt(0).toUpperCase() + language.slice(1);

        langBadge.textContent = displayLang;
        block.appendChild(langBadge);
      }
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

  // --- Add style to scrollbar, copy animations, and Jupyter notebook styling for WebKit browsers ---
  const style = document.createElement("style");
  style.textContent = `
        ::-webkit-scrollbar {
            width: 12px;
            height: 12px;
        }
        ::-webkit-scrollbar-track {
            background: rgba(30, 33, 38, 0.3);
            border-radius: 10px;
        }
        ::-webkit-scrollbar-thumb {
            background: var(--graphite-70);
            border-radius: 10px;
            border: 3px solid rgba(30, 33, 38, 0.3);
        }
        ::-webkit-scrollbar-thumb:hover {
            background: var(--lab-violet);
        }

        /* Jupyter Notebook Styling */
        .nb-cell {
            margin-bottom: var(--spacing-lg, 1.5rem);
        }

        .nb-input, .nb-output {
            background: rgba(30, 33, 38, 0.75);
            border: 1px solid var(--glass-border, rgba(255, 255, 255, 0.1));
            border-radius: var(--border-radius-md, 8px);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            margin-bottom: var(--spacing-md, 1rem);
            overflow: hidden;
        }

        .nb-input-prompt, .nb-output-prompt {
            background: rgba(83, 51, 237, 0.1);
            border-right: 2px solid var(--lab-violet, #5333ed);
            color: var(--lab-violet, #5333ed);
            font-family: var(--font-code, monospace);
            font-size: 0.85rem;
            font-weight: 500;
            padding: 0.5rem 1rem;
            min-width: 80px;
            text-align: center;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .nb-output-prompt {
            background: rgba(4, 226, 220, 0.1);
            border-right-color: var(--lab-aqua, #04e2dc);
            color: var(--lab-aqua, #04e2dc);
        }

        .nb-input-content, .nb-output-content {
            padding: var(--spacing-md, 1rem);
        }

        .nb-input pre, .nb-output pre {
            background: transparent !important;
            border: none !important;
            margin: 0 !important;
            padding: 0 !important;
        }

        .nb-input code, .nb-output code {
            background: transparent !important;
            color: var(--photon-white, #f5f7fa) !important;
            font-family: var(--font-code, monospace) !important;
            font-size: 0.9rem !important;
            line-height: 1.6 !important;
        }

        .nb-output-text {
            color: var(--photon-white, #f5f7fa);
            font-family: var(--font-code, monospace);
            font-size: 0.9rem;
            line-height: 1.6;
            white-space: pre-wrap;
        }

        .nb-output-image, .nb-output-display-data {
            text-align: center;
            padding: var(--spacing-md, 1rem);
        }

        .nb-output img {
            max-width: 100%;
            height: auto;
            border-radius: var(--border-radius-sm, 4px);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }

        .nb-error {
            background: rgba(255, 84, 96, 0.1) !important;
            border-color: var(--status-error, #ff5460) !important;
            color: var(--status-error, #ff5460) !important;
        }

        .nb-error .nb-output-prompt {
            background: rgba(255, 84, 96, 0.2);
            border-right-color: var(--status-error, #ff5460);
            color: var(--status-error, #ff5460);
        }

        /* Enhanced code block styling for notebooks */
        .nb-input .copy-button, .nb-output .copy-button {
            background: rgba(30, 33, 38, 0.9);
            border: 1px solid var(--glass-border, rgba(255, 255, 255, 0.1));
        }

        .nb-input:hover .copy-button, .nb-output:hover .copy-button {
            opacity: 1;
        }

        /* Copy Button Animation */
        .copy-ripple {
            position: absolute;
            top: 50%;
            left: 50%;
            width: 5px;
            height: 5px;
            background: rgba(255, 255, 255, 0.8);
            border-radius: 50%;
            transform: translate(-50%, -50%);
            animation: copy-ripple 0.6s ease-out;
            pointer-events: none;
        }

        @keyframes copy-ripple {
            0% {
                width: 5px;
                height: 5px;
                opacity: 1;
            }
            100% {
                width: 100px;
                height: 100px;
                opacity: 0;
            }
        }

        .success-pulse {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            border-radius: var(--border-radius-md, 8px);
            box-shadow: 0 0 0 0 rgba(0, 178, 124, 0.7);
            opacity: 0.6;
            animation: success-pulse 1s ease-out;
            pointer-events: none;
        }

        @keyframes success-pulse {
            0% {
                box-shadow: 0 0 0 0 rgba(0, 178, 124, 0.7);
            }
            70% {
                box-shadow: 0 0 0 15px rgba(0, 178, 124, 0);
            }
            100% {
                box-shadow: 0 0 0 0 rgba(0, 178, 124, 0);
                opacity: 0;
            }
        }
    `;
  document.head.appendChild(style);
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
