"""
Main Atlan Documentation Scraper using Crawl4AI
Production-ready scraper for docs.atlan.com and developer.atlan.com
"""
import asyncio
import json
import logging
import time
from typing import List, Dict, Optional, Any
from pathlib import Path
import signal
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from crawl4ai import AsyncWebCrawler

from config import CRAWLER_CONFIG, OUTPUT_FILE, SITES
from sitemap_parser import SitemapParser
from content_extractor import ContentExtractor
from content_chunker import ContentChunker
from metadata_extractor import MetadataExtractor
from crawler_utils import (
    setup_logging, CrawlCheckpoint, CrawlStats, RetryHandler, 
    ErrorHandler, validate_output_file, cleanup_temp_files
)

logger = logging.getLogger(__name__)


class AtlanDocsCrawler:
    """Main crawler orchestrating the documentation scraping process"""
    
    def __init__(self):
        self.sitemap_parser = SitemapParser()
        self.content_extractors = {
            site_key: ContentExtractor(site_key) 
            for site_key in SITES.keys()
        }
        self.chunker = ContentChunker()
        self.metadata_extractor = MetadataExtractor()
        
        self.checkpoint = CrawlCheckpoint()
        self.stats = CrawlStats()
        self.retry_handler = RetryHandler()
        self.error_handler = ErrorHandler()
        
        self.crawler = None
        self.output_file_handle = None
        self.graceful_shutdown = False
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        logger.info(f"Received signal {signum}. Initiating graceful shutdown...")
        self.graceful_shutdown = True
    
    async def initialize(self):
        """Initialize the crawler and output file"""
        logger.info("Initializing Atlan documentation crawler...")
        
        # Initialize Crawl4AI
        self.crawler = AsyncWebCrawler(
            headless=True,
            verbose=False,
            **CRAWLER_CONFIG
        )
        
        # Open output file for writing
        self.output_file_handle = open(OUTPUT_FILE, 'a', encoding='utf-8')
        
        logger.info("Crawler initialized successfully")
    
    async def cleanup(self):
        """Cleanup resources"""
        if self.crawler:
            await self.crawler.close()
        
        if self.output_file_handle:
            self.output_file_handle.close()
        
        logger.info("Crawler cleanup completed")
    
    async def crawl_documentation_sites(self):
        """Main method to crawl both documentation sites"""
        try:
            await self.initialize()
            
            # Step 1: Parse sitemaps and get URLs
            logger.info("Step 1: Parsing sitemaps and prioritizing URLs")
            all_urls = self.sitemap_parser.parse_all_sitemaps()
            
            if not all_urls:
                logger.error("No URLs found in sitemaps. Exiting.")
                return
            
            # Filter out already processed URLs
            urls_to_process = []
            for url_data in all_urls:
                if not self.checkpoint.is_url_processed(url_data['url']):
                    urls_to_process.append(url_data)
            
            self.checkpoint.set_total_urls(len(urls_to_process))
            
            logger.info(f"Found {len(all_urls)} total URLs, {len(urls_to_process)} remaining to process")
            
            if not urls_to_process:
                logger.info("All URLs already processed. Nothing to do.")
                return
            
            # Step 2: Process URLs in batches
            await self._process_urls_in_batches(urls_to_process)
            
            # Step 3: Finalize and save statistics
            self._finalize_crawl()
            
        except Exception as e:
            logger.error(f"Critical error in main crawl process: {e}")
            raise
        
        finally:
            await self.cleanup()
    
    async def _process_urls_in_batches(self, urls_to_process: List[Dict]):
        """Process URLs in batches with proper error handling"""
        batch_size = 10  # Process 10 URLs concurrently
        
        for i in range(0, len(urls_to_process), batch_size):
            if self.graceful_shutdown:
                logger.info("Graceful shutdown requested. Stopping processing.")
                break
            
            batch = urls_to_process[i:i + batch_size]
            batch_start_time = time.time()
            
            logger.info(f"Processing batch {i//batch_size + 1} ({len(batch)} URLs)")
            
            # Process batch concurrently
            tasks = []
            for url_data in batch:
                task = asyncio.create_task(self._process_single_url(url_data))
                tasks.append(task)
            
            # Wait for all tasks in batch to complete
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results and handle any exceptions
            for url_data, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    error_type = self.error_handler.log_error(url_data['url'], result)
                    self.stats.record_page_failure(
                        url_data['url'], 
                        url_data['site'], 
                        str(result), 
                        error_type
                    )
                    self.checkpoint.mark_url_failed(url_data['url'], str(result))
            
            # Save checkpoint periodically
            if self.checkpoint.should_save_checkpoint():
                self.checkpoint.save_checkpoint()
                self.stats.save_stats()
            
            # Print progress
            self.stats.print_progress(self.checkpoint)
            
            # Rate limiting between batches
            batch_time = time.time() - batch_start_time
            if batch_time < CRAWLER_CONFIG['delay_between_requests']:
                await asyncio.sleep(CRAWLER_CONFIG['delay_between_requests'] - batch_time)
    
    async def _process_single_url(self, url_data: Dict) -> Optional[Dict]:
        """Process a single URL with retry logic"""
        url = url_data['url']
        site_key = url_data['site']
        
        start_time = time.time()
        
        try:
            # Crawl the page
            logger.debug(f"Crawling {url}")
            result = await self.retry_handler.retry_with_backoff(
                self._crawl_page, url
            )
            
            if not result or not result.success:
                raise Exception(f"Failed to crawl page: {result.error_message if result else 'Unknown error'}")
            
            # Extract content
            content_extractor = self.content_extractors[site_key]
            content_data = content_extractor.extract_page_content(result.html, url)
            
            if not content_data:
                raise Exception("Failed to extract content from page")
            
            # Detect content type
            content_type = content_extractor.detect_content_type(content_data, url)
            self.stats.record_content_type(content_type)
            
            # Chunk content
            chunks = self.chunker.chunk_content(content_data, content_type)
            
            if not chunks:
                logger.warning(f"No chunks created for {url}")
                return
            
            # Generate metadata for each chunk and write to output
            chunks_written = 0
            for chunk in chunks:
                try:
                    # Generate metadata
                    metadata = self.metadata_extractor.generate_chunk_metadata(
                        chunk, content_data, url_data
                    )
                    
                    # Validate metadata schema
                    is_valid, errors = self.metadata_extractor.validate_metadata_schema(metadata)
                    if not is_valid:
                        logger.warning(f"Invalid metadata for {url}: {errors}")
                        continue
                    
                    # Write to output file
                    json_line = json.dumps(metadata, ensure_ascii=False)
                    self.output_file_handle.write(json_line + '\n')
                    self.output_file_handle.flush()  # Ensure data is written
                    
                    chunks_written += 1
                    self.stats.record_chunk_type(chunk.get('chunk_type', 'unknown'))
                    
                except Exception as e:
                    logger.error(f"Failed to process chunk from {url}: {e}")
                    continue
            
            # Record success
            processing_time = time.time() - start_time
            self.stats.record_page_success(url, site_key, chunks_written, processing_time)
            self.checkpoint.mark_url_processed(url, chunks_written)
            
            logger.info(f"Successfully processed {url} - {chunks_written} chunks in {processing_time:.2f}s")
            
            return {
                'url': url,
                'chunks_count': chunks_written,
                'processing_time': processing_time
            }
        
        except Exception as e:
            error_type = self.error_handler.log_error(url, e, {'site': site_key})
            
            # Only retry for recoverable errors
            if self.error_handler.is_recoverable_error(e):
                logger.info(f"Will retry {url} due to recoverable error: {error_type}")
                raise  # Let retry handler catch this
            else:
                logger.error(f"Non-recoverable error for {url}: {error_type}")
                self.stats.record_page_failure(url, site_key, str(e), error_type)
                self.checkpoint.mark_url_failed(url, str(e))
                return None
    
    async def _crawl_page(self, url: str):
        """Crawl a single page using Crawl4AI"""
        return await self.crawler.arun(
            url=url,
            word_count_threshold=MIN_WORD_COUNT,
            exclude_external_links=True,
            exclude_social_media_links=True,
            timeout=CRAWLER_CONFIG['timeout']
        )
    
    def _finalize_crawl(self):
        """Finalize the crawling process"""
        logger.info("Finalizing crawl process...")
        
        # Save final checkpoint and statistics
        self.checkpoint.save_checkpoint()
        self.stats.finalize_stats()
        self.stats.save_stats()
        
        # Validate output file
        if validate_output_file(OUTPUT_FILE):
            logger.info(f"Output file validation passed: {OUTPUT_FILE}")
        else:
            logger.error(f"Output file validation failed: {OUTPUT_FILE}")
        
        # Print final summary
        print("\n" + "="*80)
        print("CRAWL COMPLETED")
        print("="*80)
        print(self.stats.get_summary())
        print("="*80)
        
        # Show file locations
        print(f"\nOutput files:")
        print(f"  Chunks: {OUTPUT_FILE}")
        print(f"  Statistics: {self.stats.stats_file}")
        print(f"  Checkpoint: {self.checkpoint.checkpoint_file}")
        print(f"  Logs: {logging.getLogger().handlers[0].baseFilename}")
    
    async def resume_crawl(self):
        """Resume crawling from checkpoint"""
        resume_info = self.checkpoint.get_resume_info()
        
        if resume_info['processed_count'] == 0:
            logger.info("No previous crawl found. Starting fresh crawl.")
            await self.crawl_documentation_sites()
        else:
            logger.info(f"Resuming crawl from checkpoint:")
            logger.info(f"  Previously processed: {resume_info['processed_count']} URLs")
            logger.info(f"  Previously failed: {resume_info['failed_count']} URLs")
            logger.info(f"  Chunks created: {resume_info['chunks_created']}")
            logger.info(f"  Last processed: {resume_info['last_processed_url']}")
            
            await self.crawl_documentation_sites()


# Minimum word count for valid content
MIN_WORD_COUNT = 50


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Atlan Documentation Crawler")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--clean", action="store_true", help="Clean start (remove checkpoint)")
    parser.add_argument("--validate-only", action="store_true", help="Only validate existing output")
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(args.log_level)
    
    # Handle clean start
    if args.clean:
        cleanup_temp_files()
        if Path(CHECKPOINT_FILE).exists():
            Path(CHECKPOINT_FILE).unlink()
        logger.info("Cleaned previous state. Starting fresh.")
    
    # Handle validation only
    if args.validate_only:
        if validate_output_file(OUTPUT_FILE):
            print(f"✓ Output file {OUTPUT_FILE} is valid")
            sys.exit(0)
        else:
            print(f"✗ Output file {OUTPUT_FILE} is invalid")
            sys.exit(1)
    
    # Run crawler
    crawler = AtlanDocsCrawler()
    
    try:
        if args.resume:
            asyncio.run(crawler.resume_crawl())
        else:
            asyncio.run(crawler.crawl_documentation_sites())
        
        logger.info("Crawl completed successfully")
        
    except KeyboardInterrupt:
        logger.info("Crawl interrupted by user")
        sys.exit(130)  # Standard exit code for SIGINT
    
    except Exception as e:
        logger.error(f"Crawl failed with error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()