"""FastAPI application for Nora chatbot."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings
from .api.routes import chat, bulk
from .dependencies.agent import init_agent

# Configure logging
logging.basicConfig(
    level=logging.INFO if settings.debug else logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting Nora chatbot application...")
    try:
        init_agent()
        logger.info("Nora agent initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize application: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down Nora chatbot application...")
    

# Create FastAPI app
app = FastAPI(
    title="Nora - Atlan Support Chatbot",
    description="Intelligent customer support chatbot for Atlan using LangGraph and RAG",
    version="1.0.0",
    lifespan=lifespan
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(chat.router)
app.include_router(bulk.router)

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Welcome to Nora - Atlan Support Chatbot",
        "version": "1.0.0",
        "endpoints": {
            "chat": "/chat - Main chatbot endpoint",
            "bulk": "/bulk - Bulk classification",
            "docs": "/docs - API documentation"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )