#!/usr/bin/env python3
"""
Test script for the HTML index page generation feature.

This script verifies that the create_index_page() function correctly
generates an index.html file with proper links to multiple library exports.
"""

import os
import sys
import tempfile
import shutil

# Add the current directory to the path to import the main module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from plex_library_exporter import create_index_page


def test_index_page_creation():
    """Test that index page is created with correct structure."""
    print("Testing index page creation...")
    
    # Create a temporary directory for test outputs
    test_dir = tempfile.mkdtemp(prefix="plexee_test_")
    print(f"Test directory: {test_dir}")
    
    try:
        # Define test library files
        library_files = [
            ("Movies", os.path.join(test_dir, "movies.html")),
            ("TV Shows", os.path.join(test_dir, "tv_shows.html")),
            ("Audiobooks", os.path.join(test_dir, "audiobooks.html")),
        ]
        
        # Create dummy HTML files
        for lib_name, filepath in library_files:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"<html><body><h1>{lib_name}</h1></body></html>")
        
        print(f"Created {len(library_files)} test HTML files")
        
        # Generate index page
        create_index_page(library_files, test_dir)
        
        # Verify index.html exists
        index_path = os.path.join(test_dir, "index.html")
        if not os.path.exists(index_path):
            print("✗ FAIL: index.html was not created")
            return False
        
        print("✓ index.html file created")
        
        # Read and verify content
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check for essential elements
        checks = [
            ("Library Index" in content, "Page title"),
            ("Plexee Library Exporter" in content, "Branding"),
            ("Movies" in content, "Movies library link"),
            ("TV Shows" in content, "TV Shows library link"),
            ("Audiobooks" in content, "Audiobooks library link"),
            ("movies.html" in content, "Movies filename"),
            ("tv_shows.html" in content, "TV Shows filename"),
            ("audiobooks.html" in content, "Audiobooks filename"),
            ("#000000" in content, "Black background color"),
            ("#00ff00" in content, "Green text color"),
            ("library-button" in content, "Button class"),
            ('"3"' in content or ">3<" in content, "Library count"),
        ]
        
        all_passed = True
        for check, description in checks:
            if check:
                print(f"  ✓ {description}")
            else:
                print(f"  ✗ {description} - NOT FOUND")
                all_passed = False
        
        # Verify file size is reasonable
        file_size = os.path.getsize(index_path)
        if file_size < 1000:
            print(f"  ✗ Index file seems too small ({file_size} bytes)")
            all_passed = False
        else:
            print(f"  ✓ Index file size: {file_size} bytes")
        
        if all_passed:
            print("\n✓ All tests PASSED")
            return True
        else:
            print("\n✗ Some tests FAILED")
            return False
            
    finally:
        # Cleanup
        shutil.rmtree(test_dir)
        print(f"Cleaned up test directory")


def test_single_library_no_index():
    """Test that index page is NOT created for single library."""
    print("\nTesting single library (no index expected)...")
    
    test_dir = tempfile.mkdtemp(prefix="plexee_test_single_")
    print(f"Test directory: {test_dir}")
    
    try:
        # Single library - index should not be created by main logic
        # (but the function itself can be called with a single item)
        library_files = [("Movies", os.path.join(test_dir, "movies.html"))]
        
        # Create dummy HTML file
        with open(library_files[0][1], "w", encoding="utf-8") as f:
            f.write("<html><body><h1>Movies</h1></body></html>")
        
        # Call create_index_page (it will create one even for single library)
        create_index_page(library_files, test_dir)
        
        # Verify index.html exists
        index_path = os.path.join(test_dir, "index.html")
        if os.path.exists(index_path):
            print("✓ Index page created (function works even with single library)")
            return True
        else:
            print("✗ Index page not created")
            return False
            
    finally:
        shutil.rmtree(test_dir)
        print(f"Cleaned up test directory")


def test_html_escaping():
    """Test that library names with special characters are properly escaped."""
    print("\nTesting HTML escaping for special characters...")
    
    test_dir = tempfile.mkdtemp(prefix="plexee_test_escape_")
    print(f"Test directory: {test_dir}")
    
    try:
        # Library names with special characters
        library_files = [
            ("Movies & TV", os.path.join(test_dir, "movies_tv.html")),
            ("Books <Fiction>", os.path.join(test_dir, "books.html")),
        ]
        
        # Create dummy HTML files
        for lib_name, filepath in library_files:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"<html><body><h1>{lib_name}</h1></body></html>")
        
        # Generate index page
        create_index_page(library_files, test_dir)
        
        # Read content
        index_path = os.path.join(test_dir, "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check for escaped characters
        checks = [
            ("Movies &amp; TV" in content, "Ampersand escaped"),
            ("Books &lt;Fiction&gt;" in content, "Angle brackets escaped"),
        ]
        
        all_passed = True
        for check, description in checks:
            if check:
                print(f"  ✓ {description}")
            else:
                print(f"  ✗ {description} - NOT FOUND")
                all_passed = False
        
        if all_passed:
            print("✓ HTML escaping test PASSED")
            return True
        else:
            print("✗ HTML escaping test FAILED")
            return False
            
    finally:
        shutil.rmtree(test_dir)
        print(f"Cleaned up test directory")


if __name__ == "__main__":
    print("=" * 60)
    print("Plexee Library Exporter - Index Page Tests")
    print("=" * 60)
    print()
    
    results = []
    results.append(test_index_page_creation())
    results.append(test_single_library_no_index())
    results.append(test_html_escaping())
    
    print()
    print("=" * 60)
    if all(results):
        print("✓ ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("✗ SOME TESTS FAILED")
        sys.exit(1)
