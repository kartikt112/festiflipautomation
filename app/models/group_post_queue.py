"""Group post queue – FIFO cooldown for group chat messages per event."""

import enum
from sqlalchemy import Column, Integer, String, Date, DateTime, Enum as SAEnum
from sqlalchemy.sql import func

from app.database import Base


class PostStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    POSTED = "POSTED"
    EXPIRED = "EXPIRED"


class GroupPostQueue(Base):
    __tablename__ = "group_post_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sell_offer_id = Column(Integer, nullable=False, index=True)
    event_name = Column(String(255), nullable=False)
    event_date = Column(Date, nullable=True)
    message_body = Column(String(2000), nullable=False)
    status = Column(SAEnum(PostStatus), default=PostStatus.QUEUED, nullable=False)
    posted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
