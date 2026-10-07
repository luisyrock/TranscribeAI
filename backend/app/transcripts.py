import html
import re
from dataclasses import dataclass


@dataclass
class Cue:
    index: int
    start: float
    end: float
    speaker: str | None
    text: str
    source_id: str | None = None


@dataclass
class Chunk:
    cue_start: int
    cue_end: int
    start: float
    end: float
    text: str


def timestamp(value: str) -> float:
    if not re.fullmatch(r"(?:\d{2,}:)?\d{2}:\d{2}\.\d{3}", value):
        raise ValueError("Marca de tiempo VTT inválida.")
    parts = value.split(":")
    seconds = float(parts[-1])
    minutes = int(parts[-2])
    if seconds >= 60 or minutes >= 60:
        raise ValueError("Marca de tiempo VTT fuera de rango.")
    return seconds + minutes * 60 + (int(parts[0]) * 3600 if len(parts) == 3 else 0)


def clock(value: float) -> str:
    total = int(value)
    return f"{total // 3600:02}:{total // 60 % 60:02}:{total % 60:02}" if total >= 3600 else f"{total // 60:02}:{total % 60:02}"


def parse_vtt(data: bytes) -> list[Cue]:
    try:
        text = data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError as exc:
        raise ValueError("El VTT debe estar codificado en UTF-8.") from exc
    if not re.match(r"^WEBVTT(?:[ \t].*)?(?:\n|$)", text):
        raise ValueError("El archivo no tiene una cabecera WEBVTT válida.")
    cues = []
    for block in re.split(r"\n[ \t]*\n", text):
        lines = block.strip().splitlines()
        if not lines or re.match(r'^NOTE(?:[ \t]|$)', lines[0]) or lines[0] in ('STYLE', 'REGION') or re.match(r'^WEBVTT(?:[ \t]|$)', lines[0]):
            continue
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None or timing_index > 1:
            raise ValueError("Se encontró un bloque VTT sin tiempos válidos.")
        match = re.match(r"^\s*(\S+)\s+-->\s+(\S+)(?:\s+.*)?$", lines[timing_index])
        if not match:
            raise ValueError("Tiempos VTT inválidos.")
        start, end = timestamp(match[1]), timestamp(match[2])
        if end <= start:
            raise ValueError("El final de una intervención debe ser posterior al inicio.")
        payload = " ".join(lines[timing_index + 1:])
        voices = re.findall(r"<v(?:\.[^ >]+)*\s+([^>]+)>", payload)
        names = list(dict.fromkeys(html.unescape(v).strip() for v in voices))
        speaker = ' / '.join(names) if names else None
        if len(voices) > 1:
            payload = re.sub(r"<v(?:\.[^ >]+)*\s+([^>]+)>", lambda m:' ' + html.unescape(m[1]).strip() + ': ', payload)
        clean = " ".join(html.unescape(re.sub(r"<[^>]*>", "", payload)).split())
        if clean:
            cues.append(Cue(len(cues), start, end, speaker, clean, lines[0] if timing_index else None))
    if not cues:
        raise ValueError("El archivo no contiene intervenciones con texto.")
    return cues


def chunk_cues(cues: list[Cue], target: int = 1800) -> list[Chunk]:
    result, group, size = [], [], 0
    def render(items):
        return "\n".join(f"[{clock(c.start)}] {c.speaker or 'Sin hablante'}: {c.text}" for c in items)
    for cue in cues:
        if group and size + len(cue.text) > target:
            result.append(Chunk(group[0].index, group[-1].index, group[0].start, group[-1].end, render(group)))
            group = [group[-1]] if len(group) > 1 else []
            size = sum(len(c.text) for c in group)
        group.append(cue)
        size += len(cue.text)
    if group:
        result.append(Chunk(group[0].index, group[-1].index, group[0].start, group[-1].end, render(group)))
    return result
