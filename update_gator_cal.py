import datetime
import os
import re
import subprocess
from bs4 import BeautifulSoup

URL = (
    "https://www.navymwr.org/programs/motion-pictures/theaters"
    "?id=f05ab221-ed69-41e0-89d7-abf5e0032e38"
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
OUTPUT_FILENAME = "gator_theater.ics"

DATE_PATTERN = re.compile(
    r"(?:(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*[-,–—]\s*)?"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{1,2})(?:\s*,\s*(\d{4}))?",
    re.IGNORECASE,
)
TIME_PATTERN = re.compile(r"\b(\d{1,2}:\d{2})\s*([APap][Mm])\b")
RUNTIME_PATTERN = re.compile(r"(\d+)\s*min", re.IGNORECASE)


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def escape_ical(text: str) -> str:
    return (
        text.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")
    )


def fetch_html_with_curl(url: str, timeout_sec: int = 25) -> str:
    cmd = [
        "curl",
        "-sS",
        "-L",
        "--max-time",
        str(timeout_sec),
        "--retry",
        "3",
        "--retry-delay",
        "2",
        "--retry-all-errors",
        "-A",
        USER_AGENT,
        "-H",
        "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "-H",
        "Accept-Language: en-US,en;q=0.9",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout


def parse_date_from_text(text: str, default_year: int):
    match = DATE_PATTERN.search(text)
    if not match:
        return None
    _, month_str, day_str, year_str = match.groups()
    year = int(year_str) if year_str else default_year
    try:
        return datetime.datetime.strptime(
            f"{month_str.capitalize()} {int(day_str)} {year}", "%B %d %Y"
        ).date()
    except ValueError:
        return None


def extract_movie_title(movie_cell) -> str:
    link = movie_cell.find("a")
    if link:
        title = clean_text(link.get_text(" ", strip=True))
        if title:
            return title

    raw = clean_text(movie_cell.get_text(" ", strip=True))
    raw = re.split(r"\s+(?:When\s+|Rated\s+(?:G|PG-13|PG|R|NC-17)\b)", raw)[0]
    return clean_text(raw)


def parse_runtime_minutes(runtime_cell, default_mins: int = 150) -> int:
    if not runtime_cell:
        return default_mins
    match = RUNTIME_PATTERN.search(clean_text(runtime_cell.get_text(" ", strip=True)))
    if match:
        return int(match.group(1))
    return default_mins


def existing_ics_has_events(path: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return "BEGIN:VEVENT" in f.read()
    except OSError:
        return False


def main():
    print("Fetching schedule from Navy MWR via curl...")
    try:
        html = fetch_html_with_curl(URL)
    except Exception as e:
        print(f"Error downloading page via curl: {e}")
        raise SystemExit(1)

    if "/apology_objects/" in html or "Internal Server Error" in html:
        print("Received MWR error/apology page; preserving existing calendar.")
        raise SystemExit(1)

    print(f"Fetched {len(html)} characters.")
    soup = BeautifulSoup(html, "html.parser")
    events = []
    current_date = None
    default_year = datetime.datetime.now().year

    for tr in soup.find_all("tr"):
        if tr.find("th", colspan=True):
            header_text = clean_text(tr.get_text(" ", strip=True))
            found_date = parse_date_from_text(header_text, default_year)
            if found_date:
                current_date = found_date
            continue

        if tr.find("th"):
            continue

        tds = tr.find_all("td")
        if not current_date or len(tds) < 2:
            continue

        time_text = clean_text(tds[0].get_text(" ", strip=True))
        time_match = TIME_PATTERN.search(time_text)
        if not time_match:
            continue

        time_norm = f"{time_match.group(1)} {time_match.group(2).upper()}"
        try:
            time_obj = datetime.datetime.strptime(time_norm, "%I:%M %p").time()
        except ValueError:
            continue

        title = extract_movie_title(tds[1])
        if not title:
            continue

        rating_img = tds[2].find("img") if len(tds) >= 3 else None
        rating = (
            clean_text(rating_img.get("alt", "")).upper()
            if rating_img and rating_img.get("alt")
            else ""
        )
        summary = f"{title} ({rating})" if rating else title

        runtime_mins = parse_runtime_minutes(
            tds[3] if len(tds) >= 4 else None, default_mins=150
        )
        start_dt = datetime.datetime.combine(current_date, time_obj)
        end_dt = start_dt + datetime.timedelta(minutes=runtime_mins)

        events.append({
            "summary": summary,
            "start": start_dt.strftime("%Y%m%dT%H%M%S"),
            "end": end_dt.strftime("%Y%m%dT%H%M%S"),
            "uid": f"gator-{start_dt.strftime('%Y%m%d%H%M')}-{len(events)+1}@carlconti",
        })

    if not events and existing_ics_has_events(OUTPUT_FILENAME):
        print(
            f"0 events parsed, but '{OUTPUT_FILENAME}' already has events. Keeping existing file."
        )
        raise SystemExit(1)

    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Gator Scraper Pass//20260809T110006//EN",
        "X-WR-CALNAME:Gator Theater Movie Schedule",
        "X-WR-TIMEZONE:America/New_York",
        "X-PUBLISHED-TTL:PT4H",
        "REFRESH-INTERVAL;VALUE=DURATION:PT4H",
    ]

    for ev in events:
        ics_lines.extend([
            "BEGIN:VEVENT",
            f"SUMMARY:{escape_ical(ev['summary'])}",
            f"DTSTART;TZID=America/New_York:{ev['start']}",
            f"DTEND;TZID=America/New_York:{ev['end']}",
            f"DTSTAMP:{now_utc}",
            f"UID:{ev['uid']}",
            "LOCATION:Gator Theater\\, JEBLC\\, Virginia Beach\\, VA",
            "END:VEVENT",
        ])

    ics_lines.append("END:VCALENDAR")

    with open(
        OUTPUT_FILENAME, "w", encoding="utf-8", newline="\r\n"
    ) as f:
        f.write("\n".join(ics_lines))

    print(
        f"Success! Updated calendar file saved as '{OUTPUT_FILENAME}' with {len(events)} events."
    )


if __name__ == "__main__":
    main()
