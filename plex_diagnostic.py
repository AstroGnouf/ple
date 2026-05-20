#!/usr/bin/env python3
"""
Plex API Connection Diagnostic Tool

This script helps diagnose authentication and connection issues with Plex Media Server.
It performs a series of tests and provides specific recommendations based on the results.

Usage:
    python plex_diagnostic.py

Author: Plex Troubleshooting Tool
Version: 1.0
"""

import sys
import re
import socket
import urllib.parse
from typing import Tuple, Dict, List, Optional
import time

try:
    import requests
    from requests.exceptions import RequestException, ConnectionError, Timeout, SSLError
except ImportError:
    print("ERROR: 'requests' library not found.")
    print("Install it with: pip install requests")
    sys.exit(1)


class Colors:
    """ANSI color codes for terminal output"""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


class PlexDiagnostic:
    """Main diagnostic class for testing Plex API connections"""
    
    def __init__(self, hostname: str, port: int, token: str):
        self.hostname = hostname
        self.port = port
        self.token = token
        self.results = []
        self.issues = []
        self.recommendations = []
        
    def print_header(self, text: str):
        """Print a formatted header"""
        print(f"\n{Colors.HEADER}{Colors.BOLD}{'=' * 70}{Colors.ENDC}")
        print(f"{Colors.HEADER}{Colors.BOLD}{text.center(70)}{Colors.ENDC}")
        print(f"{Colors.HEADER}{Colors.BOLD}{'=' * 70}{Colors.ENDC}\n")
    
    def print_test(self, name: str):
        """Print test name"""
        print(f"{Colors.OKCYAN}{Colors.BOLD}[TEST]{Colors.ENDC} {name}")
    
    def print_success(self, message: str):
        """Print success message"""
        print(f"{Colors.OKGREEN}✓ {message}{Colors.ENDC}")
        self.results.append(('success', message))
    
    def print_warning(self, message: str):
        """Print warning message"""
        print(f"{Colors.WARNING}⚠ {message}{Colors.ENDC}")
        self.results.append(('warning', message))
    
    def print_error(self, message: str):
        """Print error message"""
        print(f"{Colors.FAIL}✗ {message}{Colors.ENDC}")
        self.results.append(('error', message))
        
    def print_info(self, message: str):
        """Print info message"""
        print(f"{Colors.OKBLUE}ℹ {message}{Colors.ENDC}")
    
    def add_issue(self, issue: str):
        """Add an issue to the list"""
        self.issues.append(issue)
    
    def add_recommendation(self, recommendation: str):
        """Add a recommendation to the list"""
        self.recommendations.append(recommendation)
    
    def validate_token_format(self) -> Tuple[bool, str]:
        """
        Validate the token format
        Returns: (is_valid, message)
        """
        if not self.token:
            return False, "Token is empty"
        
        # Check length
        if len(self.token) < 15:
            return False, f"Token too short ({len(self.token)} chars). Expected ~20 characters"
        
        if len(self.token) > 30:
            return False, f"Token too long ({len(self.token)} chars). Expected ~20 characters"
        
        # Check for invalid characters
        if not re.match(r'^[a-zA-Z0-9]+$', self.token):
            invalid_chars = set(re.findall(r'[^a-zA-Z0-9]', self.token))
            return False, f"Token contains invalid characters: {', '.join(invalid_chars)}"
        
        # Check for common mistakes
        if self.token.startswith('"') or self.token.endswith('"'):
            return False, "Token contains quotation marks - remove them"
        
        if ' ' in self.token:
            return False, "Token contains spaces"
        
        # Check for mix of letters and numbers
        has_letter = re.search(r'[a-zA-Z]', self.token)
        has_number = re.search(r'[0-9]', self.token)
        
        if not (has_letter and has_number):
            return False, "Token should contain both letters and numbers"
        
        return True, f"Token format looks valid ({len(self.token)} characters, alphanumeric)"
    
    def test_token_format(self):
        """Test 1: Validate token format"""
        self.print_test("Token Format Validation")
        
        is_valid, message = self.validate_token_format()
        
        if is_valid:
            self.print_success(message)
        else:
            self.print_error(message)
            self.add_issue("Token format is invalid")
            self.add_recommendation("Re-obtain your Plex token. See the troubleshooting guide for methods.")
            self.add_recommendation("Check for extra spaces, quotation marks, or special characters.")
    
    def test_hostname_resolution(self) -> bool:
        """Test 2: Check if hostname can be resolved"""
        self.print_test("Hostname Resolution")
        
        try:
            ip_address = socket.gethostbyname(self.hostname)
            self.print_success(f"Hostname '{self.hostname}' resolved to {ip_address}")
            
            # Check if it's a local IP
            if ip_address.startswith(('192.168.', '10.', '172.')) or ip_address == '127.0.0.1':
                self.print_info(f"This is a local network address ({ip_address})")
            else:
                self.print_info(f"This is a public/external IP address ({ip_address})")
            
            return True
            
        except socket.gaierror:
            self.print_error(f"Cannot resolve hostname '{self.hostname}'")
            self.add_issue("Hostname resolution failed")
            self.add_recommendation(f"Check if '{self.hostname}' is the correct server address.")
            self.add_recommendation("Try using the IP address directly instead of hostname.")
            return False
    
    def test_tcp_connectivity(self) -> bool:
        """Test 3: Check if we can connect to the port"""
        self.print_test(f"TCP Connectivity to {self.hostname}:{self.port}")
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        
        try:
            result = sock.connect_ex((self.hostname, self.port))
            sock.close()
            
            if result == 0:
                self.print_success(f"Successfully connected to {self.hostname}:{self.port}")
                return True
            else:
                self.print_error(f"Cannot connect to {self.hostname}:{self.port} (Error code: {result})")
                self.add_issue("TCP connection failed")
                self.add_recommendation("Check if Plex Media Server is running.")
                self.add_recommendation(f"Verify that port {self.port} is correct (default is 32400).")
                self.add_recommendation("Check firewall rules on both client and server.")
                return False
                
        except socket.timeout:
            self.print_error(f"Connection timeout to {self.hostname}:{self.port}")
            self.add_issue("Connection timeout")
            self.add_recommendation("Server may be unreachable. Check network connectivity.")
            self.add_recommendation("If connecting remotely, check router port forwarding.")
            return False
        except Exception as e:
            self.print_error(f"Connection error: {e}")
            self.add_issue("Connection error")
            return False
    
    def test_http_connection(self, use_https: bool = False) -> Tuple[bool, Optional[requests.Response]]:
        """
        Test HTTP/HTTPS connection to Plex server
        Returns: (success, response)
        """
        protocol = "https" if use_https else "http"
        url = f"{protocol}://{self.hostname}:{self.port}/identity"
        
        # Show the URL being tested
        self.print_test(f"{protocol.upper()} Connection Test")
        print(f"  URL: {url}")
        print(f"  Token: {self.token[:4]}...{self.token[-4:]} ({len(self.token)} chars)")
        
        # Test with query parameter
        print(f"\n  {Colors.BOLD}Method 1: Query Parameter{Colors.ENDC}")
        url_with_token = f"{url}?X-Plex-Token={self.token}"
        print(f"  Full URL: {url_with_token[:50]}...?X-Plex-Token=***")
        
        try:
            response = requests.get(url_with_token, timeout=10, verify=False)
            
            print(f"\n  {Colors.BOLD}HTTP Response:{Colors.ENDC}")
            print(f"    Status Code: {response.status_code}")
            print(f"    Reason: {response.reason}")
            print(f"    Content-Type: {response.headers.get('Content-Type', 'N/A')}")
            print(f"    Content-Length: {len(response.content)} bytes")
            
            if response.status_code == 200:
                self.print_success(f"{protocol.upper()} connection successful!")
                
                # Try to parse server info
                if 'xml' in response.headers.get('Content-Type', ''):
                    print(f"\n  {Colors.BOLD}Response Content (first 500 chars):{Colors.ENDC}")
                    print(f"    {response.text[:500]}")
                    
                    # Extract server info
                    if 'machineIdentifier' in response.text:
                        match = re.search(r'machineIdentifier="([^"]+)"', response.text)
                        if match:
                            print(f"\n  {Colors.OKGREEN}Server Machine ID: {match.group(1)}{Colors.ENDC}")
                    
                    if 'version' in response.text:
                        match = re.search(r'version="([^"]+)"', response.text)
                        if match:
                            print(f"  {Colors.OKGREEN}Server Version: {match.group(1)}{Colors.ENDC}")
                
                return True, response
                
            elif response.status_code == 401:
                self.print_error("Unauthorized (401) - Token was rejected")
                print(f"\n  {Colors.BOLD}Response Content:{Colors.ENDC}")
                print(f"    {response.text[:500]}")
                
                self.add_issue(f"Authentication failed with {protocol.upper()}")
                self.add_recommendation("Token is being sent but server rejected it.")
                self.add_recommendation("Generate a new token - your current one may be expired or invalid.")
                self.add_recommendation("If you recently changed your Plex password, all old tokens are invalidated.")
                
                return False, response
                
            else:
                self.print_error(f"Unexpected status code: {response.status_code}")
                print(f"\n  {Colors.BOLD}Response Content:{Colors.ENDC}")
                print(f"    {response.text[:500]}")
                
                return False, response
                
        except SSLError as e:
            self.print_error(f"SSL/Certificate error: {e}")
            self.add_issue(f"SSL certificate error with {protocol.upper()}")
            self.add_recommendation("Server may be using self-signed certificate.")
            self.add_recommendation("Try HTTP instead of HTTPS (if allowed by server settings).")
            return False, None
            
        except ConnectionError as e:
            self.print_error(f"Connection error: {e}")
            self.add_issue(f"Cannot connect via {protocol.upper()}")
            return False, None
            
        except Timeout:
            self.print_error("Request timeout")
            self.add_issue(f"{protocol.upper()} request timeout")
            self.add_recommendation("Server is not responding. Check if Plex is running.")
            return False, None
            
        except Exception as e:
            self.print_error(f"Unexpected error: {e}")
            self.add_issue(f"Error with {protocol.upper()} connection")
            return False, None
    
    def test_library_access(self, use_https: bool = False) -> bool:
        """Test access to library sections endpoint"""
        protocol = "https" if use_https else "http"
        url = f"{protocol}://{self.hostname}:{self.port}/library/sections"
        
        self.print_test(f"Library Access Test ({protocol.upper()})")
        print(f"  URL: {url}")
        
        try:
            response = requests.get(
                url,
                params={"X-Plex-Token": self.token},
                timeout=10,
                verify=False
            )
            
            print(f"\n  {Colors.BOLD}HTTP Response:{Colors.ENDC}")
            print(f"    Status Code: {response.status_code}")
            
            if response.status_code == 200:
                self.print_success("Successfully accessed library sections!")
                
                # Parse library sections
                if 'xml' in response.headers.get('Content-Type', ''):
                    # Count sections
                    section_count = response.text.count('<Directory')
                    print(f"\n  {Colors.OKGREEN}Found {section_count} library section(s){Colors.ENDC}")
                    
                    # Extract section titles
                    titles = re.findall(r'title="([^"]+)"', response.text)
                    if titles:
                        print(f"\n  {Colors.BOLD}Libraries:{Colors.ENDC}")
                        for i, title in enumerate(titles[:10], 1):  # Show first 10
                            print(f"    {i}. {title}")
                
                return True
                
            elif response.status_code == 401:
                self.print_error("Unauthorized - Cannot access library sections")
                self.add_issue("Cannot access library sections")
                return False
            else:
                self.print_error(f"Unexpected status code: {response.status_code}")
                return False
                
        except Exception as e:
            self.print_error(f"Error accessing library: {e}")
            return False
    
    def test_plex_tv_token(self) -> bool:
        """Test if token is valid on plex.tv"""
        self.print_test("Plex.tv Token Validation")
        
        url = "https://plex.tv/api/v2/resources"
        print(f"  URL: {url}")
        print(f"  Testing if token is valid on Plex.tv...")
        
        try:
            response = requests.get(
                url,
                params={"X-Plex-Token": self.token},
                timeout=10
            )
            
            print(f"\n  {Colors.BOLD}HTTP Response:{Colors.ENDC}")
            print(f"    Status Code: {response.status_code}")
            
            if response.status_code == 200:
                self.print_success("Token is valid on Plex.tv!")
                
                # Parse resources
                try:
                    import json
                    resources = json.loads(response.text)
                    
                    if isinstance(resources, list):
                        server_count = len([r for r in resources if r.get('provides') == 'server'])
                        print(f"\n  {Colors.OKGREEN}Found {server_count} Plex server(s) in your account{Colors.ENDC}")
                        
                        # Show server names
                        print(f"\n  {Colors.BOLD}Your Plex Servers:{Colors.ENDC}")
                        for resource in resources:
                            if resource.get('provides') == 'server':
                                name = resource.get('name', 'Unknown')
                                connections = resource.get('connections', [])
                                print(f"    • {name}")
                                if connections:
                                    for conn in connections[:2]:  # Show first 2 connections
                                        print(f"      - {conn.get('uri', 'N/A')}")
                
                except:
                    pass  # JSON parsing failed, but token is still valid
                
                return True
                
            elif response.status_code == 401:
                self.print_error("Token is INVALID on Plex.tv")
                self.add_issue("Token rejected by Plex.tv")
                self.add_recommendation("Token is fundamentally invalid or expired.")
                self.add_recommendation("Generate a completely new token using the troubleshooting guide.")
                return False
            else:
                self.print_warning(f"Unexpected status code: {response.status_code}")
                return False
                
        except Exception as e:
            self.print_error(f"Error validating token on Plex.tv: {e}")
            self.add_issue("Cannot validate token on Plex.tv")
            self.add_recommendation("Check your internet connection.")
            return False
    
    def run_diagnostics(self):
        """Run all diagnostic tests"""
        self.print_header("PLEX API CONNECTION DIAGNOSTICS")
        
        print(f"{Colors.BOLD}Configuration:{Colors.ENDC}")
        print(f"  Hostname: {self.hostname}")
        print(f"  Port: {self.port}")
        print(f"  Token: {self.token[:4]}...{self.token[-4:]} ({len(self.token)} characters)")
        
        print(f"\n{Colors.BOLD}Running diagnostic tests...{Colors.ENDC}\n")
        
        # Test 1: Token format
        self.test_token_format()
        print()
        
        # Test 2: Hostname resolution
        hostname_ok = self.test_hostname_resolution()
        print()
        
        # Test 3: TCP connectivity
        if hostname_ok:
            tcp_ok = self.test_tcp_connectivity()
            print()
        else:
            tcp_ok = False
            self.print_warning("Skipping TCP test due to hostname resolution failure")
            print()
        
        # Test 4: Plex.tv token validation
        plextv_ok = self.test_plex_tv_token()
        print()
        
        # Test 5: HTTP connection
        if tcp_ok:
            http_ok, http_response = self.test_http_connection(use_https=False)
            print()
            
            # Test 6: HTTPS connection
            https_ok, https_response = self.test_http_connection(use_https=True)
            print()
            
            # Test 7: Library access
            if http_ok:
                self.test_library_access(use_https=False)
            elif https_ok:
                self.test_library_access(use_https=True)
            else:
                self.print_warning("Skipping library access test due to connection failures")
            print()
            
        else:
            self.print_warning("Skipping HTTP/HTTPS tests due to TCP connection failure")
            print()
        
        # Summary
        self.print_summary()
    
    def print_summary(self):
        """Print diagnostic summary and recommendations"""
        self.print_header("DIAGNOSTIC SUMMARY")
        
        # Count results
        success_count = sum(1 for r in self.results if r[0] == 'success')
        warning_count = sum(1 for r in self.results if r[0] == 'warning')
        error_count = sum(1 for r in self.results if r[0] == 'error')
        
        print(f"{Colors.BOLD}Test Results:{Colors.ENDC}")
        print(f"  {Colors.OKGREEN}✓ Passed: {success_count}{Colors.ENDC}")
        print(f"  {Colors.WARNING}⚠ Warnings: {warning_count}{Colors.ENDC}")
        print(f"  {Colors.FAIL}✗ Failed: {error_count}{Colors.ENDC}")
        
        # Issues found
        if self.issues:
            print(f"\n{Colors.BOLD}{Colors.FAIL}Issues Found:{Colors.ENDC}")
            for i, issue in enumerate(self.issues, 1):
                print(f"  {i}. {issue}")
        
        # Recommendations
        if self.recommendations:
            print(f"\n{Colors.BOLD}{Colors.WARNING}Recommendations:{Colors.ENDC}")
            for i, rec in enumerate(self.recommendations, 1):
                print(f"  {i}. {rec}")
        
        # Overall status
        print(f"\n{Colors.BOLD}Overall Status:{Colors.ENDC}")
        if error_count == 0:
            print(f"{Colors.OKGREEN}✓ Connection looks good! Your Plex API should work.{Colors.ENDC}")
        elif error_count <= 2:
            print(f"{Colors.WARNING}⚠ Some issues detected. Follow the recommendations above.{Colors.ENDC}")
        else:
            print(f"{Colors.FAIL}✗ Multiple issues detected. Start with the first recommendation.{Colors.ENDC}")
        
        # Next steps
        print(f"\n{Colors.BOLD}Next Steps:{Colors.ENDC}")
        
        if error_count == 0:
            print(f"  1. Your configuration should work in your application")
            print(f"  2. Use these exact values: {self.hostname}:{self.port}")
            print(f"  3. If it still doesn't work, check application logs for details")
        else:
            print(f"  1. Address the issues listed above in order")
            print(f"  2. Refer to the troubleshooting guide for detailed instructions")
            print(f"  3. Re-run this diagnostic after making changes")
            print(f"  4. If problems persist, check Plex server logs")
        
        print(f"\n{Colors.BOLD}Additional Resources:{Colors.ENDC}")
        print(f"  • Troubleshooting Guide: /home/ubuntu/plex_troubleshooting_guide.md")
        print(f"  • Plex Support: https://support.plex.tv")
        print(f"  • Finding Plex Token: https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/")
        
        print(f"\n{Colors.HEADER}{'=' * 70}{Colors.ENDC}\n")


def get_user_input() -> Tuple[str, int, str]:
    """Get connection parameters from user"""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'=' * 70}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'PLEX API DIAGNOSTIC TOOL'.center(70)}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'=' * 70}{Colors.ENDC}\n")
    
    print("This tool will help diagnose Plex API authentication issues.")
    print("Please provide your Plex server connection details.\n")
    
    # Get hostname
    print(f"{Colors.BOLD}1. Server Hostname or IP Address{Colors.ENDC}")
    print("   Examples: 192.168.1.100, localhost, plex.example.com")
    hostname = input("   Enter hostname: ").strip()
    
    if not hostname:
        print(f"{Colors.FAIL}Error: Hostname cannot be empty{Colors.ENDC}")
        sys.exit(1)
    
    # Get port
    print(f"\n{Colors.BOLD}2. Server Port{Colors.ENDC}")
    print("   Default: 32400")
    port_input = input("   Enter port [32400]: ").strip()
    
    if not port_input:
        port = 32400
    else:
        try:
            port = int(port_input)
            if port < 1 or port > 65535:
                print(f"{Colors.FAIL}Error: Port must be between 1 and 65535{Colors.ENDC}")
                sys.exit(1)
        except ValueError:
            print(f"{Colors.FAIL}Error: Port must be a number{Colors.ENDC}")
            sys.exit(1)
    
    # Get token
    print(f"\n{Colors.BOLD}3. Plex Authentication Token{Colors.ENDC}")
    print("   See troubleshooting guide for how to obtain your token")
    token = input("   Enter token: ").strip()
    
    if not token:
        print(f"{Colors.FAIL}Error: Token cannot be empty{Colors.ENDC}")
        sys.exit(1)
    
    # Remove quotes if user included them
    if token.startswith('"') and token.endswith('"'):
        token = token[1:-1]
        print(f"{Colors.WARNING}   Note: Removed quotation marks from token{Colors.ENDC}")
    
    return hostname, port, token


def main():
    """Main entry point"""
    # Suppress SSL warnings
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except:
        pass
    
    # Check if running with arguments
    if len(sys.argv) == 4:
        hostname = sys.argv[1]
        port = int(sys.argv[2])
        token = sys.argv[3]
        print(f"\n{Colors.OKBLUE}Using command-line arguments{Colors.ENDC}")
    else:
        # Interactive mode
        hostname, port, token = get_user_input()
    
    print(f"\n{Colors.OKBLUE}Starting diagnostics...{Colors.ENDC}\n")
    time.sleep(1)
    
    # Run diagnostics
    diagnostic = PlexDiagnostic(hostname, port, token)
    diagnostic.run_diagnostics()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{Colors.WARNING}Diagnostic cancelled by user{Colors.ENDC}\n")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Colors.FAIL}Unexpected error: {e}{Colors.ENDC}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
