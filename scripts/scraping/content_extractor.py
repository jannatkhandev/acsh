"""
Content extraction logic for both Docusaurus and MkDocs documentation frameworks
"""
import re
import logging
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup, Tag, NavigableString
import html2text
from markdownify import markdownify as md

from config import SITES

logger = logging.getLogger(__name__)


class ContentExtractor:
    """Extracts clean content from documentation pages"""
    
    def __init__(self, site_key: str):
        self.site_key = site_key
        self.site_config = SITES[site_key]
        self.html2text_converter = html2text.HTML2Text()
        self.html2text_converter.ignore_links = False
        self.html2text_converter.ignore_images = True
        self.html2text_converter.body_width = 0  # Don't wrap lines
    
    def extract_page_content(self, html_content: str, url: str) -> Dict:
        """Extract all relevant content from a documentation page"""
        soup = BeautifulSoup(html_content, 'lxml')
        
        # Remove unwanted elements
        self._remove_unwanted_elements(soup)
        
        # Extract main content
        main_content = self._extract_main_content(soup)
        if not main_content:
            logger.warning(f"No main content found for {url}")
            return None
        
        # Extract various components
        result = {
            'url': url,
            'title': self._extract_title(soup),
            'breadcrumbs': self._extract_breadcrumbs(soup),
            'content': self._clean_content_text(main_content),
            'raw_html': str(main_content),
            'headings': self._extract_headings(main_content),
            'code_blocks': self._extract_code_blocks(main_content),
            'tables': self._extract_tables(main_content),
            'links': self._extract_links(main_content, url),
            'tags': self._extract_tags(soup),
            'meta_description': self._extract_meta_description(soup),
            'structured_content': self._extract_structured_content(main_content)
        }
        
        return result
    
    def _remove_unwanted_elements(self, soup: BeautifulSoup):
        """Remove navigation, sidebars, and other unwanted elements"""
        selectors_to_remove = self.site_config['remove_selectors']
        
        for selector in selectors_to_remove:
            elements = soup.select(selector)
            for element in elements:
                element.decompose()
        
        # Additional cleanup for common unwanted elements - but preserve main content
        unwanted_classes = [
            'sidebar', 'navigation', 'footer', 'header',
            'toc', 'table-of-contents', 'edit-page', 'feedback',
            'advertisement', 'social-share', 'comment'
        ]
        
        for class_name in unwanted_classes:
            elements = soup.find_all(class_=re.compile(class_name, re.I))
            for element in elements:
                # Don't remove if it's our main content container
                if element.name not in ['article', 'main'] and not element.find('article'):
                    element.decompose()
    
    def _extract_main_content(self, soup: BeautifulSoup) -> Optional[Tag]:
        """Extract the main content area"""
        content_selector = self.site_config['content_selector']
        main_content = soup.select_one(content_selector)
        
        if not main_content:
            # Enhanced fallback selectors for different documentation frameworks
            if self.site_key == 'docs':
                # Docusaurus-specific selectors
                fallback_selectors = [
                    'article',
                    '.theme-doc-markdown',
                    '[class*="docusaurus"]',
                    'main article',
                    '.main-wrapper article',
                    'main',
                    '.content',
                    '#content'
                ]
            else:
                # MkDocs Material fallbacks
                fallback_selectors = [
                    '.md-content article',
                    '.md-content',
                    'article',
                    'main',
                    '.content',
                    '#content'
                ]
            
            for selector in fallback_selectors:
                main_content = soup.select_one(selector)
                if main_content:
                    logger.debug(f"Found content using fallback selector: {selector}")
                    break
        
        return main_content
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract page title"""
        # Try h1 first
        h1 = soup.find('h1')
        if h1:
            return h1.get_text(strip=True)
        
        # Fallback to title tag
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text(strip=True)
            # Remove site name suffix
            if ' | ' in title:
                title = title.split(' | ')[0]
            return title
        
        return "Untitled"
    
    def _extract_breadcrumbs(self, soup: BeautifulSoup) -> List[str]:
        """Extract breadcrumb navigation"""
        breadcrumbs = []
        
        if self.site_key == 'docs':
            # Docusaurus breadcrumbs
            breadcrumb_nav = soup.select_one("nav[aria-label='Breadcrumbs']")
            if breadcrumb_nav:
                links = breadcrumb_nav.find_all(['a', 'span'])
                breadcrumbs = [link.get_text(strip=True) for link in links if link.get_text(strip=True)]
        
        elif self.site_key == 'developer':
            # MkDocs Material breadcrumbs
            breadcrumb_elements = soup.select('.md-nav__item .md-nav__link')
            if breadcrumb_elements:
                breadcrumbs = [elem.get_text(strip=True) for elem in breadcrumb_elements]
            
            # Alternative: look for structured data
            if not breadcrumbs:
                breadcrumb_list = soup.find('ol', {'itemtype': 'https://schema.org/BreadcrumbList'})
                if breadcrumb_list:
                    items = breadcrumb_list.find_all('span', {'itemprop': 'name'})
                    breadcrumbs = [item.get_text(strip=True) for item in items]
        
        return breadcrumbs
    
    def _clean_content_text(self, content_elem: Tag) -> str:
        """Convert HTML content to clean text"""
        # Use html2text for better formatting preservation
        html_str = str(content_elem)
        text = self.html2text_converter.handle(html_str)
        
        # Clean up extra whitespace
        text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
        
        return text.strip()
    
    def _extract_headings(self, content_elem: Tag) -> List[Dict]:
        """Extract all headings with hierarchy"""
        headings = []
        
        for i, heading in enumerate(content_elem.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])):
            level = int(heading.name[1])
            text = heading.get_text(strip=True)
            
            # Extract anchor/id for linking
            anchor = heading.get('id') or heading.get('data-id')
            if not anchor and heading.find('a'):
                anchor_link = heading.find('a')
                if anchor_link:
                    href = anchor_link.get('href', '')
                    if href.startswith('#'):
                        anchor = href[1:]
            
            headings.append({
                'level': level,
                'text': text,
                'anchor': anchor,
                'position': i
            })
        
        return headings
    
    def _extract_code_blocks(self, content_elem: Tag) -> List[Dict]:
        """Extract code blocks with language information"""
        code_blocks = []
        
        if self.site_key == 'docs':
            # Docusaurus code blocks
            code_elements = content_elem.select("div[class*='codeBlock']")
            for code_elem in code_elements:
                code_content = code_elem.find('code')
                if code_content:
                    # Extract language from class
                    language = self._extract_language_from_classes(code_content.get('class', []))
                    code_text = code_content.get_text()
                    
                    code_blocks.append({
                        'language': language,
                        'code': code_text,
                        'has_copy_button': bool(code_elem.select('.copyButton'))
                    })
        
        elif self.site_key == 'developer':
            # MkDocs Material code blocks
            code_elements = content_elem.select('.highlight pre')
            for code_elem in code_elements:
                code_content = code_elem.find('code')
                if code_content:
                    # Language might be in parent div class
                    parent = code_elem.parent
                    language = None
                    if parent and parent.get('class'):
                        language = self._extract_language_from_classes(parent.get('class', []))
                    
                    if not language:
                        language = self._extract_language_from_classes(code_content.get('class', []))
                    
                    code_text = code_content.get_text()
                    
                    code_blocks.append({
                        'language': language,
                        'code': code_text,
                        'has_copy_button': bool(code_elem.find_parent().select('.md-clipboard'))
                    })
        
        # Also catch inline code and generic <pre> blocks
        for pre in content_elem.find_all('pre'):
            if not any(cb['code'] == pre.get_text() for cb in code_blocks):
                code_blocks.append({
                    'language': 'text',
                    'code': pre.get_text(),
                    'has_copy_button': False
                })
        
        return code_blocks
    
    def _extract_language_from_classes(self, classes: List[str]) -> str:
        """Extract programming language from CSS classes"""
        if not classes:
            return 'text'
        
        for cls in classes:
            if cls.startswith('language-'):
                return cls.replace('language-', '')
            elif cls.startswith('highlight-'):
                return cls.replace('highlight-', '')
            elif cls in ['python', 'javascript', 'java', 'sql', 'bash', 'json', 'yaml', 'xml', 'css', 'html']:
                return cls
        
        return 'text'
    
    def _extract_tables(self, content_elem: Tag) -> List[Dict]:
        """Extract tables and convert to markdown"""
        tables = []
        
        for table in content_elem.find_all('table'):
            # Convert table to markdown
            table_md = md(str(table), strip=['a'])
            
            # Extract table metadata
            rows = table.find_all('tr')
            headers = []
            if rows:
                header_row = rows[0]
                headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
            
            tables.append({
                'markdown': table_md,
                'headers': headers,
                'row_count': len(rows),
                'column_count': len(headers)
            })
        
        return tables
    
    def _extract_links(self, content_elem: Tag, base_url: str) -> List[Dict]:
        """Extract all links with context"""
        links = []
        
        for link in content_elem.find_all('a', href=True):
            href = link.get('href')
            text = link.get_text(strip=True)
            
            # Resolve relative URLs
            if href.startswith('/') or href.startswith('./') or href.startswith('../'):
                href = urljoin(base_url, href)
            
            # Categorize link type
            link_type = 'external'
            if any(domain in href for domain in ['docs.atlan.com', 'developer.atlan.com']):
                link_type = 'internal'
            elif href.startswith('#'):
                link_type = 'anchor'
            elif href.startswith('mailto:'):
                link_type = 'email'
            
            links.append({
                'text': text,
                'href': href,
                'type': link_type
            })
        
        return links
    
    def _extract_tags(self, soup: BeautifulSoup) -> List[str]:
        """Extract tags or categories"""
        tags = []
        
        # Look for tag links (common in Docusaurus)
        tag_links = soup.find_all('a', href=re.compile(r'/tags/'))
        for link in tag_links:
            tag = link.get_text(strip=True)
            if tag not in tags:
                tags.append(tag)
        
        # Look for category metadata
        meta_tags = soup.find_all('meta', {'name': 'keywords'})
        for meta in meta_tags:
            content = meta.get('content', '')
            if content:
                keywords = [kw.strip() for kw in content.split(',')]
                tags.extend(keywords)
        
        return list(set(tags))  # Remove duplicates
    
    def _extract_meta_description(self, soup: BeautifulSoup) -> str:
        """Extract meta description"""
        meta_desc = soup.find('meta', {'name': 'description'})
        if meta_desc:
            return meta_desc.get('content', '').strip()
        
        # Fallback to Open Graph description
        og_desc = soup.find('meta', {'property': 'og:description'})
        if og_desc:
            return og_desc.get('content', '').strip()
        
        return ''
    
    def _extract_structured_content(self, content_elem: Tag) -> List[Dict]:
        """Extract structured content sections"""
        sections = []
        current_section = None
        
        for element in content_elem.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'ul', 'ol', 'blockquote', 'pre', 'table']):
            if element.name.startswith('h'):
                # Start new section
                if current_section:
                    sections.append(current_section)
                
                level = int(element.name[1])
                current_section = {
                    'type': 'section',
                    'level': level,
                    'title': element.get_text(strip=True),
                    'anchor': element.get('id'),
                    'content_elements': []
                }
            
            elif current_section:
                # Add content to current section
                element_type = element.name
                element_text = element.get_text(strip=True)
                
                if element_text:  # Only add non-empty content
                    current_section['content_elements'].append({
                        'type': element_type,
                        'text': element_text,
                        'html': str(element)
                    })
        
        # Don't forget the last section
        if current_section:
            sections.append(current_section)
        
        return sections
    
    def detect_content_type(self, content_data: Dict, url: str) -> str:
        """Detect the type of documentation content"""
        url_lower = url.lower()
        title_lower = content_data.get('title', '').lower()
        content_text = content_data.get('content', '').lower()
        
        # API documentation
        if ('/api/' in url_lower or '/endpoints/' in url_lower or 
            'api' in title_lower or 'endpoint' in title_lower):
            return 'api'
        
        # FAQ pages
        if ('faq' in url_lower or 'faq' in title_lower or 
            'question' in title_lower):
            return 'faq'
        
        # Tutorials and how-to guides
        if (any(x in url_lower for x in ['tutorial', 'guide', 'how-to']) or
            any(x in title_lower for x in ['tutorial', 'guide', 'how to']) or
            'step' in content_text):
            return 'tutorial'
        
        # Concept documentation
        if ('concept' in url_lower or 'concept' in title_lower or
            'overview' in title_lower or 'introduction' in title_lower):
            return 'concept'
        
        # Reference documentation
        if ('reference' in url_lower or 'ref' in url_lower or
            len(content_data.get('code_blocks', [])) > 2):
            return 'reference'
        
        # Default
        return 'reference'


def test_extractor():
    """Test the content extractor"""
    import requests
    
    # Test with a sample page
    test_urls = [
        ("docs", "https://docs.atlan.com/connectors/snowflake/"),
        ("developer", "https://developer.atlan.com/sdk/python/")
    ]
    
    for site_key, url in test_urls:
        print(f"\nTesting {site_key}: {url}")
        
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            extractor = ContentExtractor(site_key)
            content_data = extractor.extract_page_content(response.text, url)
            
            if content_data:
                print(f"Title: {content_data['title']}")
                print(f"Breadcrumbs: {content_data['breadcrumbs']}")
                print(f"Headings: {len(content_data['headings'])}")
                print(f"Code blocks: {len(content_data['code_blocks'])}")
                print(f"Tables: {len(content_data['tables'])}")
                print(f"Content length: {len(content_data['content'])}")
                print(f"Content type: {extractor.detect_content_type(content_data, url)}")
            else:
                print("Failed to extract content")
                
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_extractor()