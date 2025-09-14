"""
Sitemap parsing and URL prioritization for Atlan documentation sites
"""
import re
import xml.etree.ElementTree as ET
from typing import List, Dict, Tuple, Optional
from urllib.parse import urlparse, urljoin
from datetime import datetime
import requests
import logging

from config import SITES, SKIP_PATTERNS, PRIORITY_BOOST_PATTERNS

logger = logging.getLogger(__name__)


class SitemapParser:
    """Parses sitemaps and prioritizes URLs for crawling"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; AtlanDocsCrawler/1.0)'
        })
    
    def fetch_sitemap(self, sitemap_url: str) -> str:
        """Fetch sitemap XML content"""
        try:
            response = self.session.get(sitemap_url, timeout=30)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"Failed to fetch sitemap {sitemap_url}: {e}")
            raise
    
    def parse_sitemap_xml(self, xml_content: str) -> List[Dict]:
        """Parse sitemap XML and extract URLs with metadata"""
        urls = []
        
        try:
            root = ET.fromstring(xml_content)
            
            # Handle namespace
            namespace = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            if root.tag.startswith('{'):
                namespace['ns'] = root.tag.split('}')[0][1:]
            
            # Extract URLs from <url> elements
            for url_elem in root.findall('.//ns:url', namespace):
                url_data = {}
                
                loc_elem = url_elem.find('ns:loc', namespace)
                if loc_elem is not None:
                    url_data['url'] = loc_elem.text.strip()
                else:
                    continue
                
                # Extract priority
                priority_elem = url_elem.find('ns:priority', namespace)
                if priority_elem is not None:
                    try:
                        url_data['priority'] = float(priority_elem.text.strip())
                    except (ValueError, AttributeError):
                        url_data['priority'] = 0.5
                else:
                    url_data['priority'] = 0.5
                
                # Extract last modified
                lastmod_elem = url_elem.find('ns:lastmod', namespace)
                if lastmod_elem is not None:
                    url_data['lastmod'] = lastmod_elem.text.strip()
                else:
                    url_data['lastmod'] = None
                
                # Extract change frequency
                changefreq_elem = url_elem.find('ns:changefreq', namespace)
                if changefreq_elem is not None:
                    url_data['changefreq'] = changefreq_elem.text.strip()
                else:
                    url_data['changefreq'] = None
                
                urls.append(url_data)
                
        except ET.ParseError as e:
            logger.error(f"Failed to parse sitemap XML: {e}")
            raise
        
        return urls
    
    def should_skip_url(self, url: str) -> bool:
        """Check if URL should be skipped based on patterns"""
        for pattern in SKIP_PATTERNS:
            if re.search(pattern, url):
                return True
        
        # Skip URLs that are just anchor links to sections on same page
        if '#' in url:
            # Keep URLs with meaningful anchors, skip fragment-only URLs
            base_url, fragment = url.split('#', 1)
            # Skip if the fragment is very short (likely just navigation)
            if len(fragment) < 3:
                return True
        
        return False
    
    def calculate_priority_score(self, url: str, base_priority: float) -> float:
        """Calculate priority score with boosts based on support ticket relevance"""
        score = base_priority
        
        # Apply priority boosts
        for pattern, boost in PRIORITY_BOOST_PATTERNS.items():
            if pattern in url.lower():
                score += boost
                logger.debug(f"Applied boost {boost} for pattern '{pattern}' to {url}")
        
        # Ensure score stays within bounds
        return max(0.0, min(1.0, score))
    
    def extract_url_features(self, url: str, site_key: str) -> Dict:
        """Extract features from URL for classification"""
        features = {
            'site': site_key,
            'is_connector_doc': '/connectors/' in url,
            'is_api_doc': '/api/' in url or '/endpoints/' in url,
            'is_overview': any(x in url.lower() for x in ['overview', 'introduction', 'getting-started']),
            'is_quickstart': 'quickstart' in url.lower(),
            'nav_depth': len([x for x in url.split('/') if x]) - 2,  # Subtract domain and empty
        }
        
        # URL pattern classification
        if site_key == 'docs':
            if '/apps/connectors/' in url:
                parts = url.split('/apps/connectors/')
                if len(parts) > 1:
                    connector_parts = parts[1].split('/')
                    if len(connector_parts) >= 2:
                        features['connector_type'] = connector_parts[0]
                        features['connector_name'] = connector_parts[1]
            
            elif '/product/capabilities/' in url:
                features['feature_area'] = url.split('/product/capabilities/')[-1].split('/')[0]
            
            elif '/platform/' in url:
                features['platform_area'] = url.split('/platform/')[-1].split('/')[0]
        
        elif site_key == 'developer':
            if '/sdk/' in url:
                sdk_parts = url.split('/sdk/')
                if len(sdk_parts) > 1:
                    features['sdk_language'] = sdk_parts[1].split('/')[0]
            
            elif '/recipes/' in url:
                features['recipe_task'] = url.split('/recipes/')[-1].split('/')[0]
            
            elif '/types/' in url:
                type_parts = url.split('/types/')
                if len(type_parts) > 1:
                    parts = type_parts[1].split('/')
                    if len(parts) >= 2:
                        features['type_category'] = parts[0]
                        features['type_name'] = parts[1]
            
            elif '/endpoints/' in url:
                features['is_api_endpoint'] = True
        
        return features
    
    def parse_all_sitemaps(self) -> List[Dict]:
        """Parse sitemaps from both sites and return prioritized URLs"""
        all_urls = []
        
        for site_key, site_config in SITES.items():
            logger.info(f"Parsing sitemap for {site_key}: {site_config['sitemap_url']}")
            
            try:
                # Fetch and parse sitemap
                xml_content = self.fetch_sitemap(site_config['sitemap_url'])
                urls = self.parse_sitemap_xml(xml_content)
                
                logger.info(f"Found {len(urls)} URLs in {site_key} sitemap")
                
                # Process each URL
                for url_data in urls:
                    url = url_data['url']
                    
                    # Skip unwanted URLs
                    if self.should_skip_url(url):
                        logger.debug(f"Skipping URL: {url}")
                        continue
                    
                    # Calculate priority score
                    base_priority = url_data.get('priority', 0.5)
                    priority_score = self.calculate_priority_score(url, base_priority)
                    
                    # Extract URL features
                    features = self.extract_url_features(url, site_key)
                    
                    # Create enhanced URL data
                    enhanced_url_data = {
                        **url_data,
                        'priority_score': priority_score,
                        'site': site_key,
                        'features': features
                    }
                    
                    all_urls.append(enhanced_url_data)
                
            except Exception as e:
                logger.error(f"Failed to process sitemap for {site_key}: {e}")
                continue
        
        # Sort by priority score (highest first)
        all_urls.sort(key=lambda x: x['priority_score'], reverse=True)
        
        logger.info(f"Total URLs after filtering and prioritization: {len(all_urls)}")
        
        return all_urls
    
    def get_priority_urls(self, all_urls: List[Dict], top_n: int = 100) -> List[Dict]:
        """Get top priority URLs for initial crawling"""
        priority_urls = all_urls[:top_n]
        logger.info(f"Selected top {len(priority_urls)} priority URLs")
        
        # Log some statistics
        priority_breakdown = {}
        for url_data in priority_urls:
            site = url_data['site']
            priority_breakdown[site] = priority_breakdown.get(site, 0) + 1
        
        logger.info(f"Priority URLs breakdown: {priority_breakdown}")
        
        return priority_urls
    
    def save_url_list(self, urls: List[Dict], filename: str):
        """Save URL list to file for debugging"""
        import json
        with open(filename, 'w') as f:
            json.dump(urls, f, indent=2, default=str)
        logger.info(f"Saved {len(urls)} URLs to {filename}")


if __name__ == "__main__":
    # Test the sitemap parser
    logging.basicConfig(level=logging.INFO)
    
    parser = SitemapParser()
    all_urls = parser.parse_all_sitemaps()
    
    print(f"Total URLs: {len(all_urls)}")
    
    # Show top 10 priority URLs
    top_urls = parser.get_priority_urls(all_urls, 10)
    print("\nTop 10 Priority URLs:")
    for i, url_data in enumerate(top_urls, 1):
        print(f"{i:2d}. {url_data['priority_score']:.3f} - {url_data['url']}")
    
    # Save all URLs for inspection
    parser.save_url_list(all_urls, "all_urls.json")