from typing import List, Dict, AsyncIterator, Tuple
from app.core.langgraph.prompts.manager import get_prompt_manager
from langchain_google_genai import ChatGoogleGenerativeAI

from ..config import settings
from ...models import Classification, TopicTag, Sentiment, Priority

class TicketClassifier:
    def __init__(self):
        self.llm = ChatGoogleGenerativeAI(
            model=settings.default_model,
            google_api_key=settings.google_api_key,
            temperature=0
        )
        self.prompt_manager = get_prompt_manager()
        self._structured_llm = self.llm.with_structured_output(Classification)
    
    async def classify(self, query: str) -> Classification:
        """Single classification - used by both chat and bulk"""
        try:
            # 1. Pull the prompt object from the LangSmith Hub
            classification_prompt = self.prompt_manager.get_prompt("classification_prompt")

            # 2. Create the chain by piping the prompt into the structured LLM
            chain = classification_prompt | self._structured_llm

            # 3. Invoke the chain with the query variable
            return await chain.ainvoke({"query": query})
    
        except Exception as e:
            return Classification(
                topic_tags=[TopicTag.OTHER],
                sentiment=Sentiment.NEUTRAL,
                priority=Priority.P2,
                reasoning="Classification failed"
            )
