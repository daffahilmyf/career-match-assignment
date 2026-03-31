from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from pelgo.ports.pii import PIIRedactor

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
LINKEDIN_RE = re.compile(r"linkedin\.com/in/\S+", re.IGNORECASE)
GITHUB_RE = re.compile(r"github\.com/\S+", re.IGNORECASE)
LOCATION_RE = re.compile(
    r"\b\d{1,5}\s+[A-Za-z0-9.'-]+(?:\s+[A-Za-z0-9.'-]+){0,5},?\s+(?:street|st|road|rd|avenue|ave|boulevard|blvd|lane|ln|drive|dr)\b",
    re.IGNORECASE,
)

FIELD_PLACEHOLDERS = {
    "name": "[REDACTED_NAME]",
    "email": "[REDACTED_EMAIL]",
    "phone": "[REDACTED_PHONE]",
    "phone_number": "[REDACTED_PHONE]",
    "address": "[REDACTED_ADDRESS]",
    "location": "[REDACTED_LOCATION]",
    "linkedin": "[REDACTED_URL]",
    "github": "[REDACTED_URL]",
    "website": "[REDACTED_URL]",
}


class SimplePIIRedactor(PIIRedactor):
    def redact_text(self, text: str) -> str:
        redacted = EMAIL_RE.sub("[REDACTED_EMAIL]", text)
        redacted = PHONE_RE.sub("[REDACTED_PHONE]", redacted)
        redacted = URL_RE.sub("[REDACTED_URL]", redacted)
        redacted = LINKEDIN_RE.sub("[REDACTED_URL]", redacted)
        redacted = GITHUB_RE.sub("[REDACTED_URL]", redacted)
        redacted = LOCATION_RE.sub("[REDACTED_ADDRESS]", redacted)
        return redacted

    def redact_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        profile_copy = deepcopy(profile)
        candidate_name = profile_copy.get("name") if isinstance(profile_copy.get("name"), str) else None
        redacted = self._redact_value(profile_copy, candidate_name)
        if not isinstance(redacted, dict):
            return {}
        if candidate_name:
            redacted["name"] = "[REDACTED_NAME]"
        if isinstance(redacted.get("email"), str):
            redacted["email"] = "[REDACTED_EMAIL]"
        return redacted

    def _redact_value(self, value: Any, candidate_name: str | None) -> Any:
        if isinstance(value, dict):
            updated: dict[str, Any] = {}
            for key, item in value.items():
                placeholder = FIELD_PLACEHOLDERS.get(key.lower())
                if placeholder is not None and item is not None:
                    updated[key] = placeholder
                else:
                    updated[key] = self._redact_value(item, candidate_name)
            return updated
        if isinstance(value, list):
            return [self._redact_value(item, candidate_name) for item in value]
        if isinstance(value, str):
            redacted = self.redact_text(value)
            if candidate_name:
                redacted = re.sub(re.escape(candidate_name), "[REDACTED_NAME]", redacted, flags=re.IGNORECASE)
            return redacted
        return value
