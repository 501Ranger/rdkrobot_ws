import re
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


RECORD_KEYWORDS = (
    '记录当前位置为', '记录当前位置成', '记录当前位置作',
    '把当前位置记作', '把当前位置记为',
    '把当前位置设置成为', '把当前位置设置为', '把当前位置设置成',
    '设置当前位置成为', '设置当前位置为', '设置当前位置成',
    '当前位置设置成为', '当前位置设置为', '当前位置设置成',
    '把这里设置成为', '把这里设置为', '把这里设置成',
    '这里设置成为', '这里设置为', '这里设置成',
)
RECORD_PLACE_PATTERNS = (
    re.compile(r'(?:请|帮我)?(?:把)?(?:当前位置|这里|这儿|这个地方|这地方|此处)(?:设置成为|设置为|设置成|设定为|设定成|设为|设成|命名为|命名成|取名为|叫做|叫|记作|记为|标记为|标记成|保存为|保存成|记录为|记录成)(?P<place>[^，。！？,.!?\s]{1,20})'),
    re.compile(r'(?:请|帮我)?(?:保存|记录|标记)(?:当前位置|这里|这儿|这个地方|这地方|此处)(?:为|成|成为|作)(?P<place>[^，。！？,.!?\s]{1,20})'),
    re.compile(r'(?:以后)?(?:这里|这儿|这个地方|这地方|此处)(?:就)?(?:叫做|叫|命名为|命名成)(?P<place>[^，。！？,.!?\s]{1,20})'),
    re.compile(r'以后(?:这里|这儿|这个地方|这地方|此处)(?:就)?是(?P<place>[^，。！？,.!?\s]{1,20})'),
)

STOP_KEYWORDS = ('停止', '停下', '别动', '不要动', '急停', '刹车', '暂停')
PATROL_KEYWORDS = ('巡查', '巡视', '巡逻', '检查一圈', '看一圈')
STATUS_KEYWORDS = ('状态', '在哪里', '在哪', '电量', '位置')
GO_VERBS = ('去', '到', '前往', '移动', '过去', '看看', '检查')
HOME_KEYWORDS = ('回家', '回起点', '回原点', '回充电桩', '返回起点')
LOOK_AT_SOUND_KEYWORDS = ('看向声音方向', '看向声音', '转到声源', '转弯声源', '看向声源', '转到声音', '看声音')
SOUND_LOCALIZATION_KEYWORDS = ('开启声源定位', '声源定位', '打开声源定位', '开启声音定位', '声音定位')
COME_HERE_KEYWORDS = ('过来', '来我这', '到我这', '到我这边', '来我这边', '靠近我')


def parse_intent(
    text: str,
    place_aliases: Optional[Dict[str, str]] = None,
) -> Intent:
    cleaned = _normalize(text)
    aliases = place_aliases or DEFAULT_PLACE_ALIASES

    if not cleaned:
        return Intent(name='empty', raw_text=text, confidence=0.0)

    if _contains_any(cleaned, COME_HERE_KEYWORDS):
        return Intent(name='come_here', raw_text=text)

    place_name = _match_record_place(cleaned)
    if place_name:
        return Intent(name='record_place', raw_text=text, place=place_name)

    if _contains_any(cleaned, LOOK_AT_SOUND_KEYWORDS):
        return Intent(name='look_at_sound', raw_text=text)

    if _contains_any(cleaned, SOUND_LOCALIZATION_KEYWORDS):
        return Intent(name='sound_localization', raw_text=text)

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



def _match_record_place(text: str) -> Optional[str]:
    for kw in RECORD_KEYWORDS:
        if kw in text:
            parts = text.split(kw, 1)
            if len(parts) > 1:
                place_name = _clean_place_name(parts[1])
                if place_name:
                    return place_name

    for pattern in RECORD_PLACE_PATTERNS:
        match = pattern.search(text)
        if match:
            place_name = _clean_place_name(match.group('place'))
            if place_name:
                return place_name

    return None


def _clean_place_name(place_name: str) -> str:
    place_name = place_name.strip(' ，。！？,.!?')
    while place_name and place_name[-1] in '吧呀啊呢啦了哦':
        place_name = place_name[:-1]
    return place_name.strip()


def _normalize(text: str) -> str:
    return ''.join(text.strip().split()).lower()


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _match_place(text: str, place_aliases: Dict[str, str]) -> Optional[str]:
    for alias, place_id in place_aliases.items():
        if alias in text:
            return place_id
    return None
