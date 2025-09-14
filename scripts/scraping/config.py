"""
Configuration settings for Atlan documentation scraper
"""
import re
from typing import Dict, List, Tuple

# Target sites configuration
SITES = {
    "docs": {
        "base_url": "https://docs.atlan.com",
        "sitemap_url": "https://docs.atlan.com/sitemap.xml",
        "framework": "docusaurus",
        "content_selector": "article",
        "remove_selectors": [
            "nav", 
            ".theme-doc-toc-mobile", 
            ".theme-doc-toc-desktop", 
            ".pagination-nav", 
            "footer", 
            ".theme-doc-breadcrumbs", 
            ".theme-edit-this-page", 
            ".navbar", 
            ".docSidebarContainer"
        ],
        "code_block_selector": "div[class*='codeBlock']",
        "breadcrumb_selector": "nav[aria-label='Breadcrumbs']",
        "main_categories": ["Get started", "Connect data", "Use data", "Build governance", "Configure Atlan"]
    },
    "developer": {
        "base_url": "https://developer.atlan.com",
        "sitemap_url": "https://developer.atlan.com/sitemap.xml",
        "framework": "mkdocs",
        "content_selector": ".md-content article",
        "remove_selectors": [
            ".md-sidebar", 
            ".md-header", 
            ".md-footer", 
            ".md-top", 
            "nav.md-nav", 
            ".headerlink", 
            ".md-source", 
            ".md-search"
        ],
        "code_block_selector": ".highlight pre",
        "breadcrumb_selector": ".md-nav__list",
        "main_categories": ["Overview", "Getting started", "Common tasks", "Asset-specific", "Governance structures", "Reference"]
    }
}

# URL patterns to skip
SKIP_PATTERNS = [
    r'/tags/',
    r'/search/',
    r'/404',
    r'/changelog/',
    r'/blog/',
    r'/versions/',
    r'#[^/]*$',  # Skip anchors only
]

# Priority boost patterns for support ticket relevance
PRIORITY_BOOST_PATTERNS = {
    # Critical for support (boost by 0.3)
    "connectors/snowflake": 0.3,
    "connectors/tableau": 0.3,
    "authentication": 0.3,
    "sso": 0.3,
    "api/rest": 0.3,
    
    # Important (boost by 0.2)
    "lineage": 0.2,
    "glossary": 0.2,
    "permissions": 0.2,
    "governance": 0.2,
    
    # Standard (no boost)
    "concepts": 0.0,
    "overview": 0.0,
    
    # Low priority (reduce by 0.3)
    "changelog": -0.3,
    "deprecated": -0.3
}

# Crawl4AI configuration - optimized for speed
CRAWLER_CONFIG = {
    "use_browser": False,
    "respect_robots_txt": True,
    "max_concurrent": 15,  # Increased from 5 to 15
    "delay_between_requests": 0.2,  # Reduced from 0.5 to 0.2
    "timeout": 20,  # Reduced from 30 to 20
    "retry_count": 2,  # Reduced from 3 to 2
    "user_agent": "Mozilla/5.0 (compatible; AtlanDocsCrawler/1.0)",
    "headers": {
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9"
    }
}

# Chunking strategies
CHUNKING_STRATEGY = {
    "overview_pages": {
        "identifier": ["overview", "introduction", "getting-started"],
        "max_tokens": 1200,
        "split_markers": ["<h2>"],
        "preserve_first_section": True
    },
    "how_to_guides": {
        "identifier": ["how-to", "tutorial", "guide"],
        "max_tokens": 800,
        "split_markers": ["<h2>", "<h3>"],
        "keep_steps_together": True,
        "preserve_code_blocks": True
    },
    "api_reference": {
        "identifier": ["api", "endpoints", "reference"],
        "max_tokens": 500,
        "split_markers": ["<h3>", "<h4>"],
        "one_endpoint_per_chunk": True
    },
    "connector_docs": {
        "identifier": ["/connectors/"],
        "max_tokens": 800,
        "split_markers": ["<h2>"],
        "keep_prerequisites_together": True
    },
    "faq_pages": {
        "identifier": ["faq", "questions"],
        "max_tokens": 400,
        "split_by_qa_pairs": True
    }
}

# Token settings
CHUNK_OVERLAP = 100  # tokens
MIN_CHUNK_SIZE = 50  # minimum characters

# Output files
OUTPUT_FILE = "atlan_docs_chunks.jsonl"
STATS_FILE = "crawl_stats.json"
CHECKPOINT_FILE = "crawl_checkpoint.json"
LOG_FILE = "crawl.log"

# Progress tracking
CHECKPOINT_INTERVAL = 50  # Save checkpoint every N pages
PROGRESS_INTERVAL = 10   # Print progress every N pages