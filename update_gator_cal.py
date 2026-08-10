import re
import datetime
import requests
from bs4 import BeautifulSoup

# Setup target URL and custom headers
URL = "https://www.navymwrmidlant.com/programs/704df338-a0bc-4c33-94f3-9a75abd01d1a"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def escape_ical(text):
    """Escapes commas and semicolons per RFC 5545 specifications."""
    return text.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")

def main():
    print("Fetching schedule from MWR Mid-Atlantic...")
    try:
        response = requests.get(URL, headers=HEADERS, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Error downloading page: {e}")
        return

    soup = BeautifulSoup(response.text, "html.parser")
    events = []

    # Parse schedule components
    current_date = None
    for element in soup.find_all(["h3", "h4", "div", "table"]):
        text = element.get_text(strip=True)

        # Parse date headings (e.g. "Saturday - August 15, 2026")
        date_match = re.search(
            r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*[-,\s]\s*([A-Za-z]+)\s+(\d{1,2})(?:\s*,\s*(\d{4}))?",
            text,
        )
        if date_match:
            _, month_str, day_str, year_str = date_match.groups()
            year = int(year_str) if year_str else datetime.datetime.now().year
            try:
                current_date = datetime.datetime.strptime(
                    f"{month_str} {day_str} {year}", "%B %d %Y"
                ).date()
            except ValueError:
                continue

        # Extract showtimes from table rows
        if current_date and element.name == "table":
            for row in element.find_all("tr"):
                cols = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cols) >= 2 and ("PM" in cols[0] or "AM" in cols[0]):
                    time_str = cols[0]
                    title = cols[1]

                    # Parse start time
                    try:
                        time_obj = datetime.datetime.strptime(time_str, "%I:%M %p").time()
                        start_dt = datetime.datetime.combine(current_date, time_obj)
                    except ValueError:
                        continue

                    # Extract runtime or set standard default (150 mins)
                    runtime_mins = 150
                    for col in cols:
                        rt_match = re.search(r"(\d+)\s*min", col)
                        if rt_match:
                            runtime_mins = int(rt_match.group(1))
                            break

                    end_dt = start_dt + datetime.timedelta(minutes=runtime_mins)
                    events.append({
                        "title": title,
                        "start": start_dt.strftime("%Y%m%dT%H%M%S"),
                        "end": end_dt.strftime("%Y%m%dT%H%M%S"),
                        "uid": f"gator-{start_dt.strftime('%Y%m%d%H%M')}-{len(events)+1}@carlconti"
                    })

    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # Build RFC 5545 compliant iCalendar payload with iOS refresh metadata
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
            f"SUMMARY:{escape_ical(ev['title'])}",
            f"DTSTART;TZID=America/New_York:{ev['start']}",
            f"DTEND;TZID=America/New_York:{ev['end']}",
            f"DTSTAMP:{now_utc}",
            f"UID:{ev['uid']}",
            "LOCATION:Gator Theater\\, JEBLC\\, Virginia Beach\\, VA",
            "END:VEVENT"
        ])

    ics_lines.append("END:VCALENDAR")

    # Save output file
    output_filename = "gator_theater.ics"
    with open(output_filename, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(ics_lines))

    print(f"Success! Updated calendar file saved as '{output_filename}' with {len(events)} events.")

if __name__ == "__main__":
    main()
