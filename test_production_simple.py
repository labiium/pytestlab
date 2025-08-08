#!/usr/bin/env python3
"""
Simple production-equivalent testing script for PyTestLab documentation.
Tests core functionality without requiring Selenium.
"""

import json
import subprocess
import time
import requests
import sys
import os
import threading
from urllib.parse import urljoin


class SimpleProductionTester:
    def __init__(self, base_url="http://localhost:8080"):
        self.base_url = base_url
        self.server_process = None
        self.test_results = []

    def start_production_server(self):
        """Start production-equivalent HTTP server"""
        try:
            print("🚀 Starting production-equivalent server...")

            # Change to site directory
            original_dir = os.getcwd()
            os.chdir("site")

            # Start server in background
            self.server_process = subprocess.Popen(
                [sys.executable, "-m", "http.server", "8080", "--bind", "0.0.0.0"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            # Wait for server to start
            time.sleep(3)

            # Test server is running
            try:
                response = requests.get(f"{self.base_url}/", timeout=5)
                if response.status_code == 200:
                    print(f"✅ Production server started at {self.base_url}")
                    os.chdir(original_dir)
                    return True
                else:
                    print(f"❌ Server returned status {response.status_code}")
                    os.chdir(original_dir)
                    return False
            except requests.exceptions.ConnectionError:
                print("❌ Could not connect to server")
                os.chdir(original_dir)
                return False

        except Exception as e:
            print(f"❌ Failed to start production server: {e}")
            return False

    def test_basic_pages(self):
        """Test basic page accessibility"""
        print("\n📄 Testing Basic Page Accessibility...")

        pages = [
            "/",
            "/installation/",
            "/user_guide/getting_started/",
            "/api/instruments/",
            "/tutorials/10_minute_tour/",
            "/debug_search.html"
        ]

        results = {}
        for page in pages:
            try:
                url = urljoin(self.base_url, page)
                response = requests.get(url, timeout=10)
                status = "✅ PASS" if response.status_code == 200 else f"❌ FAIL ({response.status_code})"
                print(f"  {page}: {status}")
                results[page] = response.status_code == 200

                # Check for basic HTML structure
                if response.status_code == 200:
                    content = response.text
                    has_hamburger = 'id="menuToggle"' in content
                    has_search = 'id="searchButton"' in content
                    has_nav = 'class="nav-primary"' in content

                    print(f"    - Hamburger menu: {'✅' if has_hamburger else '❌'}")
                    print(f"    - Search button: {'✅' if has_search else '❌'}")
                    print(f"    - Navigation: {'✅' if has_nav else '❌'}")

            except Exception as e:
                print(f"  {page}: ❌ ERROR - {e}")
                results[page] = False

        return all(results.values())

    def test_search_infrastructure(self):
        """Test search-related files and infrastructure"""
        print("\n🔍 Testing Search Infrastructure...")

        search_files = [
            "/search/search_index.json",
            "/search/lunr.js",
            "/search/main.js",
            "/search/worker.js"
        ]

        results = {}
        for file_path in search_files:
            try:
                url = urljoin(self.base_url, file_path)
                response = requests.get(url, timeout=10)
                status = "✅ PASS" if response.status_code == 200 else f"❌ FAIL ({response.status_code})"
                size = len(response.content) if response.status_code == 200 else 0
                print(f"  {file_path}: {status} ({size:,} bytes)")
                results[file_path] = response.status_code == 200

                # Special check for search index
                if file_path == "/search/search_index.json" and response.status_code == 200:
                    try:
                        data = response.json()
                        doc_count = len(data.get('docs', []))
                        config = data.get('config', {})
                        print(f"    - Documents indexed: {doc_count}")
                        print(f"    - Min search length: {config.get('min_search_length', 'unknown')}")
                        print(f"    - Languages: {config.get('lang', 'unknown')}")
                    except json.JSONDecodeError:
                        print("    - ❌ Invalid JSON format")
                        results[file_path] = False

            except Exception as e:
                print(f"  {file_path}: ❌ ERROR - {e}")
                results[file_path] = False

        return all(results.values())

    def test_css_and_js_assets(self):
        """Test CSS and JS asset loading"""
        print("\n🎨 Testing CSS and JS Assets...")

        assets = [
            "/css/theme.css",
            "/js/theme.js",
            "/stylesheets/extra.css",
            "/stylesheets/notebook-enhancements.css",
            "/js/notebook-enhancements.js"
        ]

        results = {}
        for asset in assets:
            try:
                url = urljoin(self.base_url, asset)
                response = requests.get(url, timeout=10)
                status = "✅ PASS" if response.status_code == 200 else f"❌ FAIL ({response.status_code})"
                size = len(response.content) if response.status_code == 200 else 0
                print(f"  {asset}: {status} ({size:,} bytes)")
                results[asset] = response.status_code == 200

                # Check for key CSS/JS content
                if response.status_code == 200:
                    content = response.text
                    if asset.endswith('.css'):
                        has_hamburger_styles = '.menu-toggle' in content
                        has_search_styles = '.search-modal' in content
                        has_glassmorphism = 'backdrop-filter' in content or 'glass' in content
                        print(f"    - Hamburger styles: {'✅' if has_hamburger_styles else '❌'}")
                        print(f"    - Search styles: {'✅' if has_search_styles else '❌'}")
                        print(f"    - Glassmorphism effects: {'✅' if has_glassmorphism else '❌'}")

                    elif asset.endswith('.js'):
                        has_menu_toggle = 'menuToggle' in content
                        has_search_func = 'searchModal' in content or 'searchButton' in content
                        print(f"    - Menu toggle code: {'✅' if has_menu_toggle else '❌'}")
                        print(f"    - Search functionality: {'✅' if has_search_func else '❌'}")

            except Exception as e:
                print(f"  {asset}: ❌ ERROR - {e}")
                results[asset] = False

        return all(results.values())

    def test_mobile_responsive_headers(self):
        """Test mobile-responsive meta tags and viewport settings"""
        print("\n📱 Testing Mobile Responsive Features...")

        test_pages = ["/", "/installation/", "/api/instruments/"]

        all_responsive = True
        for page in test_pages:
            try:
                url = urljoin(self.base_url, page)
                response = requests.get(url, timeout=10)

                if response.status_code == 200:
                    content = response.text

                    # Check viewport meta tag
                    has_viewport = 'name="viewport"' in content and 'width=device-width' in content

                    # Check responsive CSS media queries
                    has_mobile_styles = '@media' in content and 'max-width' in content

                    # Check hamburger menu presence
                    has_hamburger = 'menu-toggle' in content

                    print(f"  {page}:")
                    print(f"    - Viewport meta tag: {'✅' if has_viewport else '❌'}")
                    print(f"    - Mobile CSS queries: {'✅' if has_mobile_styles else '❌'}")
                    print(f"    - Hamburger menu: {'✅' if has_hamburger else '❌'}")

                    if not all([has_viewport, has_hamburger]):
                        all_responsive = False

                else:
                    print(f"  {page}: ❌ Could not load page")
                    all_responsive = False

            except Exception as e:
                print(f"  {page}: ❌ ERROR - {e}")
                all_responsive = False

        return all_responsive

    def test_production_paths(self):
        """Test different path resolution scenarios"""
        print("\n🛤️  Testing Production Path Resolution...")

        # Test from different page depths
        test_scenarios = [
            ("/", "./search/search_index.json"),
            ("/installation/", "../search/search_index.json"),
            ("/api/instruments/", "../../search/search_index.json"),
            ("/tutorials/10_minute_tour/", "../../search/search_index.json")
        ]

        results = {}
        for base_page, search_path in test_scenarios:
            try:
                # Get the base page first
                base_url = urljoin(self.base_url, base_page)
                base_response = requests.get(base_url, timeout=5)

                if base_response.status_code != 200:
                    print(f"  {base_page} -> {search_path}: ❌ Base page not accessible")
                    results[base_page] = False
                    continue

                # Test if the search index is accessible from this page's relative path
                # We need to resolve the relative path manually
                if search_path.startswith('./'):
                    # Same directory
                    resolved_path = base_page.rstrip('/') + '/' + search_path[2:]
                elif search_path.startswith('../'):
                    # Parent directory
                    parts = base_page.strip('/').split('/')
                    up_levels = search_path.count('../')
                    remaining_path = search_path.replace('../', '', up_levels)

                    if len(parts) >= up_levels:
                        new_parts = parts[:-up_levels] if up_levels > 0 else parts
                        resolved_path = '/' + '/'.join(new_parts) + '/' + remaining_path
                    else:
                        resolved_path = '/' + remaining_path
                else:
                    resolved_path = search_path

                # Clean up path
                resolved_path = resolved_path.replace('//', '/')

                search_url = urljoin(self.base_url, resolved_path)
                search_response = requests.get(search_url, timeout=5)

                status = "✅ ACCESSIBLE" if search_response.status_code == 200 else f"❌ FAIL ({search_response.status_code})"
                print(f"  {base_page} -> {search_path}: {status}")
                print(f"    Resolved to: {resolved_path}")

                results[base_page] = search_response.status_code == 200

            except Exception as e:
                print(f"  {base_page} -> {search_path}: ❌ ERROR - {e}")
                results[base_page] = False

        return all(results.values())

    def test_debug_page(self):
        """Test the debug page functionality"""
        print("\n🐛 Testing Debug Page...")

        try:
            debug_url = urljoin(self.base_url, "/debug_search.html")
            response = requests.get(debug_url, timeout=10)

            if response.status_code == 200:
                content = response.text

                # Check for debug page components
                has_env_info = 'Environment Information' in content
                has_search_test = 'Search Index Test' in content
                has_hamburger_test = 'Hamburger Menu Test' in content
                has_network_test = 'Network & CORS Test' in content
                has_javascript = '<script>' in content

                print(f"  Debug page accessible: ✅")
                print(f"  Environment info section: {'✅' if has_env_info else '❌'}")
                print(f"  Search test section: {'✅' if has_search_test else '❌'}")
                print(f"  Hamburger test section: {'✅' if has_hamburger_test else '❌'}")
                print(f"  Network test section: {'✅' if has_network_test else '❌'}")
                print(f"  JavaScript functionality: {'✅' if has_javascript else '❌'}")

                return all([has_env_info, has_search_test, has_hamburger_test, has_javascript])
            else:
                print(f"  Debug page: ❌ FAIL ({response.status_code})")
                return False

        except Exception as e:
            print(f"  Debug page: ❌ ERROR - {e}")
            return False

    def run_all_tests(self):
        """Run all production tests"""
        print("🚀 Simple Production-Equivalent Tests for PyTestLab Documentation")
        print("=" * 80)

        # Setup
        if not self.start_production_server():
            print("❌ Failed to start production server. Exiting.")
            return False

        # Run tests
        tests = [
            ("Basic Page Accessibility", self.test_basic_pages),
            ("Search Infrastructure", self.test_search_infrastructure),
            ("CSS and JS Assets", self.test_css_and_js_assets),
            ("Mobile Responsive Features", self.test_mobile_responsive_headers),
            ("Production Path Resolution", self.test_production_paths),
            ("Debug Page Functionality", self.test_debug_page),
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
                    print(f"✅ {test_name}: PASSED")
                else:
                    print(f"❌ {test_name}: FAILED")
            except Exception as e:
                print(f"❌ {test_name}: CRASHED - {e}")
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
            print("\n🎉 All tests passed! Production-equivalent environment is working correctly.")
            print(f"\n🌐 You can now test manually at: {self.base_url}")
            print("📱 Try the debug page: " + urljoin(self.base_url, "/debug_search.html"))
        else:
            print("\n⚠️  Some tests failed. Check the output above for details.")

        return passed == total

    def cleanup(self):
        """Cleanup resources"""
        if self.server_process:
            print("\n🧹 Stopping production server...")
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
                self.server_process.wait()
            print("✅ Server stopped")

    def keep_server_running(self):
        """Keep server running for manual testing"""
        if self.server_process:
            print(f"\n🚀 Server is running at: {self.base_url}")
            print("📱 Debug page: " + urljoin(self.base_url, "/debug_search.html"))
            print("\nPress Ctrl+C to stop the server...")

            try:
                while True:
                    if self.server_process.poll() is not None:
                        print("❌ Server process died unexpectedly")
                        break
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n⏹️  Stopping server...")
                self.cleanup()


def main():
    """Main entry point"""
    # Check if we're in the right directory
    if not os.path.exists("site"):
        print("❌ Error: 'site' directory not found.")
        print("   Please run from PyTestLab root directory after building docs with:")
        print("   python -m mkdocs build -f docs/mkdocs.yml")
        sys.exit(1)

    tester = SimpleProductionTester()

    try:
        # Check command line arguments
        if len(sys.argv) > 1 and sys.argv[1] == "--server-only":
            # Just start server and keep it running
            if tester.start_production_server():
                tester.keep_server_running()
            else:
                print("❌ Failed to start server")
                sys.exit(1)
        else:
            # Run tests
            success = tester.run_all_tests()

            if success:
                print("\n🔄 Server will continue running for manual testing...")
                print("   Use Ctrl+C to stop, or run with --server-only to skip tests")
                tester.keep_server_running()

            sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n⏹️  Interrupted by user")
        tester.cleanup()
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        tester.cleanup()
        sys.exit(1)


if __name__ == "__main__":
    main()
