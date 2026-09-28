from sqlalchemy import String, Column, DateTime, Float, JSON, Boolean,TIMESTAMP
from app.db.base import Base
from uuid import uuid4 

class Event(Base):
    __tablename__ = 'event'
    id = Column(String, primary_key=True)
    timestamp = Column(TIMESTAMP)
    camera_id = Column(String)
    event_type = Column(String)
    pid = Column(String)
    bid = Column(String)
    confidence = Column(Float)
    zone = Column(String)
    image_path = Column(String)
    resolved = Column(Boolean)
