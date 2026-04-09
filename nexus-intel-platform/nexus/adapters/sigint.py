from nexus.adapters.base import BaseAdapter
from nexus.models import IntelEvent, ClassificationLevel, ThreatTier, IntSource
import re, hashlib
from datetime import datetime, timezone


class SigintAdapter(BaseAdapter):
    """
    Normalizes SIGINT intercept records.
    Input: raw intercept text with embedded DTG, FLASH marker, and
           optional geographic metadata (MGRS or lat/lon).
    Output: IntelEvent with normalized prose + extracted geo.
    """

    # Regex for Date-Time-Group: DDHHMM[Z]MMMYY
    DTG_RE = re.compile(
        r'(\d{2})(\d{2})(\d{2})Z\s*(JAN|FEB|MAR|APR|MAY|JUN|'
        r'JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})',
        re.IGNORECASE
    )
    FLASH_RE  = re.compile(r'FLASH\s*[:\-]?\s*', re.IGNORECASE)
    LATLON_RE = re.compile(r'(\d{1,3}\.\d+)[NS][,\s]+(\d{1,3}\.\d+)[EW]')

    async def normalize(self, raw) -> IntelEvent:
        text = raw.raw_text.strip()

        # Extract DTG -> event_time
        dtg_match  = self.DTG_RE.search(text)
        event_time = datetime.now(timezone.utc)
        if dtg_match:
            event_time = self._parse_dtg(*dtg_match.groups())

        # Strip FLASH prefix from normalized text
        clean = self.FLASH_RE.sub("", text).strip()

        # Extract lat/lon if present
        geo_lat = geo_lon = None
        geo_m   = self.LATLON_RE.search(text)
        if geo_m:
            geo_lat = float(geo_m.group(1))
            geo_lon = float(geo_m.group(2))

        # Determine threat tier from signal priority keywords
        tier = self._classify_tier(clean)

        return IntelEvent(
            source_id        = raw.source_id,
            int_type         = IntSource.SIGINT,
            event_time       = event_time,
            classification   = ClassificationLevel(
                raw.metadata.get("classification", "SECRET")
            ),
            threat_tier      = tier,
            raw_text         = raw.raw_text,
            normalized_text  = clean,
            geo_lat          = geo_lat,
            geo_lon          = geo_lon,
            metadata         = raw.metadata,
            fingerprint      = hashlib.sha256(
                (raw.source_id + raw.raw_text).encode()
            ).hexdigest(),
        )

    def _classify_tier(self, text: str) -> ThreatTier:
        txt = text.lower()
        if any(k in txt for k in ("imminent", "attack", "strike", "flash")):
            return ThreatTier.CRITICAL
        if any(k in txt for k in ("movement", "surveillance", "observed")):
            return ThreatTier.HIGH
        return ThreatTier.MEDIUM

    @staticmethod
    def _parse_dtg(dd, hh, mm, mon, yy) -> datetime:
        mon_map = {
            "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4,
            "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
            "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
        }
        return datetime(
            2000 + int(yy), mon_map[mon.upper()], int(dd),
            int(hh), int(mm), tzinfo=timezone.utc
        )
