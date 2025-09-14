"""Search-related Pydantic models."""
from typing import List
from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """Search request model."""
    query: str = Field(..., description="Search query", min_length=1)
    top_k: int = Field(default=5, description="Number of results to return", ge=1, le=20)


class SearchResult(BaseModel):
    """Search result model."""
    content: str = Field(..., description="Document content")
    url: str = Field(..., description="Source URL")
    title: str = Field(..., description="Document title")
    score: float = Field(..., description="Relevance score")


class SearchResponse(BaseModel):
    """Search response model."""
    query: str = Field(..., description="Original search query")
    results: List[SearchResult] = Field(..., description="Search results")