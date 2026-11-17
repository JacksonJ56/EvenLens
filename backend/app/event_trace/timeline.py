import re
import unicodedata
from calendar import month_name, month_abbr
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from .schemas import EventProposal, Evidence, TimelineEvent, TimePrecision


def evidence_text(value: str) -> str:
    return " ".join(value.split())


def validated_time(value: str | None, precision: TimePrecision) -> tuple[str | None, TimePrecision, str | None]:
    if value is None or precision == "unknown":
        return None, "unknown", None
    try:
        if precision == "datetime" and re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})?", value
        ):
            moment = datetime.fromisoformat(value)
            if moment.tzinfo:
                normalized = moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                return normalized, precision, None
            return moment.date().isoformat(), "date", "时区未知，仅保留日期"
        formats = {"date": r"[0-9]{4}-[0-9]{2}-[0-9]{2}", "month": r"[0-9]{4}-[0-9]{2}", "year": r"[0-9]{4}"}
        if precision in formats and re.fullmatch(formats[precision], value):
            suffix = {"date": "", "month": "-01", "year": "-01-01"}[precision]
            date.fromisoformat(value + suffix)
            return value, precision, None
    except (ValueError, OverflowError):
        pass
    return None, "unknown", "时间格式或日期无法确认"


def time_bounds(event: TimelineEvent) -> tuple[datetime, datetime] | None:
    value = event.occurred_at
    if value is None:
        return None
    if event.time_precision == "datetime":
        point = datetime.fromisoformat(value)
        return point, point
    suffix = {"date": "", "month": "-01", "year": "-01-01"}[event.time_precision]
    start = datetime.fromisoformat(value + suffix).replace(tzinfo=timezone.utc)
    if event.time_precision == "date":
        if start.date() == date.max:
            return start, datetime.max.replace(tzinfo=timezone.utc)
        end = start + timedelta(days=1)
    elif start.year == 9999 and (event.time_precision == "year" or start.month == 12):
        return start, datetime.max.replace(tzinfo=timezone.utc)
    elif event.time_precision == "year" or start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end - timedelta(microseconds=1)


def title_key(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).casefold()
    return "".join(char for char in normalized if char.isalnum()) or normalized


def mentions_date(text: str, day: str) -> bool:
    parsed = date.fromisoformat(day)
    year, month, number = parsed.year, parsed.month, parsed.day
    formats = [
        day, f"{year}/{month}/{number}", f"{year}/{month:02}/{number:02}",
        f"{month:02}-{number:02}", f"{month}月 {number}日", f"{month} 月 {number} 日",
        f"{month}月{number}日",
    ]
    for label in (month_name[month], month_abbr[month]):
        formats.extend([f"{label} {number}", f"{number} {label}"])
    return any(value.casefold() in text.casefold() for value in formats)


def validate_timeline(
    proposals: list[EventProposal], texts: dict[str, dict[str, str]],
    publication_dates: dict[str, str] | None = None,
) -> tuple[list[TimelineEvent], bool, bool]:
    valid: dict[tuple[str, str | None, str], TimelineEvent] = {}
    dropped = False
    for proposal in proposals:
        evidence = []
        for quote in proposal.evidence:
            snippet = evidence_text(quote.excerpt)
            text = texts.get(quote.source_id, {}).get(quote.kind, "")
            offset = text.find(snippet) if len(snippet) >= 8 else -1
            if offset < 0:
                dropped = True
                continue
            hit = Evidence(source_id=quote.source_id, kind=quote.kind, excerpt=text[offset:offset + len(snippet)], offset=offset)
            if hit not in evidence:
                evidence.append(hit)
        if not evidence:
            continue

        occurred_at, precision, note = validated_time(proposal.occurred_at, proposal.time_precision)
        if publication_dates and occurred_at and precision in {"date", "datetime"}:
            day = occurred_at[:10]
            same_as_publication = any(publication_dates.get(hit.source_id, "")[:10] == day for hit in evidence)
            if same_as_publication and not any(mentions_date(hit.excerpt, day) for hit in evidence):
                occurred_at, precision, note = None, "unknown", "日期与来源发布日期相同，但引文未明确事件发生日"
        uncertainty = "；".join(filter(None, [proposal.uncertainty, note])) or None
        key = (title_key(proposal.title), occurred_at, precision)
        if existing := valid.get(key):
            existing.evidence.extend(hit for hit in evidence if hit not in existing.evidence)
            existing.source_ids = list(dict.fromkeys(hit.source_id for hit in existing.evidence))
            if uncertainty and uncertainty != existing.uncertainty:
                existing.uncertainty = "；".join(filter(None, [existing.uncertainty, uncertainty]))
        else:
            valid[key] = TimelineEvent(
                id=f"event_{len(valid) + 1:03}", title=proposal.title, description=proposal.description,
                occurred_at=occurred_at, time_precision=precision, evidence=evidence,
                source_ids=list(dict.fromkeys(hit.source_id for hit in evidence)), uncertainty=uncertainty,
            )

    families = defaultdict(list)
    for (key, _, _), event in valid.items():
        if bounds := time_bounds(event):
            families[key].append((event, bounds))
    conflict = False
    for group in families.values():
        for event, (start, end) in group:
            if any(end < other_start or start > other_end for _, (other_start, other_end) in group):
                conflict = True
                event.uncertainty = "；".join(filter(None, [event.uncertainty, "来源对事件时间的说法冲突"]))
    return list(valid.values()), dropped, conflict


def chronological_key(event: TimelineEvent) -> tuple[bool, datetime]:
    bounds = time_bounds(event)
    return bounds is None, bounds[0] if bounds else datetime.max.replace(tzinfo=timezone.utc)
