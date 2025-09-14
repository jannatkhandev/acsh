"""Fixed document search tool that returns structured, unique, and content-loaded data."""
import asyncio
import logging
from typing import List, Dict, Any

from bs4 import SoupStrainer
from langchain_community.document_loaders import WebBaseLoader
from langchain_core.tools import tool
from pinecone import Pinecone
from sentence_transformers import SentenceTransformer

from ....dependencies.config import get_settings

# --- Setup & Initialization ---
logger = logging.getLogger(__name__)
settings = get_settings()

# Initialize shared resources ONCE to be reused across tool calls.
# This is efficient and prevents reloading models/re-establishing connections.

_pc = Pinecone(api_key=settings.pinecone_api_key)
_index = _pc.Index(settings.pinecone_index_name)
_embedder = SentenceTransformer(settings.embedding_model)

async def _load_single_doc_content(doc: Dict[str, Any]) -> str:
    """
    Asynchronously loads content from a single document's URL.
    Returns the full content on success, or the preview content on failure.
    """
    url = doc.get("url")
    fallback_content = doc.get("content", "") # Use the preview as a fallback

    if not url:
        return fallback_content

    try:
        # Define site-specific CSS selectors for precise content extraction
        bs_kwargs = {
            "docs.atlan.com": {"parse_only": SoupStrainer(class_="theme-doc-markdown markdown")},
            "developer.atlan.com": {"parse_only": SoupStrainer("article")},
        }
        # Use a general selector for other domains
        default_strainer = SoupStrainer(["main", "article", "div[role=main]"])
        
        # Select the appropriate strainer based on the URL
        selected_bs_kwargs = next(
            (kwargs for domain, kwargs in bs_kwargs.items() if domain in url),
            {"parse_only": default_strainer},
        )

        loader = WebBaseLoader(
            web_paths=[url],
            bs_kwargs=selected_bs_kwargs,
            bs_get_text_kwargs={"separator": " ", "strip": True},
        )

        # Run the blocking I/O `load` operation in a separate thread
        loop = asyncio.get_event_loop()
        documents = await loop.run_in_executor(None, loader.load)

        if documents and documents[0].page_content:
            content = documents[0].page_content.strip()
            # Truncate content to a reasonable max length to avoid oversized outputs
            return content[:8000]
        
        logger.warning(f"No content extracted from {url}, using preview.")
        return fallback_content

    except Exception as e:
        logger.warning(f"Failed to load URL {url}, using preview. Error: {e}")
        return fallback_content


@tool
async def document_search_tool(query: str, top_k: int = 5) -> Dict[str, Any]:
    """
    Searches for relevant Atlan documentation, fetches unique URLs, and returns a list 
    of documents augmented with their full content.

    Rules for an optimal search query:
      - Use key technical terms and concepts (e.g., "Azure AD SSO setup").
      - Remove generic words or company names (e.g., remove "Atlan", "how to").
      - Focus on the core action or topic (e.g., "Snowflake connector setup").
    
    Args:
        query: The optimized search query string.
        top_k: The number of results to retrieve from the vector search.
    
    Returns:
        A list of dictionaries, where each dictionary represents a unique document
        with its metadata and the fully loaded page content.
        Example:
        [
            {
                "title": "Connectors > Snowflake",
                "url": "https://docs.atlan.com/...",
                "content": "To set up the Snowflake connector...",
                "score": 0.85
            }
        ]
    """
    if not _index or not _embedder:
        logger.error("Document search tool is not initialized. Cannot perform search.")
        return []

    try:
        loop = asyncio.get_event_loop()

        # 1. Generate query embedding (CPU-bound, run in executor)
        query_embedding = await loop.run_in_executor(
            None,
            lambda: _embedder.encode([query], normalize_embeddings=True)[0].tolist()
        )

        # 2. Query Pinecone for relevant documents (I/O-bound, run in executor)
        results = await loop.run_in_executor(
            None,
            lambda: _index.query(
                vector=query_embedding, top_k=top_k, include_metadata=True
            ),
        )

        # 3. Process and deduplicate results based on URL
        unique_docs = []
        seen_urls = set()
        for match in results.get("matches", []):
            meta = match.get("metadata", {})
            url = meta.get("url")
            # Ensure the document has a URL and we haven't seen it before
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_docs.append({
                    "title": f"{meta.get('category', 'Docs')} > {meta.get('section', 'General')}".strip(" > "),
                    "url": url,
                    "content": meta.get("preview", "")[:300], # Keep preview as a fallback
                    "score": float(match.score)
                })
        
        if not unique_docs:
            logger.info(f"No unique documents found for query: '{query}'")
            return []

        # 4. Concurrently load the full content for the unique documents
        loading_tasks = [_load_single_doc_content(doc) for doc in unique_docs]
        full_contents = await asyncio.gather(*loading_tasks)

        # 5. Augment the documents with their newly loaded content
        for i, doc in enumerate(unique_docs):
            doc["content"] = full_contents[i] # Replace preview with full content

        logger.info(f"Found and loaded {len(unique_docs)} documents for query: '{query}'")
        return {"retrieved_docs": unique_docs}

    except Exception as e:
        logger.error(f"Document search failed for query '{query}': {e}", exc_info=True)
        return [] # Return an empty list on any unexpected error