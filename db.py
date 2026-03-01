"""
Supabase database module for Finger Analysis Tool.

Stores and retrieves saved configurations (finger types, materials, etc.)
so users can quickly reuse previous settings.

Tables:
  - finger_types: dropdown values for finger selection
  - materials: body and skin material options
  - saved_configs: full test configurations for reuse
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = (
    os.getenv("SUPABASE_ANON_KEY", "") or os.getenv("SUPABASE_SERVICE_KEY", "")
)

TABLE_FINGER_TYPES = "finger_types"
TABLE_MATERIALS = "materials"
TABLE_SAVED_CONFIGS = "saved_configs"

_client = None


def get_client():
    """Get or create Supabase client. Returns None if credentials missing."""
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            return None
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


# ---------------------------------------------------------------------------
# Finger types
# ---------------------------------------------------------------------------
def get_finger_types() -> List[str]:
    """Fetch all saved finger type names."""
    try:
        client = get_client()
        if not client:
            return []
        result = (
            client.table(TABLE_FINGER_TYPES)
            .select("name")
            .order("name")
            .execute()
        )
        return [r["name"] for r in (result.data or [])]
    except Exception as e:
        logger.warning("Failed to load finger types: %s", e)
        return []


def add_finger_type(name: str) -> bool:
    """Add a new finger type if it doesn't exist."""
    try:
        client = get_client()
        if not client:
            return False
        client.table(TABLE_FINGER_TYPES).upsert(
            {"name": name.strip()}, on_conflict="name"
        ).execute()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Materials (body + skin)
# ---------------------------------------------------------------------------
def get_materials(material_type: str = "body") -> List[str]:
    """Fetch saved material names. material_type is 'body' or 'skin'."""
    try:
        client = get_client()
        if not client:
            return []
        result = (
            client.table(TABLE_MATERIALS)
            .select("name")
            .eq("type", material_type)
            .order("name")
            .execute()
        )
        return [r["name"] for r in (result.data or [])]
    except Exception:
        return []


def add_material(name: str, material_type: str = "body") -> bool:
    """Save a new material."""
    try:
        client = get_client()
        if not client:
            return False
        client.table(TABLE_MATERIALS).upsert(
            {"name": name.strip(), "type": material_type},
            on_conflict="name,type",
        ).execute()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Saved configurations
# ---------------------------------------------------------------------------
def save_config(config: Dict[str, Any]) -> bool:
    """Save a test configuration for future reuse."""
    try:
        client = get_client()
        if not client:
            return False

        row = {
            "finger_type": config.get("finger_type", ""),
            "finger_length": config.get("finger_length", 0),
            "body_material": config.get("body_material", ""),
            "skin_material": config.get("skin_material", ""),
            "speed": config.get("speed", 0),
            "prepared_by": config.get("prepared_by", ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # Persist dropdown values FIRST, so they are saved even if config insert fails
        if row["finger_type"]:
            add_finger_type(row["finger_type"])
        if row["body_material"]:
            add_material(row["body_material"], "body")
        if row["skin_material"]:
            add_material(row["skin_material"], "skin")

        # Now try to save the full configuration
        client.table(TABLE_SAVED_CONFIGS).insert(row).execute()

        return True
    except Exception as e:
        logger.warning("Failed to save config: %s", e)
        return False


def get_recent_configs(limit: int = 20) -> List[Dict]:
    """Fetch recent configurations for quick reuse."""
    try:
        client = get_client()
        if not client:
            return []
        result = (
            client.table(TABLE_SAVED_CONFIGS)
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception:
        return []
