#!/usr/bin/env python3
"""
Production-equivalent testing script for PyTestLab documentation.
Tests hamburger menu functionality and search features in a production-like environment.
"""

import asyncio
import json
import subprocess
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, WebDriverException
import sys
import os


class ProductionTester:
    def __init__(self, base_url="http://localhost:8080"):
        self.base_url = base_url
        self.driver = None
        self.server_process = None
        self.test_results = []

    def setup_chrome_driver(self):
        """Setup Chrome driver with mobile and desktop viewports"""
        chrome_options = Options()
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        # Uncomment for headless testing
        # chrome_options.add_argument("--headless")

        try:
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.implicitly_wait(10)
            return True
        except Exception as e:
            print(f"❌ Failed to setup Chrome driver: {e}")
            return False

    def start_production_server(self):
        """Start production-equivalent HTTP server"""
        try:
            os.chdir("site")
            self.server_process = subprocess.Popen(
                [sys.executable, "-m", "http.server", "8080", "--bind", "0.0.0.0"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            time.sleep(3)  # Give server time to start

            # Test server is running
            response = requests.get(f"{self.base_url}/", timeout=5)
            if response.status_code == 200:
                print(f"✅ Production server started at {self.base_url}")
                return True
            else:
                print(f"❌ Server returned status {response.status_code}")
                return False

        except Exception as e:
            print(f"❌ Failed to start production server: {e}")
            return False

    def test_search_index_accessibility(self):
        """Test if search index is accessible via HTTP"""
        print("\n🔍 Testing Search Index Accessibility...")

        search_paths = [
            "/search/search_index.json",
            "/search/lunr.js",
            "/search/main.js"
        ]

        results = []
        for path in search_paths:
            try:
                response = requests.get(f"{self.base_url}{path}", timeout=10)
                status = "✅ PASS" if response.status_code == 200 else f"❌ FAIL ({response.status_code})"
                print(f"  {path}: {status}")
                results.append({
                    "path": path,
                    "status": response.status_code,
                    "size": len(response.content) if response.status_code == 200 else 0
                })
            except Exception as e:
                print(f"  {path}: ❌ ERROR - {e}")
                results.append({"path": path, "error": str(e)})

        return results

    def test_search_functionality_javascript(self):
        """Test search functionality using JavaScript execution"""
        print("\n🔍 Testing Search Functionality (JavaScript)...")

        try:
            # Navigate to home page
            self.driver.get(f"{self.base_url}/")
            time.sleep(2)

            # Test search index loading
            search_test_script = """
            return new Promise((resolve) => {
                const searchPaths = [
                    './search/search_index.json',
                    'search/search_index.json',
                    '/search/search_index.json'
                ];

                let results = [];
                let completed = 0;

                searchPaths.forEach(async (path) => {
                    try {
                        const response = await fetch(path);
                        results.push({
                            path: path,
                            status: response.status,
                            ok: response.ok,
                            size: response.ok ? (await response.text()).length : 0
                        });
                    } catch (error) {
                        results.push({
                            path: path,
                            error: error.message
                        });
                    }

                    completed++;
                    if (completed === searchPaths.length) {
                        resolve(results);
                    }
                });
            });
            """

            results = self.driver.execute_async_script(search_test_script)

            working_paths = [r for r in results if r.get('ok', False)]
            print(f"  Working search paths: {len(working_paths)}/{len(results)}")

            for result in results:
                if result.get('ok'):
                    print(f"  ✅ {result['path']}: {result['status']} ({result.get('size', 0)} bytes)")
                else:
                    error = result.get('error', f"HTTP {result.get('status', 'unknown')}")
                    print(f"  ❌ {result['path']}: {error}")

            return len(working_paths) > 0

        except Exception as e:
            print(f"  ❌ JavaScript search test failed: {e}")
            return False

    def test_hamburger_menu_desktop(self):
        """Test hamburger menu on desktop viewport"""
        print("\n🍔 Testing Hamburger Menu (Desktop)...")

        try:
            # Set desktop viewport
            self.driver.set_window_size(1920, 1080)
            self.driver.get(f"{self.base_url}/installation/")
            time.sleep(2)

            # Hamburger should be hidden on desktop
            hamburger = self.driver.find_element(By.ID, "menuToggle")
            is_displayed = hamburger.is_displayed()

            print(f"  Hamburger visibility on desktop: {'❌ VISIBLE (should be hidden)' if is_displayed else '✅ HIDDEN (correct)'}")
            return not is_displayed

        except Exception as e:
            print(f"  ❌ Desktop hamburger test failed: {e}")
            return False

    def test_hamburger_menu_mobile(self):
        """Test hamburger menu on mobile viewport"""
        print("\n📱 Testing Hamburger Menu (Mobile)...")

        try:
            # Set mobile viewport
            self.driver.set_window_size(375, 667)
            self.driver.get(f"{self.base_url}/installation/")
            time.sleep(2)

            # Find hamburger menu
            hamburger = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "menuToggle"))
            )

            # Check if hamburger is visible on mobile
            is_displayed = hamburger.is_displayed()
            print(f"  Hamburger visibility on mobile: {'✅ VISIBLE' if is_displayed else '❌ HIDDEN'}")

            if not is_displayed:
                return False

            # Check hamburger properties
            hamburger_style = self.driver.execute_script("""
                const hamburger = document.getElementById('menuToggle');
                const styles = window.getComputedStyle(hamburger);
                return {
                    display: styles.display,
                    zIndex: styles.zIndex,
                    position: styles.position,
                    pointerEvents: styles.pointerEvents,
                    cursor: styles.cursor
                };
            """)

            print(f"  Hamburger CSS properties:")
            for prop, value in hamburger_style.items():
                print(f"    {prop}: {value}")

            # Test hamburger click
            nav_primary = self.driver.find_element(By.CLASS_NAME, "nav-primary")
            nav_initially_active = "active" in nav_primary.get_attribute("class")

            print(f"  Navigation initially active: {nav_initially_active}")

            # Click hamburger
            ActionChains(self.driver).click(hamburger).perform()
            time.sleep(1)

            # Check if navigation opened
            nav_after_click = self.driver.find_element(By.CLASS_NAME, "nav-primary")
            nav_active_after_click = "active" in nav_after_click.get_attribute("class")

            print(f"  Navigation active after click: {nav_active_after_click}")

            # Test navigation items are clickable
            if nav_active_after_click:
                nav_links = self.driver.find_elements(By.CSS_SELECTOR, ".nav-links a")
                print(f"  Found {len(nav_links)} navigation links")

                if nav_links:
                    # Test first link
                    first_link = nav_links[0]
                    link_text = first_link.text
                    link_href = first_link.get_attribute("href")
                    print(f"  First link: '{link_text}' -> {link_href}")

                    # Check if link is clickable
                    try:
                        ActionChains(self.driver).click(first_link).perform()
                        time.sleep(1)
                        print("  ✅ Navigation link clickable")
                        return True
                    except Exception as e:
                        print(f"  ❌ Navigation link not clickable: {e}")
                        return False

            return nav_active_after_click and not nav_initially_active

        except Exception as e:
            print(f"  ❌ Mobile hamburger test failed: {e}")
            return False

    def test_search_modal_zindex(self):
        """Test search modal z-index layering"""
        print("\n🔍 Testing Search Modal Z-Index...")

        try:
            # Set mobile viewport to trigger hamburger
            self.driver.set_window_size(375, 667)
            self.driver.get(f"{self.base_url}/installation/")
            time.sleep(2)

            # Get z-index values
            z_indexes = self.driver.execute_script("""
                const elements = {
                    hamburger: document.querySelector('.menu-toggle'),
                    navigation: document.querySelector('.nav-primary'),
                    searchModal: document.querySelector('.search-modal'),
                    header: document.querySelector('.site-header')
                };

                const result = {};
                for (const [name, element] of Object.entries(elements)) {
                    if (element) {
                        const styles = window.getComputedStyle(element);
                        result[name] = {
                            zIndex: styles.zIndex,
                            position: styles.position,
                            display: styles.display
                        };
                    } else {
                        result[name] = null;
                    }
                }
                return result;
            """)

            print("  Z-Index layers:")
            for element, props in z_indexes.items():
                if props:
                    print(f"    {element}: z-index={props['zIndex']}, position={props['position']}")
                else:
                    print(f"    {element}: ❌ Not found")

            # Check proper layering
            if z_indexes.get('searchModal') and z_indexes.get('hamburger'):
                search_z = int(z_indexes['searchModal']['zIndex']) if z_indexes['searchModal']['zIndex'] != 'auto' else 0
                hamburger_z = int(z_indexes['hamburger']['zIndex']) if z_indexes['hamburger']['zIndex'] != 'auto' else 0

                proper_layering = search_z > hamburger_z
                print(f"  Proper z-index layering: {'✅ CORRECT' if proper_layering else '❌ INCORRECT'}")
                return proper_layering

            return False

        except Exception as e:
            print(f"  ❌ Z-index test failed: {e}")
            return False

    def test_search_modal_functionality(self):
        """Test search modal open/close functionality"""
        print("\n🔍 Testing Search Modal Functionality...")

        try:
            self.driver.get(f"{self.base_url}/installation/")
            time.sleep(2)

            # Find search button
            search_button = self.driver.find_element(By.ID, "searchButton")
            print("  ✅ Search button found")

            # Click search button
            ActionChains(self.driver).click(search_button).perform()
            time.sleep(1)

            # Check if search modal opened
            search_modal = self.driver.find_element(By.ID, "searchModal")
            modal_active = "active" in search_modal.get_attribute("class")
            print(f"  Search modal opened: {'✅ YES' if modal_active else '❌ NO'}")

            if modal_active:
                # Test search input
                search_input = self.driver.find_element(By.ID, "searchInput")
                search_input.send_keys("pytestlab")
                time.sleep(2)

                # Check for search results
                search_results = self.driver.find_element(By.ID, "searchResults")
                results_html = search_results.get_attribute("innerHTML")
                has_results = len(results_html.strip()) > 0
                print(f"  Search results generated: {'✅ YES' if has_results else '❌ NO'}")

                # Close modal with escape key
                search_input.send_keys('\ue00c')  # ESC key
                time.sleep(1)

                modal_closed = "active" not in search_modal.get_attribute("class")
                print(f"  Search modal closed with ESC: {'✅ YES' if modal_closed else '❌ NO'}")

                return modal_active and has_results and modal_closed

            return False

        except Exception as e:
            print(f"  ❌ Search modal test failed: {e}")
            return False

    def run_all_tests(self):
        """Run all production tests"""
        print("🚀 Starting Production-Equivalent Tests for PyTestLab Documentation")
        print("=" * 80)

        # Setup
        if not self.start_production_server():
            print("❌ Failed to start production server. Exiting.")
            return False

        if not self.setup_chrome_driver():
            print("❌ Failed to setup Chrome driver. Exiting.")
            return False

        # Run tests
        tests = [
            ("Search Index Accessibility", self.test_search_index_accessibility),
            ("Search Functionality (JavaScript)", self.test_search_functionality_javascript),
            ("Hamburger Menu (Desktop)", self.test_hamburger_menu_desktop),
            ("Hamburger Menu (Mobile)", self.test_hamburger_menu_mobile),
            ("Search Modal Z-Index", self.test_search_modal_zindex),
            ("Search Modal Functionality", self.test_search_modal_functionality),
        ]

        results = []
        passed = 0
        total = len(tests)

        for test_name, test_func in tests:
            try:
                result = test_func()
                results.append((test_name, result))
                if result:
                    passed += 1
            except Exception as e:
                print(f"❌ {test_name} crashed: {e}")
                results.append((test_name, False))

        # Summary
        print("\n" + "=" * 80)
        print("📊 TEST SUMMARY")
        print("=" * 80)

        for test_name, result in results:
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"{status} {test_name}")

        print(f"\nOverall: {passed}/{total} tests passed ({passed/total*100:.1f}%)")

        if passed == total:
            print("🎉 All tests passed! Production-equivalent environment is working correctly.")
        else:
            print("⚠️  Some tests failed. Check the output above for details.")

        return passed == total

    def cleanup(self):
        """Cleanup resources"""
        if self.driver:
            self.driver.quit()

        if self.server_process:
            self.server_process.terminate()
            self.server_process.wait()

        print("\n🧹 Cleanup completed")


def main():
    """Main entry point"""
    # Check if we're in the right directory
    if not os.path.exists("site"):
        print("❌ Error: 'site' directory not found. Please run from PyTestLab root directory after building docs.")
        sys.exit(1)

    tester = ProductionTester()

    try:
        success = tester.run_all_tests()
        sys.exit(0 if success else 1)
    finally:
        tester.cleanup()


if __name__ == "__main__":
    main()
