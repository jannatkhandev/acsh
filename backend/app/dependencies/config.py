"""Configuration dependency management."""
from functools import lru_cache
from typing import Annotated
from fastapi import Depends

from ..core.config import Settings


@lru_cache
def get_settings() -> Settings:
    """Get application settings."""
    return Settings()


# Type alias for cleaner dependency injection  
SettingsDep = Annotated[Settings, Depends(get_settings)]