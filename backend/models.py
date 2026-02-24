# backend/models.py
import os
from dotenv import load_dotenv

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.mysql import LONGBLOB
from datetime import datetime
import urllib.parse
import enum

load_dotenv()

# ---------------------------------------------------------
#   DATABASE CONFIG
# ---------------------------------------------------------
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "admin123")
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_DB = os.getenv("MYSQL_DB", "decentralised_voting")

encoded_pass = urllib.parse.quote_plus(MYSQL_PASSWORD)

DATABASE_URL = (
    f"mysql+pymysql://{MYSQL_USER}:{encoded_pass}@"
    f"{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
)

# ---------------------------------------------------------
#   ENGINE + BASE
# ---------------------------------------------------------
engine = create_engine(DATABASE_URL, echo=False)
Base = declarative_base()


# ---------------------------------------------------------
#   ENUMS
# ---------------------------------------------------------
class ElectionPhase(enum.Enum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    RESULT_DECLARED = "RESULT_DECLARED"


# ---------------------------------------------------------
#   MODELS
# ---------------------------------------------------------
class Admin(Base):
    __tablename__ = "admin"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(300), nullable=False)
    face_encoding = Column(LONGBLOB, nullable=False)


class Voter(Base):
    __tablename__ = "voters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    enrollment = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    face_encoding = Column(LONGBLOB, nullable=False)


class Election(Base):
    """
    Local cache of elections (source of truth is blockchain)
    """
    __tablename__ = "elections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    blockchain_id = Column(Integer, unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    phase = Column(String(50), default="CREATED")
    total_candidates = Column(Integer, default=0)
    total_votes = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    is_live_results = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "blockchain_id": self.blockchain_id,
            "name": self.name,
            "description": self.description,
            "phase": self.phase,
            "total_candidates": self.total_candidates,
            "total_votes": self.total_votes,
            "is_live_results": self.is_live_results,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
        }


class VoteReceipt(Base):
    """
    Vote receipts for verification (no vote choice stored)
    """
    __tablename__ = "vote_receipts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    receipt_id = Column(Integer, unique=True, nullable=False)
    election_id = Column(Integer, nullable=False)
    enrollment_hash = Column(String(66), nullable=False)
    visible_tag = Column(String(20), nullable=False)
    tx_hash = Column(String(66), nullable=False)
    block_number = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    verified_on_chain = Column(Boolean, default=True)

    def to_dict(self):
        return {
            "receipt_id": self.receipt_id,
            "election_id": self.election_id,
            "visible_tag": self.visible_tag,
            "tx_hash": self.tx_hash,
            "block_number": self.block_number,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "verified": self.verified_on_chain,
        }


class VoterElectionRegistration(Base):
    """
    Track which voters are registered for which elections
    """
    __tablename__ = "voter_election_registrations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    voter_id = Column(Integer, nullable=False)
    election_id = Column(Integer, nullable=False)
    enrollment = Column(String(50), nullable=False)
    face_hash = Column(String(66), nullable=False)
    registered_at = Column(DateTime, default=datetime.utcnow)
    has_voted = Column(Boolean, default=False)


# ---------------------------------------------------------
#   CREATE TABLES IF NOT EXISTS
# ---------------------------------------------------------
Base.metadata.create_all(engine)

# ---------------------------------------------------------
#   SESSION FACTORY
# ---------------------------------------------------------
SessionLocal = sessionmaker(bind=engine)

print("[OK] Database connected & models ready (V2 with Elections)")
