"""
Utility functions for error handling, logging, and resume capability
"""
import json
import logging
import time
import os
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path
import traceback

from config import CHECKPOINT_FILE, LOG_FILE, STATS_FILE, CHECKPOINT_INTERVAL, PROGRESS_INTERVAL

# Configure logging
def setup_logging(log_level: str = "INFO"):
    """Set up logging configuration"""
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # Create logs directory if it doesn't exist
    os.makedirs(os.path.dirname(LOG_FILE) if os.path.dirname(LOG_FILE) else '.', exist_ok=True)
    
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=log_format,
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    # Set specific log levels for libraries
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('crawl4ai').setLevel(logging.INFO)


class CrawlCheckpoint:
    """Manages crawling checkpoints for resume capability"""
    
    def __init__(self, checkpoint_file: str = CHECKPOINT_FILE):
        self.checkpoint_file = checkpoint_file
        self.data = self._load_checkpoint()
        self.logger = logging.getLogger(__name__)
    
    def _load_checkpoint(self) -> Dict:
        """Load existing checkpoint data"""
        if os.path.exists(self.checkpoint_file):
            try:
                with open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logging.warning(f"Failed to load checkpoint: {e}")
        
        # Default checkpoint structure
        return {
            'last_processed_url': None,
            'processed_urls': [],
            'failed_urls': [],
            'chunks_created': 0,
            'pages_processed': 0,
            'start_time': None,
            'last_save_time': None,
            'total_urls': 0,
            'current_batch': 0
        }
    
    def save_checkpoint(self):
        """Save current checkpoint to file"""
        try:
            self.data['last_save_time'] = datetime.utcnow().isoformat() + 'Z'
            
            # Create backup of existing checkpoint
            if os.path.exists(self.checkpoint_file):
                backup_file = f"{self.checkpoint_file}.backup"
                os.rename(self.checkpoint_file, backup_file)
            
            # Save new checkpoint
            with open(self.checkpoint_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            
            self.logger.debug(f"Checkpoint saved: {self.data['pages_processed']} pages processed")
            
        except Exception as e:
            self.logger.error(f"Failed to save checkpoint: {e}")
    
    def mark_url_processed(self, url: str, chunks_count: int = 0):
        """Mark a URL as successfully processed"""
        if url not in self.data['processed_urls']:
            self.data['processed_urls'].append(url)
        
        self.data['last_processed_url'] = url
        self.data['chunks_created'] += chunks_count
        self.data['pages_processed'] += 1
        
        # Remove from failed URLs if it was there
        if url in self.data['failed_urls']:
            self.data['failed_urls'].remove(url)
    
    def mark_url_failed(self, url: str, error: str):
        """Mark a URL as failed"""
        if url not in self.data['failed_urls']:
            self.data['failed_urls'].append(url)
        
        self.logger.error(f"URL failed: {url} - {error}")
    
    def is_url_processed(self, url: str) -> bool:
        """Check if URL has already been processed"""
        return url in self.data['processed_urls']
    
    def should_save_checkpoint(self) -> bool:
        """Check if it's time to save checkpoint"""
        return self.data['pages_processed'] % CHECKPOINT_INTERVAL == 0
    
    def get_resume_info(self) -> Dict:
        """Get information for resuming crawl"""
        return {
            'processed_count': len(self.data['processed_urls']),
            'failed_count': len(self.data['failed_urls']),
            'chunks_created': self.data['chunks_created'],
            'last_processed_url': self.data['last_processed_url'],
            'start_time': self.data['start_time']
        }
    
    def set_total_urls(self, total: int):
        """Set total number of URLs to process"""
        self.data['total_urls'] = total
        if not self.data['start_time']:
            self.data['start_time'] = datetime.utcnow().isoformat() + 'Z'
    
    def get_progress(self) -> Dict:
        """Get current progress information"""
        processed = len(self.data['processed_urls'])
        total = self.data['total_urls']
        percentage = (processed / total * 100) if total > 0 else 0
        
        return {
            'processed': processed,
            'total': total,
            'percentage': percentage,
            'failed': len(self.data['failed_urls']),
            'chunks_created': self.data['chunks_created']
        }


class CrawlStats:
    """Tracks and manages crawling statistics"""
    
    def __init__(self, stats_file: str = STATS_FILE):
        self.stats_file = stats_file
        self.logger = logging.getLogger(__name__)
        self.stats = {
            'start_time': datetime.utcnow().isoformat() + 'Z',
            'end_time': None,
            'total_urls': 0,
            'successful_urls': 0,
            'failed_urls': 0,
            'total_pages_crawled': 0,
            'total_chunks_created': 0,
            'pages_per_site': {},
            'chunks_per_site': {},
            'average_chunk_size': 0,
            'failed_url_details': [],
            'crawl_duration_seconds': 0,
            'processing_stats': {
                'avg_time_per_page': 0,
                'avg_chunks_per_page': 0,
                'content_types': {},
                'chunk_types': {},
            },
            'error_summary': {}
        }
    
    def record_page_success(self, url: str, site: str, chunks_count: int, processing_time: float):
        """Record successful page processing"""
        self.stats['successful_urls'] += 1
        self.stats['total_pages_crawled'] += 1
        self.stats['total_chunks_created'] += chunks_count
        
        # Site-specific stats
        if site not in self.stats['pages_per_site']:
            self.stats['pages_per_site'][site] = 0
            self.stats['chunks_per_site'][site] = 0
        
        self.stats['pages_per_site'][site] += 1
        self.stats['chunks_per_site'][site] += chunks_count
        
        # Update processing averages
        self._update_processing_averages(processing_time, chunks_count)
    
    def record_page_failure(self, url: str, site: str, error: str, error_type: str = "unknown"):
        """Record failed page processing"""
        self.stats['failed_urls'] += 1
        
        # Record detailed failure info
        self.stats['failed_url_details'].append({
            'url': url,
            'site': site,
            'error': str(error),
            'error_type': error_type,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        })
        
        # Update error summary
        if error_type not in self.stats['error_summary']:
            self.stats['error_summary'][error_type] = 0
        self.stats['error_summary'][error_type] += 1
    
    def record_chunk_type(self, chunk_type: str):
        """Record chunk type for statistics"""
        if 'chunk_types' not in self.stats['processing_stats']:
            self.stats['processing_stats']['chunk_types'] = {}
        
        if chunk_type not in self.stats['processing_stats']['chunk_types']:
            self.stats['processing_stats']['chunk_types'][chunk_type] = 0
        
        self.stats['processing_stats']['chunk_types'][chunk_type] += 1
    
    def record_content_type(self, content_type: str):
        """Record content type for statistics"""
        if 'content_types' not in self.stats['processing_stats']:
            self.stats['processing_stats']['content_types'] = {}
        
        if content_type not in self.stats['processing_stats']['content_types']:
            self.stats['processing_stats']['content_types'][content_type] = 0
        
        self.stats['processing_stats']['content_types'][content_type] += 1
    
    def _update_processing_averages(self, processing_time: float, chunks_count: int):
        """Update processing time and chunks per page averages"""
        total_pages = self.stats['total_pages_crawled']
        
        if total_pages == 1:
            self.stats['processing_stats']['avg_time_per_page'] = processing_time
            self.stats['processing_stats']['avg_chunks_per_page'] = chunks_count
        else:
            # Running average calculation
            current_avg_time = self.stats['processing_stats']['avg_time_per_page']
            current_avg_chunks = self.stats['processing_stats']['avg_chunks_per_page']
            
            self.stats['processing_stats']['avg_time_per_page'] = (
                (current_avg_time * (total_pages - 1) + processing_time) / total_pages
            )
            self.stats['processing_stats']['avg_chunks_per_page'] = (
                (current_avg_chunks * (total_pages - 1) + chunks_count) / total_pages
            )
    
    def finalize_stats(self):
        """Finalize statistics at end of crawl"""
        self.stats['end_time'] = datetime.utcnow().isoformat() + 'Z'
        
        # Calculate duration
        if self.stats['start_time']:
            start_dt = datetime.fromisoformat(self.stats['start_time'].replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(self.stats['end_time'].replace('Z', '+00:00'))
            self.stats['crawl_duration_seconds'] = int((end_dt - start_dt).total_seconds())
        
        # Calculate average chunk size
        if self.stats['total_chunks_created'] > 0:
            # This would need to be calculated during processing
            pass
        
        # Set total URLs
        self.stats['total_urls'] = self.stats['successful_urls'] + self.stats['failed_urls']
    
    def save_stats(self):
        """Save statistics to file"""
        try:
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.stats, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"Statistics saved to {self.stats_file}")
            
        except Exception as e:
            self.logger.error(f"Failed to save statistics: {e}")
    
    def print_progress(self, checkpoint: CrawlCheckpoint):
        """Print current progress"""
        progress = checkpoint.get_progress()
        
        if progress['total'] > 0 and progress['processed'] % PROGRESS_INTERVAL == 0:
            print(f"Processed {progress['processed']}/{progress['total']} pages "
                  f"({progress['percentage']:.1f}%) - "
                  f"Created {progress['chunks_created']} chunks - "
                  f"Failed: {progress['failed']}")
    
    def get_summary(self) -> str:
        """Get a human-readable summary of statistics"""
        summary_lines = [
            f"Crawl Summary:",
            f"  Total pages processed: {self.stats['total_pages_crawled']}",
            f"  Successful: {self.stats['successful_urls']}",
            f"  Failed: {self.stats['failed_urls']}",
            f"  Total chunks created: {self.stats['total_chunks_created']}",
            f"  Average chunks per page: {self.stats['processing_stats']['avg_chunks_per_page']:.1f}",
            f"  Duration: {self.stats['crawl_duration_seconds']} seconds",
        ]
        
        if self.stats['pages_per_site']:
            summary_lines.append("  Pages per site:")
            for site, count in self.stats['pages_per_site'].items():
                summary_lines.append(f"    {site}: {count}")
        
        if self.stats['error_summary']:
            summary_lines.append("  Error types:")
            for error_type, count in self.stats['error_summary'].items():
                summary_lines.append(f"    {error_type}: {count}")
        
        return '\n'.join(summary_lines)


class RetryHandler:
    """Handles retry logic with exponential backoff"""
    
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.logger = logging.getLogger(__name__)
    
    def retry_with_backoff(self, func, *args, **kwargs):
        """Execute function with retry and exponential backoff"""
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            
            except Exception as e:
                last_exception = e
                
                if attempt == self.max_retries:
                    self.logger.error(f"Final retry attempt failed: {e}")
                    break
                
                # Calculate delay for exponential backoff
                delay = self.base_delay * (2 ** attempt)
                self.logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay:.1f}s...")
                time.sleep(delay)
        
        # All retries failed
        raise last_exception


class ErrorHandler:
    """Centralized error handling and classification"""
    
    ERROR_TYPES = {
        'network': ['ConnectionError', 'Timeout', 'HTTPError', 'URLError'],
        'parsing': ['ParseError', 'JSONDecodeError', 'XMLSyntaxError'],
        'rate_limit': ['429', 'TooManyRequests'],
        'not_found': ['404', 'NotFound'],
        'forbidden': ['403', 'Forbidden'],
        'server_error': ['500', '502', '503', '504'],
        'validation': ['ValidationError', 'SchemaError'],
        'unknown': []
    }
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def classify_error(self, error: Exception) -> str:
        """Classify error type for statistics"""
        error_str = str(error)
        error_type = type(error).__name__
        
        for category, patterns in self.ERROR_TYPES.items():
            if any(pattern.lower() in error_str.lower() or pattern in error_type for pattern in patterns):
                return category
        
        return 'unknown'
    
    def is_recoverable_error(self, error: Exception) -> bool:
        """Determine if error is recoverable and should be retried"""
        error_type = self.classify_error(error)
        
        # Don't retry for these error types
        non_recoverable = ['not_found', 'forbidden', 'validation', 'parsing']
        
        return error_type not in non_recoverable
    
    def log_error(self, url: str, error: Exception, context: Dict = None):
        """Log error with context information"""
        error_type = self.classify_error(error)
        
        log_data = {
            'url': url,
            'error_type': error_type,
            'error_message': str(error),
            'traceback': traceback.format_exc(),
        }
        
        if context:
            log_data.update(context)
        
        self.logger.error(f"Error processing {url}: {log_data}")
        
        return error_type


def validate_output_file(output_file: str) -> bool:
    """Validate that output file contains valid JSONL data"""
    if not os.path.exists(output_file):
        return False
    
    logger = logging.getLogger(__name__)
    
    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            line_count = 0
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line:
                    try:
                        json.loads(line)
                        line_count += 1
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON on line {line_num}: {e}")
                        return False
        
        logger.info(f"Output file validation passed: {line_count} valid JSON lines")
        return True
        
    except Exception as e:
        logger.error(f"Failed to validate output file: {e}")
        return False


def cleanup_temp_files():
    """Clean up temporary files"""
    temp_files = [
        'all_urls.json',
        f"{CHECKPOINT_FILE}.backup"
    ]
    
    for temp_file in temp_files:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass  # Ignore cleanup errors


if __name__ == "__main__":
    # Test the utility functions
    setup_logging()
    
    # Test checkpoint
    checkpoint = CrawlCheckpoint("test_checkpoint.json")
    checkpoint.set_total_urls(100)
    checkpoint.mark_url_processed("https://example.com/1", 5)
    checkpoint.mark_url_processed("https://example.com/2", 3)
    checkpoint.mark_url_failed("https://example.com/3", "Network error")
    
    print("Checkpoint progress:", checkpoint.get_progress())
    
    # Test stats
    stats = CrawlStats("test_stats.json")
    stats.record_page_success("https://example.com/1", "docs", 5, 2.5)
    stats.record_page_success("https://example.com/2", "developer", 3, 1.8)
    stats.record_page_failure("https://example.com/3", "docs", "Network timeout", "network")
    
    stats.finalize_stats()
    print("\nStats summary:")
    print(stats.get_summary())
    
    # Cleanup test files
    for f in ["test_checkpoint.json", "test_stats.json"]:
        if os.path.exists(f):
            os.remove(f)