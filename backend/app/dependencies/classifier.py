from typing import Annotated
from fastapi import Depends
from functools import lru_cache
from ..core.langgraph.classifier import TicketClassifier


@lru_cache
def get_classifier() -> TicketClassifier:
    return TicketClassifier()

ClassifierDep = Annotated[TicketClassifier, Depends(get_classifier)]
