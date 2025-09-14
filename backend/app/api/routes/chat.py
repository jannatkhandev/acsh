"""Chat routes."""
import json
import logging
from typing import AsyncGenerator
from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse

from ...models import QueryRequest, ChatbotResponse
from ...dependencies.agent import AgentDep

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/chat",
    tags=["chat"]
)

@router.post("/")
async def chat(request: QueryRequest, agent: AgentDep):
    """Live chat endpoint with SSE streaming."""
    logger.info(f"Processing live query: {request.query[:100]}...")
    
    async def generate_events() -> AsyncGenerator[str, None]:
        try:
            # Process query with streaming
            async for event in agent.process_query_stream(request.query, request.session_id):
                event_data = json.dumps(event, default=str)
                yield f"data: {event_data}\n\n"
        except Exception as e:
            logger.error(f"Error in live chat stream: {e}")
            error_event = json.dumps({"type": "error", "message": str(e)})
            yield f"data: {error_event}\n\n"
    
    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
