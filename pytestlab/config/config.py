from __future__ import annotations

from pydantic import BaseModel


class Config(BaseModel):
    """Shared Pydantic base with legacy JSON-compatible serialization."""

    def to_json(self) -> dict:
        """Return the model as JSON-compatible Python values."""
        return self.model_dump(mode="json")


class BaseConfig(Config):
    """Base class for PyTestLab device and instrument configuration models."""
