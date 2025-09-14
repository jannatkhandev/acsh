#!/usr/bin/env python3
"""
FREE TIER VERSION - Ingest Atlan documentation chunks into Pinecone 
Using free sentence-transformers model instead of paid OpenAI
"""
import json
import os
import time
import logging
from typing import List, Dict, Any, Generator
from tqdm import tqdm
import hashlib

# Install required packages for FREE TIER:
# pip install pinecone-client sentence-transformers python-dotenv tqdm torch

from pinecone import Pinecone, ServerlessSpec
from sentence_transformers import SentenceTransformer
import torch

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AtlanDocsPineconeFreeIngester:
    """FREE TIER: Ingests Atlan docs using free sentence-transformers model"""
    
    def __init__(self, 
                 pinecone_api_key: str,
                 index_name: str = "atlan-docs-free",
                 embedding_model: str = "all-MiniLM-L6-v2",
                 dimension: int = 384):  # Fixed for this model
        
        self.pinecone_api_key = pinecone_api_key
        self.index_name = index_name
        self.embedding_model = embedding_model
        self.dimension = dimension
        
        # Initialize Pinecone client
        self.pc = Pinecone(api_key=pinecone_api_key)
        
        # Initialize FREE sentence transformer model
        logger.info(f"Loading free embedding model: {embedding_model}")
        self.embedder = SentenceTransformer(embedding_model)
        
        # Use GPU if available for faster processing
        device = "cuda" if torch.cuda.is_available() else "cpu"
        self.embedder.to(device)
        logger.info(f"Using device: {device}")
        
        # Batch settings optimized for free tier
        self.batch_size = 100  # Vectors per batch to Pinecone
        self.embedding_batch_size = 32  # Local embedding batch size
        
        logger.info(f"✅ FREE TIER initialized for index: {index_name}")
        logger.info(f"📏 Embedding model: {embedding_model} ({dimension}D)")
    
    def create_index(self, cloud: str = "aws", region: str = "us-east-1"):
        """Create Pinecone index (uses free tier limit: 1 index)"""
        try:
            # Check if index exists
            existing_indexes = [idx.name for idx in self.pc.list_indexes()]
            
            if self.index_name in existing_indexes:
                logger.info(f"Index '{self.index_name}' already exists")
                return self.pc.Index(self.index_name)
            
            # Create new index with FREE tier specs
            logger.info(f"Creating FREE TIER index: {self.index_name}")
            self.pc.create_index(
                name=self.index_name,
                dimension=self.dimension,  # 384 for all-MiniLM-L6-v2
                metric="cosine",
                spec=ServerlessSpec(
                    cloud=cloud,
                    region=region
                )
            )
            
            # Wait for index to be ready
            logger.info("⏳ Waiting for index to be ready...")
            while not self.pc.describe_index(self.index_name).status['ready']:
                time.sleep(2)
            
            logger.info(f"✅ FREE TIER index '{self.index_name}' created successfully")
            return self.pc.Index(self.index_name)
            
        except Exception as e:
            logger.error(f"Failed to create index: {e}")
            logger.info("💡 Remember: Free tier allows only 1 index")
            raise
    
    def load_chunks(self, file_path: str = "atlan_docs_chunks.jsonl", 
                   max_chunks: int = 100000) -> Generator[Dict, None, None]:
        """Load chunks (with free tier limit consideration)"""
        try:
            count = 0
            with open(file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    if count >= max_chunks:
                        logger.info(f"🛑 Reached free tier limit: {max_chunks:,} chunks")
                        break
                        
                    try:
                        chunk = json.loads(line.strip())
                        yield chunk
                        count += 1
                    except json.JSONDecodeError as e:
                        logger.warning(f"Skipping invalid JSON at line {line_num}: {e}")
                        continue
                        
        except FileNotFoundError:
            logger.error(f"File not found: {file_path}")
            raise
    
    def prepare_text_for_embedding(self, chunk: Dict) -> str:
        """Prepare text for FREE embedding model (optimized for smaller context)"""
        text_parts = []
        
        # Main content (truncate for free model efficiency)
        content = chunk.get('content', '').strip()
        if content:
            # Truncate to ~500 chars for better free model performance
            if len(content) > 500:
                content = content[:500] + "..."
            text_parts.append(content)
        
        # Add concise context
        hierarchy = chunk.get('hierarchy', {})
        if hierarchy.get('l1_category') and hierarchy.get('l2_section'):
            context = f"{hierarchy['l1_category']} > {hierarchy['l2_section']}"
            text_parts.insert(0, context)
        
        return " | ".join(text_parts)
    
    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using FREE sentence-transformers model"""
        try:
            # Use the free model to generate embeddings
            logger.debug(f"Generating {len(texts)} embeddings locally (FREE)")
            
            embeddings = self.embedder.encode(
                texts,
                batch_size=self.embedding_batch_size,
                show_progress_bar=len(texts) > 100,
                convert_to_tensor=False,
                normalize_embeddings=True  # Good for cosine similarity
            )
            
            # Convert to list format for Pinecone
            if hasattr(embeddings, 'tolist'):
                embeddings = embeddings.tolist()
            
            return embeddings
            
        except Exception as e:
            logger.error(f"Failed to generate embeddings: {e}")
            raise
    
    def prepare_metadata(self, chunk: Dict) -> Dict[str, Any]:
        """Prepare metadata (optimized for free tier storage limits)"""
        # Simplified metadata to stay within free tier limits
        metadata = {
            # Essential fields only
            'url': chunk['url'],
            'site': chunk['site'],
            'preview': chunk['content_preview'][:300],  # Shorter preview
            
            # Key hierarchy fields
            'category': chunk['hierarchy']['l1_category'] or '',
            'section': chunk['hierarchy']['l2_section'] or '',
            
            # Content type
            'type': chunk['doc_classification']['primary_type'],
            'level': chunk['doc_classification']['technical_level'],
            
            # Important features
            'has_code': chunk['content_features']['has_code'],
            'has_api': chunk['content_features']['has_api_endpoints'],
            'has_steps': chunk['content_features']['has_numbered_steps'],
            
            # Priority for ranking
            'priority': round(chunk['relevance_scoring']['priority_score'], 2),
            'is_connector': chunk['relevance_scoring']['is_connector_doc'],
            
            # Basic chunk info
            'chunk_type': chunk['chunk_context']['chunk_type'],
            'tokens': chunk['chunk_context']['token_count'],
        }
        
        # Add key connector info if available
        if chunk['site'] == 'docs' and 'product_context' in chunk:
            pc = chunk['product_context']
            if pc.get('connector_name'):
                metadata['connector'] = pc['connector_name']
        
        return metadata
    
    def ingest_chunks(self, file_path: str = "atlan_docs_chunks.jsonl", 
                     max_chunks: int = 100000, dry_run: bool = False):
        """FREE TIER ingestion with limits"""
        try:
            # Create/get index
            if not dry_run:
                index = self.create_index()
            
            logger.info(f"🆓 Starting FREE TIER ingestion (max {max_chunks:,} chunks)")
            
            # Process chunks in batches
            chunks_processed = 0
            vectors_batch = []
            texts_for_embedding = []
            
            chunk_generator = self.load_chunks(file_path, max_chunks)
            
            with tqdm(desc="Processing chunks (FREE TIER)") as pbar:
                for chunk in chunk_generator:
                    # Prepare text for embedding
                    embedding_text = self.prepare_text_for_embedding(chunk)
                    texts_for_embedding.append(embedding_text)
                    
                    # Prepare metadata
                    metadata = self.prepare_metadata(chunk)
                    
                    # Store chunk info for batching
                    vectors_batch.append({
                        'id': chunk['id'],
                        'metadata': metadata,
                        'text': embedding_text
                    })
                    
                    chunks_processed += 1
                    
                    # Process batch when full
                    if len(vectors_batch) >= self.batch_size:
                        if not dry_run:
                            self._process_batch(index, vectors_batch, texts_for_embedding)
                        else:
                            logger.info(f"[DRY RUN] Would process batch of {len(vectors_batch)} vectors")
                        
                        vectors_batch = []
                        texts_for_embedding = []
                        
                        # Add small delay to be respectful to free tier
                        time.sleep(0.1)
                    
                    pbar.update(1)
                
                # Process remaining batch
                if vectors_batch:
                    if not dry_run:
                        self._process_batch(index, vectors_batch, texts_for_embedding)
                    else:
                        logger.info(f"[DRY RUN] Would process final batch of {len(vectors_batch)} vectors")
            
            if not dry_run:
                # Get final index stats
                stats = index.describe_index_stats()
                logger.info(f"✅ FREE TIER ingestion completed!")
                logger.info(f"   📊 Total vectors: {stats.total_vector_count:,}")
                logger.info(f"   📏 Dimension: {stats.dimension}")
                logger.info(f"   🆓 Using FREE models only")
            else:
                logger.info(f"✅ Dry run completed! Would process {chunks_processed:,} chunks")
            
        except Exception as e:
            logger.error(f"Ingestion failed: {e}")
            raise
    
    def _process_batch(self, index, vectors_batch: List[Dict], texts: List[str]):
        """Process a batch of vectors"""
        try:
            # Generate embeddings locally (FREE)
            embeddings = self.generate_embeddings_batch(texts)
            
            # Prepare vectors for upsert
            vectors_to_upsert = []
            for i, vector_data in enumerate(vectors_batch):
                vectors_to_upsert.append({
                    'id': vector_data['id'],
                    'values': embeddings[i],
                    'metadata': vector_data['metadata']
                })
            
            # Upsert to Pinecone
            upsert_response = index.upsert(vectors=vectors_to_upsert)
            
            logger.debug(f"🆓 Upserted {len(vectors_to_upsert)} vectors (FREE)")
            
        except Exception as e:
            logger.error(f"Failed to process batch: {e}")
            raise
    
    def query_test(self, query: str, top_k: int = 5, filter_dict: Dict = None):
        """Test query using FREE embedding model"""
        try:
            index = self.pc.Index(self.index_name)
            
            # Generate query embedding using FREE model
            query_embedding = self.generate_embeddings_batch([query])[0]
            
            # Query Pinecone
            results = index.query(
                vector=query_embedding,
                top_k=top_k,
                include_metadata=True,
                filter=filter_dict
            )
            
            print(f"\n🔍 FREE TIER Query: '{query}'")
            print(f"📊 Found {len(results.matches)} results:")
            
            for i, match in enumerate(results.matches, 1):
                print(f"\n{i}. Score: {match.score:.3f}")
                print(f"   URL: {match.metadata['url']}")
                print(f"   Type: {match.metadata['type']} ({match.metadata['site']})")
                print(f"   Content: {match.metadata['preview'][:150]}...")
            
            return results
            
        except Exception as e:
            logger.error(f"Query test failed: {e}")
            raise


def main():
    """Main execution for FREE TIER"""
    import argparse
    
    parser = argparse.ArgumentParser(description="FREE TIER: Ingest Atlan docs to Pinecone")
    parser.add_argument("--pinecone-key", default="key", help="Pinecone API key (free tier)")
    parser.add_argument("--index-name", default="atlan-docs-free", help="Index name")
    parser.add_argument("--input-file", default="atlan_docs_chunks.jsonl", help="Input file")
    parser.add_argument("--max-chunks", type=int, default=100000, help="Max chunks (free tier limit)")
    parser.add_argument("--dry-run", action="store_true", help="Test run")
    parser.add_argument("--test-query", help="Test query after ingestion")
    
    args = parser.parse_args()
    
    # Initialize FREE TIER ingester
    ingester = AtlanDocsPineconeFreeIngester(
        pinecone_api_key=args.pinecone_key,
        index_name=args.index_name
    )
    
    try:
        ingester.ingest_chunks(
            file_path=args.input_file,
            max_chunks=args.max_chunks,
            dry_run=args.dry_run
        )
        
        # Test query if provided
        if args.test_query and not args.dry_run:
            ingester.query_test(args.test_query)
            
    except KeyboardInterrupt:
        logger.info("Ingestion cancelled by user")
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())