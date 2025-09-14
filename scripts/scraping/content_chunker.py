"""
Intelligent content chunking strategies for different types of documentation
"""
import re
import logging
from typing import List, Dict, Tuple, Optional
from bs4 import BeautifulSoup, NavigableString
import tiktoken

from config import CHUNKING_STRATEGY, CHUNK_OVERLAP, MIN_CHUNK_SIZE

logger = logging.getLogger(__name__)


class ContentChunker:
    """Chunks documentation content intelligently based on content type"""
    
    def __init__(self):
        self.encoder = tiktoken.encoding_for_model("gpt-3.5-turbo")
    
    def count_tokens(self, text: str) -> int:
        """Count tokens in text using tiktoken"""
        return len(self.encoder.encode(text))
    
    def chunk_content(self, content_data: Dict, content_type: str) -> List[Dict]:
        """Main chunking method that routes to appropriate strategy"""
        url = content_data.get('url', '')
        
        # Determine chunking strategy
        strategy = self._select_chunking_strategy(content_type, url)
        logger.debug(f"Using chunking strategy: {strategy} for {url}")
        
        # Route to appropriate chunking method
        if strategy == 'overview_pages':
            chunks = self._chunk_overview_pages(content_data)
        elif strategy == 'how_to_guides':
            chunks = self._chunk_how_to_guides(content_data)
        elif strategy == 'api_reference':
            chunks = self._chunk_api_reference(content_data)
        elif strategy == 'connector_docs':
            chunks = self._chunk_connector_docs(content_data)
        elif strategy == 'faq_pages':
            chunks = self._chunk_faq_pages(content_data)
        else:
            chunks = self._chunk_default(content_data)
        
        # Post-process chunks
        chunks = self._post_process_chunks(chunks, content_data)
        
        logger.info(f"Created {len(chunks)} chunks from {url}")
        return chunks
    
    def _select_chunking_strategy(self, content_type: str, url: str) -> str:
        """Select appropriate chunking strategy"""
        url_lower = url.lower()
        
        # Check URL patterns first
        for strategy, config in CHUNKING_STRATEGY.items():
            identifiers = config.get('identifier', [])
            for identifier in identifiers:
                if identifier in url_lower:
                    return strategy
        
        # Fall back to content type
        if content_type == 'tutorial':
            return 'how_to_guides'
        elif content_type == 'api':
            return 'api_reference'
        elif content_type == 'faq':
            return 'faq_pages'
        elif content_type == 'concept' and any(x in url_lower for x in ['overview', 'introduction']):
            return 'overview_pages'
        
        return 'default'
    
    def _chunk_overview_pages(self, content_data: Dict) -> List[Dict]:
        """Chunk overview and introduction pages"""
        config = CHUNKING_STRATEGY['overview_pages']
        max_tokens = config['max_tokens']
        
        structured_content = content_data.get('structured_content', [])
        chunks = []
        
        if structured_content and config.get('preserve_first_section', True):
            # Keep the first section intact if it's not too large
            first_section = structured_content[0]
            first_section_text = self._section_to_text(first_section)
            
            if self.count_tokens(first_section_text) <= max_tokens:
                chunks.append({
                    'content': first_section_text,
                    'chunk_type': 'overview_intro',
                    'parent_heading': first_section.get('title', ''),
                    'section_data': first_section
                })
                remaining_sections = structured_content[1:]
            else:
                remaining_sections = structured_content
        else:
            remaining_sections = structured_content
        
        # Process remaining sections
        current_chunk = ""
        current_sections = []
        
        for section in remaining_sections:
            section_text = self._section_to_text(section)
            section_tokens = self.count_tokens(section_text)
            
            # If section is too large by itself, split it
            if section_tokens > max_tokens:
                # Save current chunk if exists
                if current_chunk:
                    chunks.append({
                        'content': current_chunk.strip(),
                        'chunk_type': 'overview_section',
                        'parent_heading': current_sections[0].get('title', '') if current_sections else '',
                        'section_data': current_sections
                    })
                    current_chunk = ""
                    current_sections = []
                
                # Split large section
                sub_chunks = self._split_large_section(section, max_tokens)
                chunks.extend(sub_chunks)
            
            else:
                # Check if adding this section would exceed limit
                combined_tokens = self.count_tokens(current_chunk + "\n\n" + section_text)
                
                if combined_tokens > max_tokens and current_chunk:
                    # Save current chunk
                    chunks.append({
                        'content': current_chunk.strip(),
                        'chunk_type': 'overview_section',
                        'parent_heading': current_sections[0].get('title', '') if current_sections else '',
                        'section_data': current_sections
                    })
                    current_chunk = section_text
                    current_sections = [section]
                else:
                    # Add to current chunk
                    if current_chunk:
                        current_chunk += "\n\n" + section_text
                    else:
                        current_chunk = section_text
                    current_sections.append(section)
        
        # Don't forget the last chunk
        if current_chunk:
            chunks.append({
                'content': current_chunk.strip(),
                'chunk_type': 'overview_section',
                'parent_heading': current_sections[0].get('title', '') if current_sections else '',
                'section_data': current_sections
            })
        
        return chunks
    
    def _chunk_how_to_guides(self, content_data: Dict) -> List[Dict]:
        """Chunk tutorial and how-to content"""
        config = CHUNKING_STRATEGY['how_to_guides']
        max_tokens = config['max_tokens']
        
        structured_content = content_data.get('structured_content', [])
        chunks = []
        
        for section in structured_content:
            section_text = self._section_to_text(section)
            
            # Check if section has numbered steps
            has_steps = self._has_numbered_steps(section_text)
            
            if has_steps and config.get('keep_steps_together', True):
                # Try to keep numbered steps together
                chunks_from_section = self._chunk_steps_section(section, max_tokens)
            else:
                # Regular chunking
                if self.count_tokens(section_text) > max_tokens:
                    chunks_from_section = self._split_large_section(section, max_tokens)
                else:
                    chunks_from_section = [{
                        'content': section_text,
                        'chunk_type': 'tutorial_section',
                        'parent_heading': section.get('title', ''),
                        'section_data': section,
                        'has_steps': has_steps
                    }]
            
            chunks.extend(chunks_from_section)
        
        return chunks
    
    def _chunk_api_reference(self, content_data: Dict) -> List[Dict]:
        """Chunk API reference documentation"""
        config = CHUNKING_STRATEGY['api_reference']
        max_tokens = config['max_tokens']
        
        structured_content = content_data.get('structured_content', [])
        chunks = []
        
        for section in structured_content:
            # For API docs, each method/endpoint should ideally be its own chunk
            if config.get('one_endpoint_per_chunk', True):
                chunks_from_section = self._chunk_api_endpoints(section, max_tokens)
            else:
                section_text = self._section_to_text(section)
                if self.count_tokens(section_text) > max_tokens:
                    chunks_from_section = self._split_large_section(section, max_tokens)
                else:
                    chunks_from_section = [{
                        'content': section_text,
                        'chunk_type': 'api_section',
                        'parent_heading': section.get('title', ''),
                        'section_data': section
                    }]
            
            chunks.extend(chunks_from_section)
        
        return chunks
    
    def _chunk_connector_docs(self, content_data: Dict) -> List[Dict]:
        """Chunk connector documentation"""
        config = CHUNKING_STRATEGY['connector_docs']
        max_tokens = config['max_tokens']
        
        structured_content = content_data.get('structured_content', [])
        chunks = []
        
        # Look for prerequisites section and keep it together
        prereq_section = None
        other_sections = []
        
        for section in structured_content:
            title = section.get('title', '').lower()
            if any(word in title for word in ['prerequisite', 'requirement', 'setup']):
                prereq_section = section
            else:
                other_sections.append(section)
        
        # Process prerequisites first
        if prereq_section and config.get('keep_prerequisites_together', True):
            prereq_text = self._section_to_text(prereq_section)
            if self.count_tokens(prereq_text) <= max_tokens:
                chunks.append({
                    'content': prereq_text,
                    'chunk_type': 'connector_prerequisites',
                    'parent_heading': prereq_section.get('title', ''),
                    'section_data': prereq_section
                })
            else:
                prereq_chunks = self._split_large_section(prereq_section, max_tokens)
                chunks.extend(prereq_chunks)
        
        # Process other sections
        current_chunk = ""
        current_sections = []
        
        for section in other_sections:
            section_text = self._section_to_text(section)
            section_tokens = self.count_tokens(section_text)
            
            if section_tokens > max_tokens:
                # Save current chunk if exists
                if current_chunk:
                    chunks.append({
                        'content': current_chunk.strip(),
                        'chunk_type': 'connector_section',
                        'parent_heading': current_sections[0].get('title', '') if current_sections else '',
                        'section_data': current_sections
                    })
                    current_chunk = ""
                    current_sections = []
                
                # Split large section
                sub_chunks = self._split_large_section(section, max_tokens)
                chunks.extend(sub_chunks)
            
            else:
                combined_tokens = self.count_tokens(current_chunk + "\n\n" + section_text)
                
                if combined_tokens > max_tokens and current_chunk:
                    chunks.append({
                        'content': current_chunk.strip(),
                        'chunk_type': 'connector_section',
                        'parent_heading': current_sections[0].get('title', '') if current_sections else '',
                        'section_data': current_sections
                    })
                    current_chunk = section_text
                    current_sections = [section]
                else:
                    if current_chunk:
                        current_chunk += "\n\n" + section_text
                    else:
                        current_chunk = section_text
                    current_sections.append(section)
        
        # Last chunk
        if current_chunk:
            chunks.append({
                'content': current_chunk.strip(),
                'chunk_type': 'connector_section',
                'parent_heading': current_sections[0].get('title', '') if current_sections else '',
                'section_data': current_sections
            })
        
        return chunks
    
    def _chunk_faq_pages(self, content_data: Dict) -> List[Dict]:
        """Chunk FAQ pages - each Q&A pair becomes a chunk"""
        config = CHUNKING_STRATEGY['faq_pages']
        max_tokens = config['max_tokens']
        
        if not config.get('split_by_qa_pairs', True):
            return self._chunk_default(content_data)
        
        content_text = content_data.get('content', '')
        chunks = []
        
        # Try to identify Q&A pairs
        qa_pairs = self._extract_qa_pairs(content_text)
        
        if qa_pairs:
            for qa in qa_pairs:
                if self.count_tokens(qa['content']) <= max_tokens:
                    chunks.append({
                        'content': qa['content'],
                        'chunk_type': 'faq_pair',
                        'parent_heading': 'FAQ',
                        'question': qa['question'],
                        'answer': qa['answer']
                    })
                else:
                    # Split long answers
                    question_tokens = self.count_tokens(qa['question'])
                    available_tokens = max_tokens - question_tokens - 50  # Buffer
                    
                    answer_chunks = self._split_text_by_tokens(qa['answer'], available_tokens)
                    for i, answer_chunk in enumerate(answer_chunks):
                        chunk_content = qa['question'] + "\n\n" + answer_chunk
                        chunks.append({
                            'content': chunk_content,
                            'chunk_type': 'faq_pair',
                            'parent_heading': 'FAQ',
                            'question': qa['question'],
                            'answer': answer_chunk,
                            'is_continuation': i > 0
                        })
        else:
            # Fall back to default chunking
            chunks = self._chunk_default(content_data)
        
        return chunks
    
    def _chunk_default(self, content_data: Dict) -> List[Dict]:
        """Default chunking strategy"""
        content_text = content_data.get('content', '')
        max_tokens = 800  # Default
        
        if self.count_tokens(content_text) <= max_tokens:
            return [{
                'content': content_text,
                'chunk_type': 'full_page',
                'parent_heading': content_data.get('title', ''),
                'section_data': None
            }]
        
        # Split by paragraphs first
        paragraphs = content_text.split('\n\n')
        chunks = []
        current_chunk = ""
        
        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            
            combined = current_chunk + "\n\n" + paragraph if current_chunk else paragraph
            
            if self.count_tokens(combined) > max_tokens:
                if current_chunk:
                    chunks.append({
                        'content': current_chunk.strip(),
                        'chunk_type': 'text_section',
                        'parent_heading': content_data.get('title', ''),
                        'section_data': None
                    })
                
                # If single paragraph is too long, split it
                if self.count_tokens(paragraph) > max_tokens:
                    sub_chunks = self._split_text_by_tokens(paragraph, max_tokens)
                    for sub_chunk in sub_chunks:
                        chunks.append({
                            'content': sub_chunk,
                            'chunk_type': 'text_section',
                            'parent_heading': content_data.get('title', ''),
                            'section_data': None
                        })
                    current_chunk = ""
                else:
                    current_chunk = paragraph
            else:
                current_chunk = combined
        
        # Last chunk
        if current_chunk:
            chunks.append({
                'content': current_chunk.strip(),
                'chunk_type': 'text_section',
                'parent_heading': content_data.get('title', ''),
                'section_data': None
            })
        
        return chunks
    
    def _section_to_text(self, section: Dict) -> str:
        """Convert structured section to text"""
        text_parts = []
        
        # Add section title
        title = section.get('title', '')
        if title:
            text_parts.append(f"# {title}")
        
        # Add content elements
        content_elements = section.get('content_elements', [])
        for element in content_elements:
            element_text = element.get('text', '')
            if element_text:
                text_parts.append(element_text)
        
        return '\n\n'.join(text_parts)
    
    def _has_numbered_steps(self, text: str) -> bool:
        """Check if text contains numbered steps"""
        # Look for numbered list patterns
        patterns = [
            r'^\d+\.',  # 1. 2. 3.
            r'Step \d+',  # Step 1, Step 2
            r'^\d+\)',  # 1) 2) 3)
        ]
        
        for pattern in patterns:
            if re.search(pattern, text, re.MULTILINE):
                return True
        
        return False
    
    def _chunk_steps_section(self, section: Dict, max_tokens: int) -> List[Dict]:
        """Chunk a section containing numbered steps"""
        section_text = self._section_to_text(section)
        
        # Split by steps
        step_pattern = r'(?=^\d+\.|\bStep \d+|\b\d+\))'
        steps = re.split(step_pattern, section_text, flags=re.MULTILINE)
        
        if len(steps) <= 1:
            # No clear step separation, use regular splitting
            return self._split_large_section(section, max_tokens)
        
        chunks = []
        current_chunk = steps[0]  # Introduction text
        
        for step in steps[1:]:
            step = step.strip()
            if not step:
                continue
            
            combined = current_chunk + "\n\n" + step if current_chunk else step
            
            if self.count_tokens(combined) > max_tokens:
                if current_chunk:
                    chunks.append({
                        'content': current_chunk.strip(),
                        'chunk_type': 'tutorial_steps',
                        'parent_heading': section.get('title', ''),
                        'section_data': section,
                        'has_steps': True
                    })
                current_chunk = step
            else:
                current_chunk = combined
        
        # Last chunk
        if current_chunk:
            chunks.append({
                'content': current_chunk.strip(),
                'chunk_type': 'tutorial_steps',
                'parent_heading': section.get('title', ''),
                'section_data': section,
                'has_steps': True
            })
        
        return chunks
    
    def _chunk_api_endpoints(self, section: Dict, max_tokens: int) -> List[Dict]:
        """Chunk API section by endpoints"""
        section_text = self._section_to_text(section)
        
        # Look for HTTP method patterns
        endpoint_pattern = r'(?=^(?:GET|POST|PUT|DELETE|PATCH)\s+/)'
        endpoints = re.split(endpoint_pattern, section_text, flags=re.MULTILINE)
        
        if len(endpoints) <= 1:
            # No clear endpoint separation
            if self.count_tokens(section_text) > max_tokens:
                return self._split_large_section(section, max_tokens)
            else:
                return [{
                    'content': section_text,
                    'chunk_type': 'api_section',
                    'parent_heading': section.get('title', ''),
                    'section_data': section
                }]
        
        chunks = []
        
        # First chunk might be introduction
        if endpoints[0].strip():
            intro_tokens = self.count_tokens(endpoints[0])
            if intro_tokens > max_tokens:
                intro_chunks = self._split_text_by_tokens(endpoints[0], max_tokens)
                for intro_chunk in intro_chunks:
                    chunks.append({
                        'content': intro_chunk,
                        'chunk_type': 'api_intro',
                        'parent_heading': section.get('title', ''),
                        'section_data': section
                    })
            else:
                chunks.append({
                    'content': endpoints[0].strip(),
                    'chunk_type': 'api_intro',
                    'parent_heading': section.get('title', ''),
                    'section_data': section
                })
        
        # Process endpoints
        for endpoint in endpoints[1:]:
            endpoint = endpoint.strip()
            if not endpoint:
                continue
            
            if self.count_tokens(endpoint) > max_tokens:
                endpoint_chunks = self._split_text_by_tokens(endpoint, max_tokens)
                for i, endpoint_chunk in enumerate(endpoint_chunks):
                    chunks.append({
                        'content': endpoint_chunk,
                        'chunk_type': 'api_endpoint',
                        'parent_heading': section.get('title', ''),
                        'section_data': section,
                        'is_continuation': i > 0
                    })
            else:
                chunks.append({
                    'content': endpoint,
                    'chunk_type': 'api_endpoint',
                    'parent_heading': section.get('title', ''),
                    'section_data': section
                })
        
        return chunks
    
    def _split_large_section(self, section: Dict, max_tokens: int) -> List[Dict]:
        """Split a large section into smaller chunks"""
        section_text = self._section_to_text(section)
        text_chunks = self._split_text_by_tokens(section_text, max_tokens)
        
        chunks = []
        for i, text_chunk in enumerate(text_chunks):
            chunks.append({
                'content': text_chunk,
                'chunk_type': 'section_part',
                'parent_heading': section.get('title', ''),
                'section_data': section,
                'is_continuation': i > 0
            })
        
        return chunks
    
    def _split_text_by_tokens(self, text: str, max_tokens: int) -> List[str]:
        """Split text by token count, preserving sentence boundaries"""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            combined = current_chunk + " " + sentence if current_chunk else sentence
            
            if self.count_tokens(combined) > max_tokens:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = sentence
                else:
                    # Single sentence too long, split by words
                    words = sentence.split()
                    temp_chunk = ""
                    for word in words:
                        temp_combined = temp_chunk + " " + word if temp_chunk else word
                        if self.count_tokens(temp_combined) > max_tokens:
                            if temp_chunk:
                                chunks.append(temp_chunk.strip())
                            temp_chunk = word
                        else:
                            temp_chunk = temp_combined
                    current_chunk = temp_chunk
            else:
                current_chunk = combined
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks
    
    def _extract_qa_pairs(self, text: str) -> List[Dict]:
        """Extract Q&A pairs from FAQ text"""
        qa_pairs = []
        
        # Common Q&A patterns
        patterns = [
            r'(?:Q:|Question:)\s*(.*?)\n(?:A:|Answer:)\s*(.*?)(?=(?:Q:|Question:)|\Z)',
            r'(?:^|\n)(.*?\?)\n+(.*?)(?=\n.*?\?|\Z)',
        ]
        
        for pattern in patterns:
            matches = re.finditer(pattern, text, re.DOTALL | re.MULTILINE)
            for match in matches:
                question = match.group(1).strip()
                answer = match.group(2).strip()
                
                if len(question) > 10 and len(answer) > 10:  # Basic validation
                    qa_pairs.append({
                        'question': question,
                        'answer': answer,
                        'content': f"Q: {question}\n\nA: {answer}"
                    })
        
        return qa_pairs
    
    def _post_process_chunks(self, chunks: List[Dict], content_data: Dict) -> List[Dict]:
        """Post-process chunks with metadata and validation"""
        processed_chunks = []
        
        for i, chunk in enumerate(chunks):
            # Validate chunk content
            content = chunk.get('content', '').strip()
            if len(content) < MIN_CHUNK_SIZE:
                logger.debug(f"Skipping chunk {i} - too small ({len(content)} chars)")
                continue
            
            # Add token count
            token_count = self.count_tokens(content)
            word_count = len(content.split())
            
            # Add chunk metadata
            chunk.update({
                'chunk_index': i,
                'total_chunks': len(chunks),
                'word_count': word_count,
                'token_count': token_count,
                'content_preview': content[:200]  # First 200 chars for preview
            })
            
            # Add overlap if not first chunk and previous chunks exist
            if i > 0 and CHUNK_OVERLAP > 0 and processed_chunks:
                previous_chunk = processed_chunks[-1]
                overlap_text = self._create_overlap(previous_chunk['content'], content, CHUNK_OVERLAP)
                if overlap_text:
                    chunk['content'] = overlap_text + "\n\n" + content
                    chunk['token_count'] = self.count_tokens(chunk['content'])
                    chunk['has_overlap'] = True
            
            processed_chunks.append(chunk)
        
        return processed_chunks
    
    def _create_overlap(self, previous_content: str, current_content: str, overlap_tokens: int) -> str:
        """Create overlap between chunks"""
        # Take last sentences from previous chunk
        sentences = re.split(r'(?<=[.!?])\s+', previous_content)
        overlap_text = ""
        
        for sentence in reversed(sentences):
            test_overlap = sentence + " " + overlap_text if overlap_text else sentence
            if self.count_tokens(test_overlap) <= overlap_tokens:
                overlap_text = test_overlap
            else:
                break
        
        return overlap_text.strip()


def test_chunker():
    """Test the content chunker"""
    # Sample content data
    test_content = {
        'url': 'https://docs.atlan.com/connectors/snowflake/setup',
        'title': 'Setting up Snowflake Connector',
        'content': '''# Setting up Snowflake Connector

This guide explains how to set up the Snowflake connector in Atlan.

## Prerequisites

Before you begin, ensure you have:
1. Snowflake account credentials
2. Appropriate permissions
3. Network connectivity

## Step 1: Configure Connection

To configure your connection:
1. Navigate to the connectors page
2. Select Snowflake connector
3. Enter your credentials

## Step 2: Test Connection

Test your connection by:
1. Clicking the test button
2. Verifying the response
3. Saving the configuration

This completes the setup process.''',
        'structured_content': [
            {
                'type': 'section',
                'level': 1,
                'title': 'Setting up Snowflake Connector',
                'content_elements': [
                    {'type': 'p', 'text': 'This guide explains how to set up the Snowflake connector in Atlan.'}
                ]
            },
            {
                'type': 'section',
                'level': 2,
                'title': 'Prerequisites',
                'content_elements': [
                    {'type': 'p', 'text': 'Before you begin, ensure you have:\n1. Snowflake account credentials\n2. Appropriate permissions\n3. Network connectivity'}
                ]
            }
        ]
    }
    
    chunker = ContentChunker()
    chunks = chunker.chunk_content(test_content, 'tutorial')
    
    print(f"Created {len(chunks)} chunks:")
    for i, chunk in enumerate(chunks):
        print(f"\nChunk {i + 1}:")
        print(f"  Type: {chunk['chunk_type']}")
        print(f"  Tokens: {chunk['token_count']}")
        print(f"  Content preview: {chunk['content_preview']}...")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_chunker()