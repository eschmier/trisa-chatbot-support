"""Reads the help website and saves a ready-made copy (help_index.json).

Run by the "Refresh help index" button on GitHub (Actions tab). The app loads this file
at start-up instead of reading the whole website each time.

    HELP_SITE_URL=https://trisa.dev/en/sitemap.xml python build_index.py
"""
import os
import sys

import helpsite

root = os.environ.get("HELP_SITE_URL", "").strip()
if not root:
    sys.exit("HELP_SITE_URL is not set.")
sections, pages, problems = helpsite.load_help_site(root)
if not sections:
    sys.exit(f"Read {pages} pages but found no text. Not saving an empty copy.")
path = helpsite.save_snapshot(sections, pages, problems, root)
print(f"Saved {len(sections)} sections from {pages} pages to {path} ({len(problems)} pages had problems).")
