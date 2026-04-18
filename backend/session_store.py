"""
Session Store — In-Memory Org Credential Management
=====================================================
Stores per-session org credentials (API token + org ID) in memory.
No disk writes, no logging of credentials, no cross-session leakage.

Security model:
  - Each session is identified by a UUID token generated server-side
  - Credentials are stored only in this Python dict — never on disk
  - Container restart (Railway deploy, crash, idle) wipes all sessions
  - Sessions expire after SESSION_TTL_SECONDS of inactivity
  - The session token is stored in the browser's sessionStorage (cleared on tab close)
"""

import time
import uuid
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 8 * 3600  # 8 hours inactivity timeout


@dataclass
class SessionCredentials:
    org_id:    str
    api_token: str
    org_name:  str = ""
    org_role:  str = ""                       # "admin" | "write" | "helpdesk" | "installer" | "observer" | ...
    api_base:  str = "https://api.mist.com"   # cloud API base for this session
    portal_base: str = "https://manage.mist.com"  # paired portal base for deep-links
    created_at: float = field(default_factory=time.time)
    last_used:  float = field(default_factory=time.time)
    selected_site_ids: list = field(default_factory=list)

    # Role-based capability flags — computed from org_role.
    # Conservative default: write capability requires "admin" or "write" role.
    # helpdesk/installer/observer/unknown → read-only for remediation actions.
    WRITE_CAPABLE_ROLES: tuple = ("admin", "write")

    @property
    def can_write(self) -> bool:
        return self.org_role.lower() in self.WRITE_CAPABLE_ROLES


class SessionStore:
    def __init__(self):
        self._sessions: dict = {}

    def create(
        self,
        org_id: str,
        api_token: str,
        org_name: str = "",
        org_role: str = "",
        api_base: str = "https://api.mist.com",
        portal_base: str = "https://manage.mist.com",
    ) -> str:
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = SessionCredentials(
            org_id=org_id,
            api_token=api_token,
            org_name=org_name,
            org_role=org_role,
            api_base=api_base,
            portal_base=portal_base,
        )
        logger.info(
            f"Session created for org {org_id[:8]}... "
            f"(session {session_id[:8]}..., role={org_role}, api_base={api_base})"
        )
        return session_id

    def get(self, session_id: str):
        creds = self._sessions.get(session_id)
        if creds is None:
            return None
        if time.time() - creds.last_used > SESSION_TTL_SECONDS:
            self.delete(session_id)
            return None
        creds.last_used = time.time()
        return creds

    def update_org_name(self, session_id: str, org_name: str) -> None:
        if session_id in self._sessions:
            self._sessions[session_id].org_name = org_name

    def update_selected_sites(self, session_id: str, site_ids: list) -> None:
        if session_id in self._sessions:
            self._sessions[session_id].selected_site_ids = site_ids

    def delete(self, session_id: str) -> None:
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"Session {session_id[:8]}... deleted")

    def cleanup_expired(self) -> int:
        now = time.time()
        expired = [
            sid for sid, creds in self._sessions.items()
            if now - creds.last_used > SESSION_TTL_SECONDS
        ]
        for sid in expired:
            del self._sessions[sid]
        return len(expired)

    @property
    def active_count(self) -> int:
        return len(self._sessions)


session_store = SessionStore()
