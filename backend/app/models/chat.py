"""Chat-related Pydantic models."""
from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from enum import Enum


class TopicTag(str, Enum):
    """Classification topic tags."""
    HOW_TO = "How-to"
    PRODUCT = "Product"
    CONNECTOR = "Connector"
    LINEAGE = "Lineage"
    API_SDK = "API/SDK"
    SSO = "SSO"
    GLOSSARY = "Glossary"
    BEST_PRACTICES = "Best practices"
    SENSITIVE_DATA = "Sensitive data"
    ISSUE_REPORT = "Issue report"
    FEATURE_REQUEST = "Feature request"
    OTHER = "Other"


class Sentiment(str, Enum):
    """User sentiment classification."""
    FRUSTRATED = "Frustrated"
    CURIOUS = "Curious"
    ANGRY = "Angry"
    NEUTRAL = "Neutral"
    POSITIVE = "Positive"


class Priority(str, Enum):
    """Ticket priority levels."""
    P0 = "P0 (High)"
    P1 = "P1 (Medium)"
    P2 = "P2 (Low)"


class QueryRequest(BaseModel):
    """Request model for user queries."""
    query: str = Field(..., description="User's support query", min_length=1, max_length=2000)
    session_id: Optional[str] = Field(None, description="Optional session ID for conversation tracking")


class Classification(BaseModel):
    """Internal classification analysis."""
    topic_tags: List[TopicTag] = Field(..., description="Classified topic tags")
    sentiment: Sentiment = Field(..., description="Detected user sentiment")
    priority: Priority = Field(..., description="Assigned ticket priority")
    reasoning: str = Field(..., description="Reasoning for the classification")


class Document(BaseModel):
    """Retrieved document from vector search."""
    content: str = Field(..., description="Document content")
    url: str = Field(..., description="Source URL")
    title: str = Field(..., description="Document title")
    score: float = Field(..., description="Relevance score")


class RAGResponse(BaseModel):
    """RAG-generated response."""
    answer: str = Field(..., description="Generated answer")
    sources: List[Document] = Field(..., description="Supporting documents")
    confidence: float = Field(..., description="Response confidence score")


class RoutingMessage(BaseModel):
    """Simple routing message for non-RAG topics."""
    message: str = Field(..., description="Routing message")
    team: str = Field(..., description="Target team or department")


class InternalAnalysis(BaseModel):
    """Internal analysis view."""
    classification: Classification


class FinalResponse(BaseModel):
    """Final response view."""
    response_type: Literal["rag_answer", "routing_message"] = Field(..., description="Type of response")
    rag_response: Optional[RAGResponse] = Field(None, description="RAG response if applicable")
    routing_response: Optional[RoutingMessage] = Field(None, description="Routing message if applicable")


class ChatbotResponse(BaseModel):
    """Complete chatbot response."""
    internal_analysis: InternalAnalysis
    final_response: FinalResponse
    session_id: str = Field(..., description="Session identifier")
    timestamp: str = Field(..., description="Response timestamp")