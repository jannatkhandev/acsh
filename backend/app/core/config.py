"""Configuration settings for Nora chatbot."""
from typing import Optional
from pydantic import Field, validator
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    """Application settings with validation."""
    
    # Google AI Configuration
    google_api_key: str = Field(..., env="GOOGLE_API_KEY", description="Google AI API key")
    
    # Pinecone Configuration
    pinecone_api_key: str = Field(..., env="PINECONE_API_KEY", description="Pinecone API key") 
    pinecone_index_name: str = Field(
        default="atlan-docs-free", 
        env="PINECONE_INDEX_NAME",
        description="Pinecone index name"
    )
    
    # Server Configuration
    host: str = Field(default="0.0.0.0", env="HOST")
    port: int = Field(default=8000, env="PORT", ge=1, le=65535)
    debug: bool = Field(default=False, env="DEBUG")
    
    # LangSmith Configuration (optional)
    langchain_tracing_v2: bool = Field(default=False, env="LANGCHAIN_TRACING_V2")
    langchain_api_key: Optional[str] = Field(default=None, env="LANGCHAIN_API_KEY")
    langsmith_endpoint: Optional[str] = Field(default=None, env="LANGCHAIN_ENDPOINT")
    langsmith_project: Optional[str] = Field(default=None, env="LANGCHAIN_PROJECT")

    # Model Settings
    default_model: str = Field(
        default="gemini-1.5-flash", 
        env="DEFAULT_MODEL",
        description="Default LLM model"
    )
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2", 
        env="EMBEDDING_MODEL",
        description="Embedding model for vector search"
    )

    # CORS Settings
    allowed_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"], 
        env="ALLOWED_ORIGINS"
    )
    
    @validator('allowed_origins', pre=True)
    def parse_allowed_origins(cls, v):
        """Parse comma-separated origins from env var."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(',')]
        return v
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()