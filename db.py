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
        
        # Auto-format URL if just the project ref was provided
        url = SUPABASE_URL
        if not url.startswith("http"):
            url = f"https://{url}.supabase.co"
            
        from supabase import create_client
        _client = create_client(url, SUPABASE_KEY)
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
def save_config(config: Dict[str, Any]) -> tuple[bool, str | None]:
    """
    Save a test configuration for future reuse.
    Returns (True, None) on success, (False, error_message) on failure.
    """
    try:
        client = get_client()
        if not client:
            return (
                False,
                "Supabase not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY in .env (local) or in Railway Variables (deploy).",
            )

        # Match schema: TEXT and REAL types; ensure numerics are float for Supabase
        row = {
            "finger_type": str(config.get("finger_type") or "").strip() or None,
            "finger_length": float(config.get("finger_length", 0) or 0),
            "finger_width": float(config.get("finger_width", 0) or 0),
            "body_material": str(config.get("body_material") or "").strip() or None,
            "skin_material": str(config.get("skin_material") or "").strip() or None,
            "speed": float(config.get("speed", 0) or 0),
            "prepared_by": str(config.get("prepared_by") or "").strip() or "",
        }

        # Persist dropdown values first so they exist for future loads
        if row["finger_type"]:
            add_finger_type(row["finger_type"])
        if row["body_material"]:
            add_material(row["body_material"], "body")
        if row["skin_material"]:
            add_material(row["skin_material"], "skin")

        # Insert; created_at uses DB default if we don't send it
        client.table(TABLE_SAVED_CONFIGS).insert(row).execute()
        return (True, None)
    except Exception as e:
        err_msg = str(e).strip() or repr(e)
        logger.warning("Failed to save config: %s", err_msg)
        return (False, err_msg)


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
