"""
Destination -> candidate URL discovery.

Turns a bare destination name ("Jabalpur") into a ranked, filtered list of
URLs worth crawling, so the knowledge base can be built from a destination
instead of a hand-pasted URL list.

Discovery is deliberately separate from crawling: it only decides *what* to
fetch. The URLs it returns are fed back into the existing POST /scrape/urls
pipeline unchanged, so every page still goes through the same crawl4ai ->
semantic_parser -> chunker path (and the same robots.txt and rate-limit
settings) as a manually pasted URL.
"""
from src.discovery.service import DiscoveryError, discover

__all__ = ["discover", "DiscoveryError"]
