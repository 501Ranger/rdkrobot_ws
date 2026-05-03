from dataclasses import dataclass
from typing import Dict, Iterable, Optional


@dataclass(frozen=True)
class Intent:
    name: str
    raw_text: str
    place: Optional[str] = None
    confidence: float = 1.0


DEFAULT_PLACE_ALIASES: Dict[str, str] = {
    '客厅': 'living_room',
    '大厅': 'living_room',
    '卧室': 'bedroom',
    '房间': 'bedroom',
    '门口': 'door',
    '大门': 'door',
    '玄关': 'door',
    '起点': 'home',
    '原点': 'home',
    '家': 'home',
    '充电桩': 'home',
}


STOP_KEYWORDS = ('停止', '停下', '别动', '不要动', '急停', '刹车', '暂停')
PATROL_KEYWORDS = ('巡查', '巡视', '巡逻', '检查一圈', '看一圈')
STATUS_KEYWORDS = ('状态', '在哪里', '在哪', '电量', '位置')
GO_VERBS = ('去', '到', '前往', '移动', '过去', '看看', '检查')
HOME_KEYWORDS = ('回家', '回起点', '回原点', '回充电桩', '返回起点')


def parse_intent(
    text: str,
    place_aliases: Optional[Dict[str, str]] = None,
) -> Intent:
    cleaned = _normalize(text)
    aliases = place_aliases or DEFAULT_PLACE_ALIASES

    if not cleaned:
        return Intent(name='empty', raw_text=text, confidence=0.0)

    if _contains_any(cleaned, STOP_KEYWORDS):
        return Intent(name='stop', raw_text=text)

    if _contains_any(cleaned, PATROL_KEYWORDS):
        return Intent(name='start_patrol', raw_text=text)

    if _contains_any(cleaned, HOME_KEYWORDS):
        return Intent(name='go_to', raw_text=text, place='home')

    if _contains_any(cleaned, STATUS_KEYWORDS):
        return Intent(name='status', raw_text=text)

    place = _match_place(cleaned, aliases)
    if place and _contains_any(cleaned, GO_VERBS):
        return Intent(name='go_to', raw_text=text, place=place)

    return Intent(name='chat', raw_text=text, confidence=0.4)


def _normalize(text: str) -> str:
    return ''.join(text.strip().split()).lower()


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _match_place(text: str, place_aliases: Dict[str, str]) -> Optional[str]:
    for alias, place_id in place_aliases.items():
        if alias in text:
            return place_id
    return None
