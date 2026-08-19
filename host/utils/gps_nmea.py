import re
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Set


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"

# NMEA 4.11 GSA sentences carry a trailing "GNSS System ID" field. Combined
# receivers emit one $GNGSA sentence per satellite system, all sharing the
# same "GN" talker, so this ID is the only way to tell them apart.
SYSTEM_ID_TO_CONSTELLATION = {
    "1": "GP",  # GPS
    "2": "GL",  # GLONASS
    "3": "GA",  # Galileo
    "4": "GB",  # BeiDou
    "5": "GQ",  # QZSS
    "6": "GI",  # NavIC / IRNSS
}

CONSTELLATION_NAMES = {
    "GP": "GPS",
    "GL": "GLONASS",
    "GA": "Galileo",
    "GB": "BeiDou",
    "GQ": "QZSS",
    "GI": "NavIC",
    "GN": "Combined",
}

# Drop a visible satellite from the display if it hasn't been re-reported in
# a GSV sentence within this many seconds (i.e. it has fallen out of view).
SATELLITE_TIMEOUT_SECONDS = 30.0


@dataclass
class GPSStatus:
    has_fix: bool = False
    fix_type: int = 0
    fix_quality: int = 0
    satellites: int = 0
    satellites_in_view: int = 0
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    geoidal_separation: Optional[float] = None
    speed_knots: Optional[float] = None
    course_deg: Optional[float] = None
    time_utc: Optional[str] = None
    date_utc: Optional[str] = None
    hdop: Optional[float] = None
    pdop: Optional[float] = None
    vdop: Optional[float] = None
    constellations: Set[str] = field(default_factory=set)
    constellation_stats: Dict[str, Dict[str, float | int | str]] = field(default_factory=dict)
    visible_satellites: Dict[str, list[dict]] = field(default_factory=dict)

    def _constellation_lines(self) -> list[str]:
        # "GN" is the combined multi-GNSS solution, already summarized by the
        # top-level Satellites/In view fields, so it's redundant here.
        names = sorted(name for name in self.constellations if name != "GN")
        if not names:
            return ["Constellations: none"]

        lines = ["Constellations:"]
        for name in names:
            stats = self.constellation_stats.get(name, {})
            sat_count = stats.get("satellites", 0)
            fix_label = stats.get("fix_mode", "")
            label = CONSTELLATION_NAMES.get(name, name)
            if fix_label:
                lines.append(f"  - {label}: {sat_count} sats, mode {fix_label}")
            else:
                lines.append(f"  - {label}: {sat_count} sats")
        return lines

    @staticmethod
    def _strip_ansi(text: str) -> str:
        return ANSI_RE.sub("", text)

    @staticmethod
    def _signal_bars(snr: Optional[int]) -> str:
        symbols = "▁▂▃▄▅▆▇█"
        if snr is None:
            return "—"
        if snr <= 0:
            return "▁"
        index = min(len(symbols) - 1, max(0, int(snr / 12)))
        return symbols[index]

    @staticmethod
    def _color_status(value: str, locked: bool) -> str:
        if locked:
            return f"{BOLD}{GREEN}{value}{RESET}"
        return f"{BOLD}{YELLOW}{value}{RESET}"

    def _fix_type_label(self) -> str:
        if self.fix_type >= 2:
            return f"{self.fix_type}D"
        if self.fix_type == 1:
            return "No fix"
        return "N/A"

    def _satellite_lines(self) -> list[str]:
        if not self.visible_satellites:
            return ["Visible sats: none"]

        lines = ["Visible sats:"]
        for constellation in sorted(self.visible_satellites):
            sats = self.visible_satellites[constellation]
            columns = []
            for sat in sats:
                prn = sat.get("prn")
                snr = sat.get("snr")
                if prn is None:
                    continue
                signal = self._signal_bars(snr)
                s = f"PRN{prn} {signal} {snr if snr is not None else '--'}dB"
                columns.append(s)
            if columns:
                # 5-column layout: show every tracked satellite, not just a subset
                row_size = 5
                for i in range(0, len(columns), row_size):
                    chunk = columns[i : i + row_size]
                    lines.append(f"  - {constellation}: {('  '.join(chunk))}")
        return lines

    def summary_lines(self) -> list[str]:
        status_text = "LOCKED" if self.has_fix else "SEARCHING"
        lines = [
            "GPS STATUS",
            "==========",
            f"Fix: {self._color_status(status_text, self.has_fix)}",
            f"Type: {self._fix_type_label()}",
            f"Quality: {self.fix_quality if self.fix_quality else 'N/A'}",
            f"Satellites: {self.satellites}",
            f"In view: {self.satellites_in_view}",
            f"UTC time: {self.time_utc or 'N/A'}",
            f"UTC date: {self.date_utc or 'N/A'}",
        ]

        if self.latitude is not None and self.longitude is not None:
            lat_dir = "N" if self.latitude >= 0 else "S"
            lon_dir = "E" if self.longitude >= 0 else "W"
            lines.append(
                f"Position: {abs(self.latitude):.5f} {lat_dir}, {abs(self.longitude):.5f} {lon_dir}"
            )
        if self.altitude is not None:
            lines.append(f"Altitude: {self.altitude:.2f} m")
        if self.geoidal_separation is not None:
            lines.append(f"Geoid sep: {self.geoidal_separation:.2f} m")
        if self.speed_knots is not None:
            lines.append(f"Speed: {self.speed_knots:.2f} kn")
        if self.course_deg is not None:
            lines.append(f"Course: {self.course_deg:.1f}°")
        if self.hdop is not None:
            lines.append(f"HDOP: {self.hdop:.2f}")
        if self.pdop is not None:
            lines.append(f"PDOP: {self.pdop:.2f}")
        if self.vdop is not None:
            lines.append(f"VDOP: {self.vdop:.2f}")

        lines.extend(self._constellation_lines())
        lines.extend(self._satellite_lines())
        return lines

    def render_dashboard(self) -> str:
        rows = self.summary_lines()
        width = max(len(self._strip_ansi(line)) for line in rows)
        top = "+" + ("-" * (width + 2)) + "+"
        body = [top]
        for line in rows:
            padding = width - len(self._strip_ansi(line))
            body.append(f"| {line}{' ' * padding} |")
        body.append(top)
        return "\n".join(body)


def _to_float(value: str) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_int(value: str) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _dms_to_decimal(value: str, hemisphere: str) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        degrees = float(value)
    except ValueError:
        return None

    deg = int(degrees // 100)
    minutes = degrees - (deg * 100)
    decimal = deg + (minutes / 60.0)
    if hemisphere in {"S", "W"}:
        decimal *= -1.0
    return decimal


class NMEADecoder:
    def __init__(self):
        self.status = GPSStatus()
        self._fix_sources: Dict[str, bool] = {"gga": False, "rmc": False, "gsa": False}

    def _update_fix_status(self, source: str, fix_present: bool) -> None:
        self._fix_sources[source] = fix_present
        self.status.has_fix = any(self._fix_sources.values())

    def _record_constellation(
        self,
        talker: str,
        sat_count: int = 0,
        fix_mode: Optional[str] = None,
        in_view: Optional[int] = None,
    ) -> None:
        self.status.constellations.add(talker)
        self.status.constellation_stats.setdefault(talker, {"satellites": 0, "fix_mode": "", "in_view": 0})
        if sat_count:
            self.status.constellation_stats[talker]["satellites"] = sat_count
        if fix_mode:
            self.status.constellation_stats[talker]["fix_mode"] = fix_mode
        if in_view is not None:
            # Multi-GNSS receivers often report GSV in separate per-signal
            # groups (e.g. L1 vs L5 for GPS), each under the same talker but
            # with its own "satellites in view" total. Taking the max instead
            # of overwriting keeps the count stable instead of flickering
            # between each signal group's (smaller) subset count.
            current = self.status.constellation_stats[talker]["in_view"]
            self.status.constellation_stats[talker]["in_view"] = max(current, in_view)
        self._recalculate_totals()

    def _recalculate_totals(self) -> None:
        # "GN" is the combined multi-GNSS solution reported directly by GGA.
        # Once real per-system breakdowns exist (from GSA/GSV), the true
        # totals are the sum of each constellation rather than a max() over
        # mismatched per-sentence readings, so the top-line counts always
        # agree with the breakdown shown underneath. Before any breakdown is
        # available, fall back to the combined GGA figures.
        real_stats = {
            name: stats
            for name, stats in self.status.constellation_stats.items()
            if name != "GN"
        }
        if real_stats:
            self.status.satellites = sum(stats.get("satellites", 0) for stats in real_stats.values())
            self.status.satellites_in_view = sum(stats.get("in_view", 0) for stats in real_stats.values())
        else:
            gn_stats = self.status.constellation_stats.get("GN", {})
            self.status.satellites = gn_stats.get("satellites", 0)
            self.status.satellites_in_view = gn_stats.get("in_view", 0)

    @staticmethod
    def _safe_int(value):
        if value in (None, ""):
            return 0
        try:
            return int(value)
        except ValueError:
            return 0

    @staticmethod
    def _checksum_ok(sentence: str) -> bool:
        sentence = sentence.strip()
        if not sentence or not sentence.startswith("$"):
            return False
        star = sentence.rfind("*")
        if star <= 0 or star == len(sentence) - 1:
            return False
        body = sentence[1:star]
        expected = sentence[star + 1 :].strip().upper()
        if len(expected) != 2:
            return False
        checksum = 0
        for ch in body:
            checksum ^= ord(ch)
        return format(checksum, "02X") == expected

    def _prune_stale_satellites(self) -> None:
        now = time.monotonic()
        for talker_key in list(self.status.visible_satellites):
            sat_list = self.status.visible_satellites[talker_key]
            fresh = [
                sat
                for sat in sat_list
                if now - sat.get("last_seen", now) <= SATELLITE_TIMEOUT_SECONDS
            ]
            if fresh:
                self.status.visible_satellites[talker_key] = fresh
            else:
                del self.status.visible_satellites[talker_key]

    @staticmethod
    def _talker_and_type(sentence: str):
        if not sentence.startswith("$"):
            return None, None
        body = sentence[1:]
        if "," not in body:
            return None, None
        prefix = body.split(",", 1)[0]
        if len(prefix) < 5:
            return None, None
        return prefix[:2], prefix[2:]

    def update(self, sentence: str) -> Optional[GPSStatus]:
        sentence = sentence.strip()
        if not sentence:
            return None
        if not self._checksum_ok(sentence):
            return None

        talker, msg_type = self._talker_and_type(sentence)
        if talker is None or msg_type is None:
            return None

        self._prune_stale_satellites()

        fields = sentence.split(",")
        if fields and "*" in fields[-1]:
            fields[-1] = fields[-1].split("*", 1)[0]

        if msg_type == "GGA":
            if len(fields) < 15:
                return self.status
            time_utc = fields[1]
            latitude = _dms_to_decimal(fields[2], fields[3]) if len(fields) > 3 else None
            longitude = _dms_to_decimal(fields[4], fields[5]) if len(fields) > 5 else None
            fix_quality = self._safe_int(fields[6])
            satellites = self._safe_int(fields[7])
            hdop = _to_float(fields[8]) if len(fields) > 8 and fields[8] not in (None, "") else None
            altitude = _to_float(fields[9]) if len(fields) > 9 and fields[9] not in (None, "") else None
            geoidal_separation = _to_float(fields[11]) if len(fields) > 11 and fields[11] not in (None, "") else None

            self._record_constellation(talker, satellites)
            self.status.time_utc = self._format_utc(time_utc)
            self.status.latitude = latitude
            self.status.longitude = longitude
            self.status.fix_quality = fix_quality
            self._update_fix_status("gga", fix_quality > 0)
            self.status.altitude = altitude
            self.status.geoidal_separation = geoidal_separation
            self.status.hdop = hdop
            return self.status

        if msg_type == "RMC":
            if len(fields) < 12:
                return self.status
            time_utc = fields[1]
            date_utc = fields[9] if len(fields) > 9 else None
            rmc_status = fields[2]
            latitude = _dms_to_decimal(fields[3], fields[4]) if len(fields) > 4 else None
            longitude = _dms_to_decimal(fields[5], fields[6]) if len(fields) > 6 else None
            speed = _to_float(fields[7]) if len(fields) > 7 else None
            course = _to_float(fields[8]) if len(fields) > 8 else None

            self._record_constellation(talker)
            self.status.time_utc = self._format_utc(time_utc)
            self.status.date_utc = self._format_date(date_utc)
            self.status.latitude = latitude
            self.status.longitude = longitude
            self._update_fix_status("rmc", rmc_status == "A")
            self.status.speed_knots = speed
            self.status.course_deg = course
            return self.status

        if msg_type == "GSA":
            if len(fields) < 18:
                return self.status
            fix_type = self._safe_int(fields[2])
            satellites = 0
            for value in fields[3:15]:
                if value and value != "":
                    satellites += 1

            # Prefer the NMEA 4.11 System ID (field 18) over the talker so that
            # multiple $GNGSA sentences (one per constellation) are attributed
            # to their real satellite system instead of colliding on "GN".
            system_id = fields[18] if len(fields) > 18 else None
            constellation = SYSTEM_ID_TO_CONSTELLATION.get(system_id, talker)

            self._record_constellation(constellation, satellites, fix_mode=str(fix_type))
            self.status.fix_type = fix_type
            self._update_fix_status("gsa", fix_type >= 2)
            self.status.pdop = _to_float(fields[15]) if len(fields) > 15 else None
            self.status.hdop = _to_float(fields[16]) if len(fields) > 16 else None
            self.status.vdop = _to_float(fields[17]) if len(fields) > 17 else None
            return self.status

        if msg_type == "GSV":
            if len(fields) < 8:
                return self.status
            talker_key = talker
            sats_in_view = self._safe_int(fields[3])
            self._record_constellation(talker_key, in_view=sats_in_view)
            sat_list = self.status.visible_satellites.setdefault(talker_key, [])

            for idx in range(4):
                offset = 4 + idx * 4
                if offset + 3 >= len(fields):
                    break
                prn = fields[offset]
                elev = fields[offset + 1]
                az = fields[offset + 2]
                snr = fields[offset + 3]
                prn_value = _to_int(prn)
                if not prn_value:
                    continue

                satellite_entry = {
                    "prn": prn_value,
                    "elevation": _to_int(elev),
                    "azimuth": _to_int(az),
                    "snr": _to_int(snr),
                    "last_seen": time.monotonic(),
                }
                for index, existing in enumerate(sat_list):
                    if existing.get("prn") == satellite_entry["prn"]:
                        sat_list[index] = satellite_entry
                        break
                else:
                    sat_list.append(satellite_entry)
            return self.status

        return self.status

    @staticmethod
    def _format_utc(value: str) -> Optional[str]:
        if not value or len(value) < 6:
            return None
        try:
            hh = int(value[0:2])
            mm = int(value[2:4])
            ss = int(value[4:6])
            return f"{hh:02d}:{mm:02d}:{ss:02d}"
        except ValueError:
            return None

    @staticmethod
    def _format_date(value: str) -> Optional[str]:
        if not value or len(value) < 6:
            return None
        try:
            dd = int(value[0:2])
            mm = int(value[2:4])
            yy = int(value[4:6])
            # NMEA dates carry a 2-digit year only. GPS didn't exist before 1980,
            # so treat 80-99 as 1900s and 00-79 as 2000s (standard century pivot).
            century = 1900 if yy >= 80 else 2000
            return f"{dd:02d}/{mm:02d}/{century + yy}"
        except ValueError:
            return None


def clear_screen() -> None:
    # ANSI clear + cursor-home avoids spawning a shell on every refresh.
    print("\033[2J\033[H", end="")


def print_gps_summary(status: GPSStatus) -> None:
    clear_screen()
    print(status.render_dashboard())
    print()


def monitor_uart(uart, poll_interval: float = 1.0) -> None:
    decoder = NMEADecoder()
    buffer = ""
    while True:
        raw = uart.read_uart_bytes(128, poll_interval)
        if not raw:
            continue
        buffer += raw.decode("utf-8", errors="ignore")
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            sentence = line.strip()
            if sentence.startswith("$"):
                status = decoder.update(sentence)
                if status is not None:
                    print_gps_summary(status)
        time.sleep(0.02)
