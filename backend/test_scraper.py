#!/usr/bin/env python3
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.scrapers import FlashscoreScraper

scraper = FlashscoreScraper()
df = scraper.scrape_match_results("Manchester United", "EPL")
print(df.head() if not df.empty else "Empty")
