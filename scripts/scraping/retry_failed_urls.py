#!/usr/bin/env python3
"""
Script to retry failed URLs from the crawl statistics
"""
import json
import asyncio
import logging
from pathlib import Path

from atlan_docs_crawler import AtlanDocsCrawler
from crawler_utils import setup_logging

def load_failed_urls():
    """Load failed URLs from stats file"""
    stats_file = "crawl_stats.json"
    
    if not Path(stats_file).exists():
        print(f"❌ Stats file {stats_file} not found")
        return []
    
    with open(stats_file, 'r') as f:
        stats = json.load(f)
    
    failed_details = stats.get('failed_url_details', [])
    
    # Filter for docs.atlan.com URLs only
    docs_failed = []
    for failure in failed_details:
        if failure['site'] == 'docs':
            docs_failed.append({
                'url': failure['url'],
                'site': 'docs',
                'priority_score': 0.5,  # Default priority
                'features': {'nav_depth': 2}  # Default features
            })
    
    print(f"Found {len(docs_failed)} failed docs.atlan.com URLs to retry")
    return docs_failed

async def retry_failed_docs():
    """Retry processing failed docs.atlan.com URLs"""
    setup_logging("INFO")
    
    # Load failed URLs
    failed_urls = load_failed_urls()
    
    if not failed_urls:
        print("No failed docs URLs to retry")
        return
    
    # Show sample of URLs to be retried
    print("\nSample URLs to retry:")
    for url in failed_urls[:5]:
        print(f"  - {url['url']}")
    
    if len(failed_urls) > 5:
        print(f"  ... and {len(failed_urls) - 5} more")
    
    # Confirm with user
    response = input(f"\nRetry {len(failed_urls)} failed URLs? (y/N): ").strip().lower()
    if response != 'y':
        print("Retry cancelled")
        return
    
    # Initialize crawler
    crawler = AtlanDocsCrawler()
    
    # Backup current checkpoint
    checkpoint_file = Path("crawl_checkpoint.json")
    if checkpoint_file.exists():
        backup_file = checkpoint_file.with_suffix('.backup.retry')
        checkpoint_file.rename(backup_file)
        print(f"Backed up checkpoint to {backup_file}")
    
    try:
        await crawler.initialize()
        
        print(f"Starting retry of {len(failed_urls)} URLs...")
        
        # Process in smaller batches for docs.atlan.com
        batch_size = 5
        successful_retries = 0
        
        for i in range(0, len(failed_urls), batch_size):
            batch = failed_urls[i:i + batch_size]
            print(f"Processing retry batch {i//batch_size + 1}/{(len(failed_urls) + batch_size - 1)//batch_size}")
            
            # Process batch
            tasks = []
            for url_data in batch:
                task = asyncio.create_task(crawler._process_single_url(url_data))
                tasks.append(task)
            
            # Wait for batch completion
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Count successes
            for result in results:
                if isinstance(result, dict) and result.get('chunks_count', 0) > 0:
                    successful_retries += 1
            
            # Small delay between batches
            await asyncio.sleep(2.0)
        
        print(f"\nRetry completed:")
        print(f"  Successful: {successful_retries}")
        print(f"  Failed: {len(failed_urls) - successful_retries}")
        
        # Validate output again
        from crawler_utils import validate_output_file
        if validate_output_file("atlan_docs_chunks.jsonl"):
            print(f"✅ Output file validation passed")
        
        # Show new chunk count
        with open("atlan_docs_chunks.jsonl", 'r') as f:
            total_chunks = sum(1 for _ in f)
        print(f"📊 Total chunks now: {total_chunks}")
        
    finally:
        await crawler.cleanup()

if __name__ == "__main__":
    asyncio.run(retry_failed_docs())