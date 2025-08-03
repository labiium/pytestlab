/**
 * PyTestLab Notebook Enhancements
 * ===============================
 *
 * Enhanced JavaScript functionality for Jupyter notebooks in PyTestLab documentation.
 * Provides professional interactions, copy-to-clipboard functionality, and improved UX.
 *
 * Features:
 * - Smart copy-to-clipboard for code cells
 * - Enhanced keyboard navigation
 * - Progressive enhancement for better accessibility
 * - Smooth animations and transitions
 * - Cell execution indicators
 * - Professional tooltip system
 */

(function() {
    'use strict';

    // Configuration
    const CONFIG = {
        copyTimeout: 2000,
        animationDuration: 300,
        tooltipDelay: 500,
        debugMode: false
    };

    // Utility functions
    const utils = {
        /**
         * Log debug messages if debug mode is enabled
         */
        debug: (...args) => {
            if (CONFIG.debugMode) {
                console.log('[PyTestLab Notebooks]', ...args);
            }
        },

        /**
         * Create a debounced function
         */
        debounce: (func, wait) => {
            let timeout;
            return function executedFunction(...args) {
                const later = () => {
                    clearTimeout(timeout);
                    func(...args);
                };
                clearTimeout(timeout);
                timeout = setTimeout(later, wait);
            };
        },

        /**
         * Check if element is visible in viewport
         */
        isInViewport: (element) => {
            const rect = element.getBoundingClientRect();
            return (
                rect.top >= 0 &&
                rect.left >= 0 &&
                rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
                rect.right <= (window.innerWidth || document.documentElement.clientWidth)
            );
        },

        /**
         * Smooth scroll to element
         */
        scrollToElement: (element, offset = 100) => {
            const targetPosition = element.offsetTop - offset;
            window.scrollTo({
                top: targetPosition,
                behavior: 'smooth'
            });
        }
    };

    // Copy to clipboard functionality
    const copyToClipboard = {
        /**
         * Copy text to clipboard using modern API with fallback
         */
        async copyText(text) {
            try {
                if (navigator.clipboard && window.isSecureContext) {
                    await navigator.clipboard.writeText(text);
                    return true;
                } else {
                    // Fallback for older browsers or non-secure contexts
                    return this.fallbackCopy(text);
                }
            } catch (err) {
                utils.debug('Clipboard API failed, using fallback:', err);
                return this.fallbackCopy(text);
            }
        },

        /**
         * Fallback copy method for older browsers
         */
        fallbackCopy(text) {
            try {
                const textArea = document.createElement('textarea');
                textArea.value = text;
                textArea.style.position = 'fixed';
                textArea.style.left = '-999999px';
                textArea.style.top = '-999999px';
                document.body.appendChild(textArea);
                textArea.focus();
                textArea.select();

                const successful = document.execCommand('copy');
                document.body.removeChild(textArea);
                return successful;
            } catch (err) {
                utils.debug('Fallback copy failed:', err);
                return false;
            }
        },

        /**
         * Extract clean code from code cell
         */
        extractCodeFromCell(cell) {
            const codeElement = cell.querySelector('pre code, pre, .jp-Editor .jp-InputArea-editor, .highlight');
            if (!codeElement) return '';

            // Get text content and clean it up
            let code = codeElement.textContent || codeElement.innerText || '';

            // Remove execution count and prompt indicators
            code = code.replace(/^In\s*\[\d*\]:\s*/gm, '');
            code = code.replace(/^Out\s*\[\d*\]:\s*/gm, '');

            // Remove leading/trailing whitespace but preserve internal formatting
            code = code.trim();

            return code;
        },

        /**
         * Create and show copy button for a cell
         */
        createCopyButton(cell) {
            const copyButton = document.createElement('button');
            copyButton.className = 'copy-button';
            copyButton.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                </svg>
                <span>Copy</span>
            `;
            copyButton.setAttribute('aria-label', 'Copy code to clipboard');
            copyButton.setAttribute('title', 'Copy code to clipboard');

            copyButton.addEventListener('click', async (e) => {
                e.preventDefault();
                e.stopPropagation();

                const code = this.extractCodeFromCell(cell);
                if (!code) {
                    this.showCopyFeedback(copyButton, 'No code found', 'error');
                    return;
                }

                const success = await this.copyText(code);
                if (success) {
                    this.showCopyFeedback(copyButton, 'Copied!', 'success');
                    utils.debug('Code copied to clipboard:', code.substring(0, 50) + '...');
                } else {
                    this.showCopyFeedback(copyButton, 'Copy failed', 'error');
                }
            });

            return copyButton;
        },

        /**
         * Show visual feedback for copy operation
         */
        showCopyFeedback(button, message, type = 'success') {
            const originalContent = button.innerHTML;
            const icon = type === 'success' ? '✓' : '✗';

            button.innerHTML = `<span>${icon} ${message}</span>`;
            button.classList.add('copied', type);

            setTimeout(() => {
                button.innerHTML = originalContent;
                button.classList.remove('copied', 'success', 'error');
            }, CONFIG.copyTimeout);
        }
    };

    // Enhanced cell interactions
    const cellEnhancements = {
        /**
         * Add hover effects and interactions to cells
         */
        enhanceCell(cell) {
            // Add smooth hover transitions
            cell.style.transition = 'all 0.3s cubic-bezier(0.16, 1, 0.3, 1)';

            // Add focus support for keyboard navigation
            if (!cell.hasAttribute('tabindex')) {
                cell.setAttribute('tabindex', '0');
            }

            // Enhance accessibility
            const cellType = this.getCellType(cell);
            cell.setAttribute('role', 'region');
            cell.setAttribute('aria-label', `${cellType} cell`);

            // Add keyboard navigation
            cell.addEventListener('keydown', (e) => {
                this.handleCellKeyboard(e, cell);
            });

            // Add visual focus indicator
            cell.addEventListener('focus', () => {
                cell.style.outline = '3px solid var(--lab-violet, #5333ed)';
                cell.style.outlineOffset = '2px';
            });

            cell.addEventListener('blur', () => {
                cell.style.outline = 'none';
            });
        },

        /**
         * Determine cell type from DOM structure
         */
        getCellType(cell) {
            if (cell.querySelector('.jp-InputArea, .input_area, .nb-input')) {
                return 'code';
            } else if (cell.querySelector('.jp-OutputArea, .output_area, .nb-output')) {
                return 'output';
            } else if (cell.querySelector('.jp-MarkdownCell, .text_cell, .nb-markdown')) {
                return 'markdown';
            }
            return 'unknown';
        },

        /**
         * Handle keyboard navigation within cells
         */
        handleCellKeyboard(e, cell) {
            switch (e.key) {
                case 'c':
                    if (e.ctrlKey || e.metaKey) {
                        e.preventDefault();
                        const copyButton = cell.querySelector('.copy-button');
                        if (copyButton) {
                            copyButton.click();
                        }
                    }
                    break;
                case 'ArrowDown':
                    if (e.ctrlKey) {
                        e.preventDefault();
                        this.focusNextCell(cell);
                    }
                    break;
                case 'ArrowUp':
                    if (e.ctrlKey) {
                        e.preventDefault();
                        this.focusPreviousCell(cell);
                    }
                    break;
                case 'Enter':
                    if (e.ctrlKey) {
                        e.preventDefault();
                        this.scrollToCell(cell);
                    }
                    break;
            }
        },

        /**
         * Focus next cell in document
         */
        focusNextCell(currentCell) {
            const cells = Array.from(document.querySelectorAll('.jp-Cell, .cell, .nb-cell'));
            const currentIndex = cells.indexOf(currentCell);
            const nextCell = cells[currentIndex + 1];

            if (nextCell) {
                nextCell.focus();
                utils.scrollToElement(nextCell);
            }
        },

        /**
         * Focus previous cell in document
         */
        focusPreviousCell(currentCell) {
            const cells = Array.from(document.querySelectorAll('.jp-Cell, .cell, .nb-cell'));
            const currentIndex = cells.indexOf(currentCell);
            const previousCell = cells[currentIndex - 1];

            if (previousCell) {
                previousCell.focus();
                utils.scrollToElement(previousCell);
            }
        },

        /**
         * Scroll to specific cell
         */
        scrollToCell(cell) {
            utils.scrollToElement(cell);
        }
    };

    // Code syntax highlighting enhancements
    const syntaxEnhancements = {
        /**
         * Enhance code syntax highlighting for better readability
         */
        enhanceCodeHighlighting() {
            const codeBlocks = document.querySelectorAll('pre code, .jp-Editor, .highlight');

            codeBlocks.forEach(block => {
                // Add line numbers if not present
                this.addLineNumbers(block);

                // Enhance syntax colors for light theme
                this.optimizeForLightTheme(block);

                // Add code block metadata
                this.addCodeMetadata(block);
            });
        },

        /**
         * Add line numbers to code blocks
         */
        addLineNumbers(codeBlock) {
            if (codeBlock.querySelector('.line-numbers')) return;

            const lines = codeBlock.textContent.split('\n');
            if (lines.length <= 1) return;

            const lineNumbers = document.createElement('div');
            lineNumbers.className = 'line-numbers';
            lineNumbers.setAttribute('aria-hidden', 'true');

            for (let i = 1; i <= lines.length; i++) {
                const lineNumber = document.createElement('div');
                lineNumber.textContent = i;
                lineNumbers.appendChild(lineNumber);
            }

            const container = codeBlock.parentElement;
            container.style.position = 'relative';
            container.style.paddingLeft = '3rem';

            lineNumbers.style.position = 'absolute';
            lineNumbers.style.left = '0';
            lineNumbers.style.top = '0';
            lineNumbers.style.bottom = '0';
            lineNumbers.style.width = '2.5rem';
            lineNumbers.style.fontSize = '0.8rem';
            lineNumbers.style.color = 'rgba(0, 0, 0, 0.4)';
            lineNumbers.style.textAlign = 'right';
            lineNumbers.style.paddingRight = '0.5rem';
            lineNumbers.style.paddingTop = '1rem';
            lineNumbers.style.lineHeight = '1.7';
            lineNumbers.style.borderRight = '1px solid rgba(0, 0, 0, 0.1)';
            lineNumbers.style.background = 'rgba(248, 250, 252, 0.8)';

            container.insertBefore(lineNumbers, codeBlock);
        },

        /**
         * Optimize syntax highlighting for light theme
         */
        optimizeForLightTheme(codeBlock) {
            // This would typically involve adjusting CSS classes
            // The actual implementation depends on the syntax highlighter being used
            codeBlock.classList.add('light-theme-optimized');
        },

        /**
         * Add metadata to code blocks (language, execution time, etc.)
         */
        addCodeMetadata(codeBlock) {
            const metadata = this.extractCodeMetadata(codeBlock);
            if (Object.keys(metadata).length === 0) return;

            const metadataElement = document.createElement('div');
            metadataElement.className = 'code-metadata';
            metadataElement.innerHTML = `
                <div class="metadata-items">
                    ${Object.entries(metadata).map(([key, value]) =>
                        `<span class="metadata-item" data-key="${key}">${value}</span>`
                    ).join('')}
                </div>
            `;

            codeBlock.parentElement.appendChild(metadataElement);
        },

        /**
         * Extract metadata from code block
         */
        extractCodeMetadata(codeBlock) {
            const metadata = {};

            // Detect language
            const languageClass = Array.from(codeBlock.classList).find(cls => cls.startsWith('language-'));
            if (languageClass) {
                metadata.language = languageClass.replace('language-', '');
            }

            // Count lines
            const lineCount = codeBlock.textContent.split('\n').length;
            if (lineCount > 1) {
                metadata.lines = `${lineCount} lines`;
            }

            return metadata;
        }
    };

    // Responsive behavior
    const responsiveEnhancements = {
        /**
         * Initialize responsive behavior for notebooks
         */
        init() {
            this.handleResize = utils.debounce(this.handleResize.bind(this), 250);
            window.addEventListener('resize', this.handleResize);

            // Initial setup
            this.handleResize();
        },

        /**
         * Handle window resize events
         */
        handleResize() {
            const width = window.innerWidth;

            if (width <= 768) {
                this.enableMobileMode();
            } else {
                this.disableMobileMode();
            }
        },

        /**
         * Enable mobile-specific optimizations
         */
        enableMobileMode() {
            document.body.classList.add('notebook-mobile');

            // Adjust copy button positions
            const copyButtons = document.querySelectorAll('.copy-button');
            copyButtons.forEach(button => {
                button.style.top = '0.5rem';
                button.style.right = '0.5rem';
                button.style.fontSize = '0.7rem';
            });
        },

        /**
         * Disable mobile-specific optimizations
         */
        disableMobileMode() {
            document.body.classList.remove('notebook-mobile');

            // Reset copy button positions
            const copyButtons = document.querySelectorAll('.copy-button');
            copyButtons.forEach(button => {
                button.style.top = '';
                button.style.right = '';
                button.style.fontSize = '';
            });
        }
    };

    // Performance monitoring
    const performance = {
        /**
         * Monitor and optimize performance
         */
        init() {
            this.observeIntersection();
            this.monitorScrollPerformance();
        },

        /**
         * Use Intersection Observer for lazy enhancements
         */
        observeIntersection() {
            if (!window.IntersectionObserver) return;

            const observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        this.enhanceCellWhenVisible(entry.target);
                        observer.unobserve(entry.target);
                    }
                });
            }, {
                rootMargin: '50px'
            });

            document.querySelectorAll('.jp-Cell, .cell, .nb-cell').forEach(cell => {
                observer.observe(cell);
            });
        },

        /**
         * Enhance cell when it becomes visible
         */
        enhanceCellWhenVisible(cell) {
            // Add progressive enhancements only when cell is visible
            cellEnhancements.enhanceCell(cell);

            // Add copy button if it's a code cell
            const isCodeCell = cell.querySelector('.jp-InputArea, .input_area, .nb-input');
            if (isCodeCell && !cell.querySelector('.copy-button')) {
                const copyButton = copyToClipboard.createCopyButton(cell);
                cell.appendChild(copyButton);
            }
        },

        /**
         * Monitor scroll performance
         */
        monitorScrollPerformance() {
            let ticking = false;

            const updateScrollEffects = () => {
                // Update any scroll-dependent effects here
                ticking = false;
            };

            window.addEventListener('scroll', () => {
                if (!ticking) {
                    requestAnimationFrame(updateScrollEffects);
                    ticking = true;
                }
            });
        }
    };

    // Main initialization
    const init = () => {
        utils.debug('Initializing PyTestLab notebook enhancements...');

        // Wait for DOM to be ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', init);
            return;
        }

        try {
            // Initialize all enhancement modules
            responsiveEnhancements.init();
            performance.init();
            syntaxEnhancements.enhanceCodeHighlighting();

            // Add global keyboard shortcuts
            document.addEventListener('keydown', (e) => {
                // Ctrl/Cmd + Shift + C: Copy all code cells
                if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'C') {
                    e.preventDefault();
                    copyAllCodeCells();
                }
            });

            utils.debug('PyTestLab notebook enhancements initialized successfully');

        } catch (error) {
            console.error('Error initializing PyTestLab notebook enhancements:', error);
        }
    };

    // Utility function to copy all code cells
    const copyAllCodeCells = async () => {
        const codeCells = document.querySelectorAll('.jp-Cell .jp-InputArea, .cell .input_area, .nb-cell .nb-input');
        const allCode = Array.from(codeCells)
            .map(cell => copyToClipboard.extractCodeFromCell(cell.closest('.jp-Cell, .cell, .nb-cell')))
            .filter(code => code.length > 0)
            .join('\n\n# ---\n\n');

        if (allCode) {
            const success = await copyToClipboard.copyText(allCode);
            if (success) {
                // Show global notification
                showGlobalNotification('All code cells copied to clipboard!', 'success');
            }
        }
    };

    // Global notification system
    const showGlobalNotification = (message, type = 'info') => {
        const notification = document.createElement('div');
        notification.className = `global-notification ${type}`;
        notification.textContent = message;
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: linear-gradient(135deg, var(--lab-violet, #5333ed), var(--lab-aqua, #04e2dc));
            color: white;
            padding: 1rem 1.5rem;
            border-radius: 8px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
            z-index: 10000;
            font-family: var(--font-ui, 'Inter', system-ui, sans-serif);
            font-weight: 500;
            opacity: 0;
            transform: translateX(100%);
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
        `;

        document.body.appendChild(notification);

        // Animate in
        setTimeout(() => {
            notification.style.opacity = '1';
            notification.style.transform = 'translateX(0)';
        }, 10);

        // Remove after delay
        setTimeout(() => {
            notification.style.opacity = '0';
            notification.style.transform = 'translateX(100%)';
            setTimeout(() => {
                document.body.removeChild(notification);
            }, 300);
        }, 3000);
    };

    // Initialize when script loads
    init();

    // Export for potential external use
    window.PyTestLabNotebooks = {
        copyToClipboard,
        cellEnhancements,
        syntaxEnhancements,
        utils
    };

})();
