"""SQLAlchemy declarative base and portable JSON storage type."""

from typing import Any, ClassVar

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[type, Any]] = {dict: JSON().with_variant(JSONB(), "postgresql")}
