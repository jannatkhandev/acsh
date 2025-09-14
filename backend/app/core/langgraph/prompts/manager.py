import logging
from functools import lru_cache
from langchain_core.prompts import PromptTemplate
from langsmith import Client
from . import templates
from ...config import settings

logger = logging.getLogger(__name__)


class PromptManager:
    """Manages fetching prompts from LangSmith Hub with local fallbacks."""

    def __init__(self):
        self.client = Client(api_key=settings.langchain_api_key)

    # LRU Cache decorator is added so that when called subsequently the method must returned cached value instead of re-fetching
    @lru_cache
    def get_prompt(self, name: str) -> PromptTemplate:
        """
        Fetches a prompt by its name.

        Tries to pull from LangSmith Hub first. If that fails, it constructs
        a PromptTemplate from the local fallback in templates.py.
        """

        try:
            # 1. Try to pull from the Hub
            pulled_prompt = self.client.pull_prompt(name)
            logger.info(f"Successfully pulled prompt '{name}' from LangSmith Hub.")
            return pulled_prompt
        except Exception as e:
            # 2. On any failure, use the local fallback
            logger.warning(
                f"Could not pull prompt '{name}' from Hub. "
                f"Reason: {e}. Using local fallback."
            )
            fallback_template_str = getattr(templates, name.upper(), None)
            if fallback_template_str is None:
                raise ValueError(f"Fallback prompt for '{name}' not found in templates.py")

            return PromptTemplate.from_template(fallback_template_str)

@lru_cache()
def get_prompt_manager():
    return PromptManager()