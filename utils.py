"""ETK 精简版 utils（只保留翻译所需）"""
import logging
import re
import unicodedata
from typing import Optional, List, Dict, Any

# 兼容原版自定义 TRACE 日志级别
if not hasattr(logging, "TRACE"):
    logging.addLevelName(5, "TRACE")
    setattr(logging, "TRACE", 5)
    def _trace(self, msg, *args, **kwargs):
        if self.isEnabledFor(5):
            self._log(5, msg, args, **kwargs)
    logging.Logger.trace = _trace

def contains_chinese(text: Optional[str]) -> bool:
    """检查字符串是否包含中文字符。"""
    if not text:
        return False
    for char in text:
        if '\u4e00' <= char <= '\u9fff' or \
           '\u3400' <= char <= '\u4dbf' or \
           '\uf900' <= char <= '\ufaff':
            return True
    return False

_CHARACTER_ROLE_DISPLAY_PREFIX_RE = re.compile(r'^(?:(?:饰|配)[\s\u3000]+)+')



def clean_character_name_static(character_name: Optional[str]) -> str:
    """
    统一格式化角色名：
    - 去除括号内容、前后缀如“饰、配、配音、as”
    - 中外对照时仅保留中文部分
    - 如果仅为“饰 Kevin”这种格式，清理前缀后保留英文，待后续翻译
    """
    if not character_name:
        return ""

    name = str(character_name).strip()

    # 移除括号和中括号的内容
    name = re.sub(r'\(.*?\)|\[.*?\]|（.*?）|【.*?】', '', name).strip()

    # 移除 as 前缀（如 "as Kevin"）
    name = re.sub(r'^(as\s+)', '', name, flags=re.IGNORECASE).strip()

    # 清理前缀中的“饰演/饰/配音/配”（不加判断，直接清理）
    prefix_pattern = r'^((?:饰演|饰|扮演|扮|配音|配|as\b)\s*)+'
    name = re.sub(prefix_pattern, '', name, flags=re.IGNORECASE).strip()

    # 清理后缀中的“饰演/饰/配音/配”
    suffix_pattern = r'(\s*(?:饰演|饰|配音|配))+$'
    name = re.sub(suffix_pattern, '', name).strip()

    # 处理中外对照：“中文+英文” 或 “英文+中文” 形式，只保留中文部分
    if re.search(r'[\u4e00-\u9fa5]', name) and re.search(r'[a-zA-Z]', name):
        # 1. 优先尝试按常见分隔符 (/, |) 拆分 (例如 "ShenWang/王忱")
        if '/' in name or '|' in name:
            parts = re.split(r'[/|]', name)
            for part in parts:
                # 找到包含中文的那一部分
                if re.search(r'[\u4e00-\u9fa5]', part):
                    # 提取出中文部分后，剔除可能残留的英文字母，并清理首尾空格
                    return re.sub(r'[a-zA-Z]', '', part).strip()
        
        # 2. 如果没有明显分隔符 (例如 "ShenWang王忱" 或 "王忱 ShenWang")
        # 直接暴力剔除所有英文字母，并压缩多余的空格
        clean_name = re.sub(r'[a-zA-Z]', '', name)
        return re.sub(r'\s+', ' ', clean_name).strip()

    # 如果只有外文，或清理后是英文，保留原值，等待后续翻译流程
    return name.strip()


def normalize_name_for_matching(name: Optional[str]) -> str:
    """
    将名字极度标准化，用于模糊比较。
    转小写、移除所有非字母数字字符、处理 Unicode 兼容性。
    例如 "Chloë Grace Moretz" -> "chloegracemoretz"
    """
    if not name:
        return ""
    # NFKD 分解可以将 'ë' 分解为 'e' 和 '̈'
    nfkd_form = unicodedata.normalize('NFKD', str(name))
    # 只保留基本字符，去除重音等组合标记
    ascii_name = u"".join([c for c in nfkd_form if not unicodedata.combining(c)])
    # 转小写并只保留字母和数字
    return ''.join(filter(str.isalnum, ascii_name.lower()))

# 类型映射
GENRE_TRANSLATION_PATCH = {
    "Sci-Fi & Fantasy": "科幻奇幻",
    "War & Politics": "战争政治",
    # 以后如果发现其他未翻译的，也可以加在这里
}

# --- ★★★ 统一分级映射功能 (V2 - 健壮版) ★★★ ---
# 1. 统一的分级选项 (前端下拉框用)
UNIFIED_RATING_CATEGORIES = [
    '全年龄', '家长辅导', '青少年', '限制级', '18禁', '成人', '未知'
]

# 2. 默认优先级策略 (如果数据库没配置，就用这个)
# ORIGIN 代表原产国，如果原产国没数据，按顺序找后面的
DEFAULT_RATING_PRIORITY = ["ORIGIN", "US", "HK", "TW", "JP", "KR", "GB", "ES", "DE"]

# 3. 默认分级映射表 (如果数据库没配置，就用这个)
# 格式: { 国家代码: [ { code: 原分级, label: 映射中文 }, ... ] }
DEFAULT_RATING_MAPPING = {
    "US": [
        {"code": "G", "label": "全年龄", "emby_value": 1},
        {"code": "TV-Y", "label": "全年龄", "emby_value": 1},
        {"code": "TV-G", "label": "全年龄", "emby_value": 1},
        {"code": "TV-Y7", "label": "家长辅导", "emby_value": 4},
        {"code": "PG", "label": "家长辅导", "emby_value": 5},
        {"code": "TV-PG", "label": "家长辅导", "emby_value": 5},
        {"code": "PG-13", "label": "青少年", "emby_value": 8},
        {"code": "TV-14", "label": "青少年", "emby_value": 8},
        {"code": "R", "label": "限制级", "emby_value": 9},
        {"code": "TV-MA", "label": "限制级", "emby_value": 9},
        {"code": "NC-17", "label": "18禁", "emby_value": 10},
        {"code": "XXX", "label": "成人", "emby_value": 15},
        {"code": "NR", "label": "未知", "emby_value": 0},
        {"code": "Unrated", "label": "未知", "emby_value": 0}
    ],
    "JP": [
        {"code": "G", "label": "全年龄", "emby_value": 1},
        {"code": "PG12", "label": "家长辅导", "emby_value": 5},
        {"code": "R15+", "label": "限制级", "emby_value": 9},
        {"code": "R18+", "label": "18禁", "emby_value": 10},
        # --- 兼容旧数据/数字录入 ---
        {"code": "12", "label": "家长辅导", "emby_value": 5},
        {"code": "15", "label": "限制级", "emby_value": 9},
        {"code": "18", "label": "18禁", "emby_value": 10}
    ],
    "HK": [
        {"code": "I", "label": "全年龄", "emby_value": 1},
        {"code": "IIA", "label": "家长辅导", "emby_value": 5},
        {"code": "IIB", "label": "限制级", "emby_value": 9}, 
        {"code": "III", "label": "18禁", "emby_value": 10},
        # --- 兼容 TMDb 历史遗留数字录入 ---
        {"code": "15", "label": "限制级", "emby_value": 9}, # 对应 IIB
        {"code": "18", "label": "18禁", "emby_value": 10}  # 对应 III
    ],
    "TW": [
        {"code": "0+", "label": "全年龄", "emby_value": 1},
        {"code": "6+", "label": "家长辅导", "emby_value": 5},
        {"code": "12+", "label": "青少年", "emby_value": 8},
        {"code": "15+", "label": "限制级", "emby_value": 9},
        {"code": "18+", "label": "18禁", "emby_value": 10},
        # --- 兼容无“+”号的数字录入 ---
        {"code": "0", "label": "全年龄", "emby_value": 1},
        {"code": "6", "label": "家长辅导", "emby_value": 5},
        {"code": "12", "label": "青少年", "emby_value": 8},
        {"code": "15", "label": "限制级", "emby_value": 9},
        {"code": "18", "label": "18禁", "emby_value": 10}
    ],
    "KR": [
        {"code": "All", "label": "全年龄", "emby_value": 1},
        {"code": "12", "label": "家长辅导", "emby_value": 5},
        {"code": "15", "label": "青少年", "emby_value": 8},
        {"code": "19", "label": "限制级", "emby_value": 9},
        {"code": "Restricted Screening", "label": "18禁", "emby_value": 10},
        # --- 兼容韩国有时会录入 18 而非 19 的情况 ---
        {"code": "18", "label": "限制级", "emby_value": 9}
    ],
    "GB": [
        {"code": "U", "label": "全年龄", "emby_value": 1},
        {"code": "PG", "label": "家长辅导", "emby_value": 5},
        {"code": "12", "label": "青少年", "emby_value": 8},
        {"code": "12A", "label": "青少年", "emby_value": 8},
        {"code": "15", "label": "限制级", "emby_value": 9},
        {"code": "18", "label": "限制级", "emby_value": 9},
        {"code": "R18", "label": "18禁", "emby_value": 10}
    ],
    "ES": [
        {"code": "TP", "label": "全年龄", "emby_value": 1},
        {"code": "7", "label": "家长辅导", "emby_value": 5},
        {"code": "12", "label": "青少年", "emby_value": 8},
        {"code": "16", "label": "限制级", "emby_value": 9},
        {"code": "18", "label": "18禁", "emby_value": 10}
    ],
    "DE": [
        {"code": "0", "label": "全年龄", "emby_value": 1},
        {"code": "6", "label": "家长辅导", "emby_value": 5},
        {"code": "12", "label": "青少年", "emby_value": 8},
        {"code": "16", "label": "限制级", "emby_value": 9},
        {"code": "18", "label": "18禁", "emby_value": 10}   
    ]
}

# --- Release group defaults ---
DEFAULT_RELEASE_GROUP_MAPPING = {
    "0ff": ['FF(?:(?:A|WE)B|CD|E(?:DU|B)|TV)'],
    "观众": ['Audies', r'\bAD(?:Audio|E(?:book|)|Music|Web)\b'],
    "备胎": ['BeiTai'],
    "学校": ['Bts(?:CHOOL|HD|PAD|TV)', 'Zone'],
    "车": ['CarPT'],
    "彩虹岛": ['CHD(?:Bits|PAD|(?:|HK)TV|WEB|)', 'StBOX', 'OneHD', 'Lee', 'xiaopie'],
    "碟粉": ['discfan'],
    "eastgame": ['(?:(?:iNT|(?:HALFC|Mini(?:S|H|FH)D))-|)TLF'],
    "gainbound": ['(?:DG|GBWE)B'],
    "hares": ['Hares(?:(?:M|T)V|Web|)'],
    "高清视界": ['HDA(?:pad|rea|TV)', 'EPiC'],
    "阿童木": ['hdatmos'],
    "hdchina": ['HDC(?:hina|TV|)', 'k9611', 'tudou', 'iHD'],
    "杜比": ['D(?:ream|BTV)', '(?:HD|QHstudI)o'],
    "红豆饭": ['beAst(?:TV|)', 'HDFans'],
    "家园": ['HDH(?:ome|Pad|TV|WEB|)'],
    "hdpt": ['HDPT(?:Web|)'],
    "天空": ['HDS(?:ky|TV|Pad|WEB|)', 'AQLJ'],
    "高清时间": ['hdtime'],
    "hdzone": ['HDZ(?:one|)'],
    "憨憨": ['HHWEB'],
    "末日": ['AGSV(PT|WEB|MUS)'],
    "htpt": ['HTPT'],
    "朋友": ['FRDS', 'Yumi', 'cXcY'],
    "柠檬": ['L(?:eague(?:(?:C|H)D|(?:M|T)V|NF|WEB)|HD)', 'i18n', 'CiNT'],
    "馒头": ['MTeam(?:TV|)', 'MPAD', 'MWeb'],
    "老师": ['nicept'],
    "我堡": ['Our(?:Bits|TV)', 'FLTTH', 'PbK', 'MGs', 'iLove(?:HD|TV)'],
    "猪猪": ['PiGo(?:NF|(?:H|WE)B)'],
    "铂金学院": ['ptchina'],
    "猫站": ['PTer(?:DIY|Game|(?:M|T)V|WEB|)'],
    "pthome": ['PTH(?:Audio|eBook|music|ome|tv|WEB|)'],
    "烧包": ['PTsbao', 'OPS', 'F(?:Fans(?:AIeNcE|BD|D(?:VD|IY)|TV|WEB)|HDMv)', 'SGXT'],
    "葡萄": ['PuTao'],
    "聆音": ['lingyin'],
    "春天": [r"CMCT(?:A|V)?", "Oldboys", "GTR", "CLV", "CatEDU", "Telesto", "iFree"],
    "鲨鱼": ['Shark(?:WEB|DIY|TV|MV|)'],
    "他吹吹风": ['tccf'],
    "北洋园": ['TJUPT'],
    "听听歌": ['TTG', 'WiKi', 'NGB', 'DoA', '(?:ARi|ExRE)N'],
    "others": ['B(?:MDru|eyondHD|TN)', 'C(?:fandora|trlhd|MRG)', 'DON', 'EVO', 'FLUX', 'HONE(?:yG|)',
               'N(?:oGroup|T(?:b|G))', 'PandaMoon', 'SMURF', 'T(?:EPES|aengoo|rollHD )'],
    "anime": [r'\bANi\b', r'\bHYSUB\b', r'\bKTXP\b', 'LoliHouse', r'\bMCE\b', 'Nekomoe kissaten', 'SweetSub', 'MingY',
              '(?:Lilith|NC|AI)-Raws', 'VCB-Stuido', '织梦字幕组', '枫叶字幕组', '猎户手抄部', '喵萌奶茶屋', '漫猫字幕社',
              '霜庭云花Sub', '北宇治字幕组', '氢气烤肉架', '云歌字幕组', '萌樱字幕组', '极影字幕社',
              '悠哈璃羽字幕社',
              '❀拨雪寻春❀', '沸羊羊(?:制作|字幕组)', '(?:桜|樱)都字幕组'],
    "青蛙": ['FROG(?:E|Web|)'],
    "ubits": ['UB(?:its|WEB|TV)'],
    "影巢": ['HiveWeb'],
}

# 115 整理时用于忽略样本、预告及花絮文件的文件名正则。
DEFAULT_JUNK_FILE_PATTERNS = [
    r'(?i)\b(sample|trailer|featurette|bonus)\b',
    r'(?i)Special Ending Movie',
    r'(?i)\[((TV|BD|\bBlu-ray\b)?\s*CM\s*\d{2,3})\]',
    r'(?i)\[Teaser.*?\]',
    r'(?i)\[PV.*?\]',
    r'(?i)\[NC[OPED]+.*?\]',
    r'(?i)\[S\d+\s+Recap(\s+\d+)?\]',
    r'(?i)Preview',
    r'(?i)\b(CDs|SPs|Scans|Bonus|映像特典|映像|specials|特典CD|Logo|Preview|/mv)\b',
    r'(?i)\b(NC)?(Disc|片头|OP|SP|ED|Advice|Trailer|BDMenu|片尾|PV|CM|Preview|Info|EDPV|SongSpot|BDSpot)(\d{0,2}|_ALL)\b',
    r'(?i)WiKi\.sample',
]

# --- 关键词预设表 ---
DEFAULT_KEYWORD_MAPPING = [
    {"label": "丧尸", "en": ["zombie"], "ids": [12377]},
    {"label": "二战", "en": ["world war ii"], "ids": [1956]},
    {"label": "吸血鬼", "en": ["vampire"], "ids": [3133]},
    {"label": "外星人", "en": ["alien"], "ids": [9951]},
    {"label": "漫改", "en": ["based on comic"], "ids": [9717]},
    {"label": "超级英雄", "en": ["superhero"], "ids": [9715]},
    {"label": "机器人", "en": ["robot"], "ids": [14544]},
    {"label": "怪兽", "en": ["monster"], "ids": [161791]},
    {"label": "恐龙", "en": ["dinosaur"], "ids": [12616]},
    {"label": "灾难", "en": ["disaster"], "ids": [10617]},
    {"label": "人工智能", "en": ["artificial intelligence (a.i.)"], "ids": [310]},
    {"label": "时间旅行", "en": ["time travel"], "ids": [4379]},
    {"label": "赛博朋克", "en": ["cyberpunk"], "ids": [12190]},
    {"label": "后末日", "en": ["post-apocalyptic future"], "ids": [4458]},
    {"label": "反乌托邦", "en": ["dystopia"], "ids": [4565]},
    {"label": "太空", "en": ["space"], "ids": [9882]},
    {"label": "魔法", "en": ["magic"], "ids": [2343]},
    {"label": "鬼", "en": ["ghost"], "ids": [10292]},
    {"label": "连环杀手", "en": ["serial killer"], "ids": [10714]},
    {"label": "复仇", "en": ["revenge"], "ids": [9748]},
    {"label": "间谍", "en": ["spy"], "ids": [470]},
    {"label": "武术", "en": ["martial arts"], "ids": [779]},
    {"label": "功夫", "en": ["kung fu"], "ids": [780]},
    {"label": "古装", "en": ["costume drama"], "ids": [195013]},
    {"label": "仙侠", "en": ["xianxia"], "ids": [234890]},
    {"label": "恐怖", "en": ["horror", "clown", "macabre"], "ids": [315058, 3199, 162810]},
    {"label": "惊悚", "en": ["thriller", "gruesome"], "ids": [10526, 186416]},
    {"label": "赛车", "en": ["car race", "street-race"], "ids": [830, 9666]},
    {"label": "怪物", "en": ["cmonster"], "ids": [1299]},
    {"label": "特工", "en": ["secret agent"], "ids": [4289]},
]

# --- 工作室预设表 ---
DEFAULT_STUDIO_MAPPING = [
    # --- 国内平台 (纯 Network) ---
    {"label": "CCTV-1", "en": ["CCTV-1"], "network_ids": [1363]}, 
    {"label": "CCTV-8", "en": ["CCTV-8"], "network_ids": [521]},
    {"label": "湖南卫视", "en": ["Hunan TV"], "network_ids": [952]},
    {"label": "浙江卫视", "en": ["Zhejiang Television"], "network_ids": [989]},
    {"label": "江苏卫视", "en": ["Jiangsu Television"], "network_ids": [1055]},
    {"label": "北京卫视", "en": ["Beijing Television"], "network_ids": [455]},
    {"label": "东方卫视", "en": ["Dragon Television"], "network_ids": [1056]},
    {"label": "腾讯视频", "en": ["Tencent Video"], "network_ids": [2007]},
    {"label": "爱奇艺", "en": ["iQiyi"], "network_ids": [1330]},
    {"label": "优酷", "en": ["Youku"], "network_ids": [1419]},
    {"label": "芒果TV", "en": ["Mango TV"], "network_ids": [1631]},
    {"label": "哔哩哔哩", "en": ["Bilibili"], "network_ids": [1605]},
    {"label": "TVB", "en": ["TVB Jade", "Television Broadcasts Limited"], "network_ids": [48, 79261]},

    # --- 全球流媒体/电视网 (Network + Company) ---
    # 这些巨头通常既作为播出平台(Network)，也作为制作公司(Company)存在
    {"label": "网飞", "en": ["Netflix"], "network_ids": [213], "company_ids": [178464]},
    {"label": "HBO", "en": ["HBO"], "network_ids": [49], "company_ids": [3268]},
    {"label": "迪士尼", "en": ["Disney+", "Walt Disney Pictures"], "network_ids": [2739], "company_ids": [2]},
    {"label": "苹果TV", "en": ["Apple TV+"], "network_ids": [2552], "company_ids": [108568]},
    {"label": "亚马逊", "en": ["Amazon Prime Video"], "network_ids": [1024], "company_ids": [20555]},
    {"label": "Hulu", "en": ["Hulu"], "network_ids": [453], "company_ids": [15365]},
    {"label": "正午阳光", "en": ["Daylight Entertainment"], "network_ids": [148869], "company_ids": [148869]},

    # --- 传统制作公司 (纯 Company) ---
    {"label": "二十世纪影业", "en": ["20th century fox"], "company_ids": [25]},
    {"label": "康斯坦丁影业", "en": ["Constantin Film"], "company_ids": [47]},
    {"label": "派拉蒙", "en": ["Paramount Pictures"], "company_ids": [4]},
    {"label": "华纳兄弟", "en": ["Warner Bros. Pictures"], "company_ids": [174]},
    {"label": "环球影业", "en": ["Universal Pictures"], "company_ids": [33]},
    {"label": "哥伦比亚影业", "en": ["Columbia Pictures"], "company_ids": [5]},
    {"label": "米高梅", "en": ["Metro-Goldwyn-Mayer"], "company_ids": [21]},
    {"label": "狮门影业", "en": ["Lionsgate"], "company_ids": [1632]}, 
    {"label": "传奇影业", "en": ["Legendary Pictures", "Legendary Entertainment"], "company_ids": [923]},
    {"label": "试金石影业", "en": ["Touchstone Pictures"], "company_ids": [9195]},
    {"label": "漫威", "en": ["Marvel Studios", "Marvel Entertainment"], "company_ids": [420, 7505]},
    {"label": "DC", "en": ["DC"], "company_ids": [128064, 9993]},
    {"label": "皮克斯", "en": ["Pixar"], "company_ids": [3]},
    {"label": "梦工厂", "en": ["DreamWorks Animation", "DreamWorks"], "company_ids": [521]},
    {"label": "吉卜力", "en": ["Studio Ghibli"], "company_ids": [10342]},
    {"label": "中国电影集团", "en": ["China Film Group"], "company_ids": [2270]},
    {"label": "登峰国际", "en": ["DF Pictures"], "company_ids": [65442]},
    {"label": "光线影业", "en": ["Beijing Enlight Pictures"], "company_ids": [17818]},
    {"label": "万达影业", "en": ["Wanda Pictures"], "company_ids": [78952]},
    {"label": "博纳影业", "en": ["Bonanza Pictures"], "company_ids": [30148]},
    {"label": "阿里影业", "en": ["Alibaba Pictures Group"], "company_ids": [69484]},
    {"label": "上影", "en": ["Shanghai Film Group"], "company_ids": [3407]},
    {"label": "华谊兄弟", "en": ["Huayi Brothers"], "company_ids": [76634]},
    {"label": "寰亚电影", "en": ["Media Asia Films"], "company_ids": [5552]},
]

# --- 国家预设表 ---
DEFAULT_COUNTRY_MAPPING = [
    {"label": "中国大陆", "value": "CN", "aliases": ["China", "PRC"]},
    {"label": "中国香港", "value": "HK", "aliases": ["Hong Kong"]},
    {"label": "中国台湾", "value": "TW", "aliases": ["Taiwan"]},
    {"label": "美国", "value": "US", "aliases": ["United States of America", "USA"]},
    {"label": "英国", "value": "GB", "aliases": ["United Kingdom", "UK"]},
    {"label": "日本", "value": "JP", "aliases": ["Japan"]},
    {"label": "韩国", "value": "KR", "aliases": ["South Korea", "Korea, Republic of"]},
    {"label": "法国", "value": "FR", "aliases": ["France"]},
    {"label": "德国", "value": "DE", "aliases": ["Germany"]},
    {"label": "意大利", "value": "IT", "aliases": ["Italy"]},
    {"label": "西班牙", "value": "ES", "aliases": ["Spain"]},
    {"label": "加拿大", "value": "CA", "aliases": ["Canada"]},
    {"label": "澳大利亚", "value": "AU", "aliases": ["Australia"]},
    {"label": "印度", "value": "IN", "aliases": ["India"]},
    {"label": "俄罗斯", "value": "RU", "aliases": ["Russia"]},
    {"label": "泰国", "value": "TH", "aliases": ["Thailand"]},
    {"label": "瑞典", "value": "SE", "aliases": ["Sweden"]},
    {"label": "丹麦", "value": "DK", "aliases": ["Denmark"]},
    {"label": "挪威", "value": "NO", "aliases": ["Norway"]},
    {"label": "荷兰", "value": "NL", "aliases": ["Netherlands"]},
    {"label": "巴西", "value": "BR", "aliases": ["Brazil"]},
    {"label": "墨西哥", "value": "MX", "aliases": ["Mexico"]},
    {"label": "阿根廷", "value": "AR", "aliases": ["Argentina"]},
    {"label": "新西兰", "value": "NZ", "aliases": ["New Zealand"]},
    {"label": "爱尔兰", "value": "IE", "aliases": ["Ireland"]},
    {"label": "新加坡", "value": "SG", "aliases": ["Singapore"]},
    {"label": "比利时", "value": "BE", "aliases": ["Belgium"]},
    {"label": "芬兰", "value": "FI", "aliases": ["Finland"]},
    {"label": "波兰", "value": "PL", "aliases": ["Poland"]},
]

# --- 音视频流/字幕流特色标签映射 ---
# 用于识别并标准化 DYSY、CCTV、上译、公映 等特色标签
DEFAULT_STREAM_FEATURE_MAPPING = [
    {
        "label": "上译",  # 统一标准化为“上译”
        "types": ["Audio", "Subtitle"],
        "patterns": [
            r"(?<![A-Za-z0-9])SY(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9])CYSY(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9])DYSY(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9])GYSY(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9])CH-DYSY(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9])GP-DYSY(?![A-Za-z0-9])",
            r"上译",
            r"东影上译",
            r"泰盛上译",
            r"上海电影译制",
            r"上海电影配音",
            r"上海译制",
            r"上海配音",
            r"公映上译",
            r"上譯"
        ],
    },
    {
        "label": "公映",
        "types": ["Audio", "Subtitle"],
        "patterns": [
            r"(?<![A-Za-z0-9])GY(?![A-Za-z0-9])",
            r"公映",
            r"院线配音",
            r"影院版"
        ],
    },
    {
        "label": "长译",
        "types": ["Audio", "Subtitle"],
        "patterns": [
            r"(?<![A-Za-z0-9])CY(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9])GYCY(?![A-Za-z0-9])",
            r"长译",
            r"长春电影"
        ],
    },
    {
        "label": "京译",
        "types": ["Audio", "Subtitle"],
        "patterns": [
            r"(?<![A-Za-z0-9])JY(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9])GYJY(?![A-Za-z0-9])",
            r"京译",
            r"中影配音",
            r"北京电影"
        ],
    },
    {
        "label": "八一",
        "types": ["Audio", "Subtitle"],
        "patterns": [
            r"八一",  
        ],
    },
    {
        "label": "六区",
        "types": ["Audio", "Subtitle"],
        "patterns": [
            r"六区",  
        ],
    },
    {
        "label": "华纳",
        "types": ["Audio", "Subtitle"],
        "patterns": [
            r"华纳",  
        ],
    },
    {
        "label": "中影",
        "types": ["Audio", "Subtitle"],
        "patterns": [
            r"中影",  
        ],
    },
    {
        "label": "央视",
        "types": ["Audio", "Subtitle"],
        "patterns": [
            r"(?<![A-Za-z0-9])CCTV(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9])GP-CCTV(?![A-Za-z0-9])",
            r"央视",
            r"CCTV6"
        ],
    },
    {
        "label": "台配",
        "types": ["Audio", "Subtitle"],
        "patterns": [
            r"台配",
            r"台湾配音"
        ],
    },
    {
    "label": "台湾",
    "types": ["Subtitle"],
    "patterns": [
        "(?<![A-Za-z0-9])TW(?![A-Za-z0-9])",
        "台灣",
        "臺灣",
        "台湾",
        "台配",
        "台灣配音",
        "臺灣配音",
        "台湾配音"
    ]
    },
    {
    "label": "香港",
    "types": ["Subtitle"],
    "patterns": [
        "(?<![A-Za-z0-9])HK(?![A-Za-z0-9])",
        "港配",
        "香港配音",
        "港",
    ]
    },
    {
        "label": "国语",
        "types": ["Subtitle"],
        "patterns": [
            r"国语",
            r"国配",
        ],
    },
    {
        "label": "官译",
        "types": ["Subtitle"],
        "patterns": [
            r"官译",
            r"官方",
        ],
    },
    {
        "label": "原声",
        "types": ["Subtitle"],
        "patterns": [
            r"原声",
            r"原音",
        ],
    },
    {
        "label": "特效",
        "types": ["Subtitle"],
        "patterns": [
            r"(?<![A-Za-z0-9])TX(?![A-Za-z0-9])",
            r"特效",
        ],
    },
    {
        "label": "HDR",
        "types": ["Subtitle"],
        "patterns": [
            r"(?<![A-Za-z0-9])HDR(?![A-Za-z0-9])",
            r"HDR",
        ],
    },
    {
        "label": "SDR",
        "types": ["Subtitle"],
        "patterns": [
            r"(?<![A-Za-z0-9])SDR(?![A-Za-z0-9])",
            r"SDR",
        ],
    },
    {
        "label": "DoVi",
        "types": ["Subtitle"],
        "patterns": [
            r"(?<![A-Za-z0-9])DoVi(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9])DV(?![A-Za-z0-9])",
            r"DoVi",
        ],
    },
    {
        "label": "拉美",
        "types": ["Subtitle", "Audio"],
        "patterns": [
            r"\bLatin\s*America\b",
            r"\bLatin\s*American\b",
            r"\bLatin[-_\s]*America\b",
            r"\bLatin[-_\s]*American\b",
            r"\bLATAM\b",
            r"\bLatinoamerica\b",
            r"\bLatinoam[eé]rica\b",
            r"拉美",
            r"拉丁美洲",
        ],
    },
    {
        "label": "巴西",
        "types": ["Subtitle", "Audio"],
        "patterns": [
            r"\bBrazil\b",
            r"\bBrasil\b",
            r"\bBrazilian\b",
            r"\bBrasilian\b",
            r"\bBrasileiro\b",
            r"\bBrasileira\b",
            r"\bPortuguese\s*\(?Brazil\)?\b",
            r"\bPortuguese\s*[-_]\s*Brazil\b",
            r"巴西",
        ],
    },
    {
        "label": "听障",
        "types": ["Subtitle"],
        "patterns": [
            r"(?<![A-Za-z0-9])SDH(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9])CC(?![A-Za-z0-9])",
            r"hearing impaired",
            r"hard of hearing",
            r"听障",
        ],
    },
    {
        "label": "导评",
        "types": ["Audio", "Subtitle"],
        "patterns": [
            r"Director'?s Commentary",
            r"Audio Commentary",
            r"Commentary",
            r"导评",
        ],
    },
]

# --- 音轨/字幕无意义压制组/字幕组过滤名单 ---
# 只要出现在这里的词，都会从音轨和字幕的标题中被无情抹除
STREAM_TITLE_GARBAGE_FILTER = [
    "麦哈", "说一不二", "人人字幕组", "人人影视", "远鉴字幕组", "衣柜字幕组", 
    "霸王龙压制组", "字幕组", "压制组", "手抄", "调轴", "精校", "原创", "校对", 
    "后期", "翻译", "制作", "发布", "团队", "组", "字幕", "配音", "合金弹头",
    "山茶树", "木木"
]


DEFAULT_AI_PROMPTS = {
    "fast_mode": """你是一个只返回 JSON 格式的翻译 API。
你的任务是将一系列人名（如演员、演职人员）从各种语言翻译成 **简体中文**。

**必须** 返回一个有效的 JSON 对象，将原始名称映射到其中文翻译。
- 源语言可能是任何语言（如英语、日语、韩语、拼音）。
- 目标语言 **必须永远是** 简体中文。
- 如果名字无法翻译或已经是中文，请使用原始名字作为值。
- **某些名字可能不完整或包含首字母（如 "Peter J."）；请根据现有部分提供最可能的标准音译。**
- 不要添加任何解释或 JSON 对象以外的文本。""",

    "transliterate_mode": """你是一个只返回 JSON 格式的影视人名中文化 API。
你的任务是将一系列影视相关的人名（演员、导演、编剧、制作人等）转换为适合中文媒体库展示的 **简体中文姓名**。

规则：
1. 优先使用该人物在中文世界最常见、最通用的译名。
2. 如果没有公认译名，再根据发音进行自然、常见的中文音译。
3. 目标语言必须永远是简体中文。
4. 如果名字已经是中文，保持原样。
5. 如果名字包含首字母、缩写或不完整部分，请尽力翻译可识别部分。
6. 如果实在无法处理，使用原始名字作为值。
7. 必须返回合法 JSON 对象，键为原文，值为中文结果。
8. 不要输出任何解释、注释、Markdown 或额外文本。""",

    "quality_mode": """你是一位世界级的影视专家，扮演一个只返回 JSON 的 API。
你的任务是利用提供的影视上下文，准确地将外语或拼音的演员名和角色名翻译成 **简体中文**。

**输入格式：**
你将收到一个包含 `context`（含 `title` 和 `year`）和 `terms`（待翻译字符串列表）的 JSON 对象。

**你的策略：**
1. **利用上下文：** 使用 `title` 和 `year` 来确定具体的剧集/电影。在该特定作品的背景下，找到 `terms` 的官方或最受认可的中文译名。这对角色名至关重要。
2. **翻译拼音：** 如果词条是拼音（如 "Zhang San"），请将其翻译成汉字（"张三"）。
3. **【核心指令】**
   **目标语言永远是简体中文：** 无论作品或名字的原始语言是什么（如韩语、日语、英语），你的最终输出翻译 **必须** 是 **简体中文**。不要翻译成该剧的原始语言。
4. **兜底：** 如果一个词条无法或不应被翻译，你 **必须** 使用原始字符串作为其值。

**输出格式（强制）：**
你 **必须** 返回一个有效的 JSON 对象，将每个原始词条映射到其中文翻译。严禁包含其他文本或 markdown 标记。""",

    "overview_translation": """你是一位专门从事影视剧情简介翻译的专业译者。
你的任务是将提供的英文简介翻译成 **流畅、引人入胜的简体中文**。

**指南：**
1. **语调：** 专业、吸引人，适合作为媒体库的介绍。避免机器翻译的生硬感。
2. **准确性：** 保留原意、关键情节和基调（如喜剧与恐怖）。
3. **人名：** 如果简介中包含演员或角色的名字，如果知道其标准中文译名，请进行翻译；如果不确定，请保留英文。
4. **输出：** 返回一个有效的 JSON 对象，包含一个键 "translation"，值为翻译后的文本。

**输入：**
标题: {title}
简介: {overview}

**输出格式：**
{{
  "translation": "..."
}}""",

    "title_translation": """你是一位影视数据库的专业编辑。
你的任务是将提供的标题翻译成 **简体中文**。

**规则：**
1. **电影/剧集：** 如果类型是 'Movie' 或 'Series'，优先使用现有的中国大陆官方译名。如果没有，使用标准音译或意译。
2. **分集 (关键)：** 如果类型是 'Episode'，**直接翻译标题的含义（意译）**。不要保留英文，除非它是无法翻译的专有名词。
   * 例如: "The Weekend in Paris Job" -> "巴黎周末行动" 或 "巴黎周末任务"
   * 例如: "Pilot" -> "试播集"
3. **风格：** 保持简洁、专业。
4. **无额外文本：** 不要包含年份或解释。
5. **输出：** 返回一个有效的 JSON 对象。

**输入：**
类型: {media_type}
原标题: {title}
年份: {year}

**输出格式：**
{{
  "translation": "..."
}}""",

    "filename_parsing": """你是一个影视文件名解析专家。
你的任务是从不规范的影视文件或文件夹名称中，提取出用于搜索的【核心片名】、【年份】和【类型】。

规则：
1. 移除所有广告词、分辨率(1080p/4k)、压制组、视频格式(mp4/mkv)、音视频编码(H265/AAC)等无关信息。
2. 如果包含中英文双语标题，优先提取【中文标题】。
3. 类型(type)只能是 "movie" (电影) 或 "tv" (剧集)。如果包含 S01, E01, 第x季, 完结 等字眼，则是 tv。
4. 年份(year)提取4位数字，如果没有则返回空字符串。
5. 必须返回严格的 JSON 格式。

输入文件名：{filename}

输出格式：
{{
  "title": "提取的纯净片名",
  "year": "2023",
  "type": "movie"
}}""",

    "batch_overview_translation": """你是一个专业的影视翻译专家。
请将以下 JSON 格式的影视剧情简介翻译成流畅、自然的简体中文。
上下文影视名称：{context_title}

**【最高指令 / 严格要求】**：
1. **绝对禁止修改键名**：必须 100% 保持原有的 JSON 键（ID）不变！绝对不允许新增、删除或篡改任何键名！
2. **只翻译值**：只翻译简介内容，遇到人名如果不确定中文译名请保留英文。
3. **符合中文习惯**：翻译要流畅自然，拒绝生硬的机翻腔调。
4. **纯 JSON 输出**：你必须且只能输出一个合法的 JSON 对象。**绝对不要**包含任何解释性文字，**绝对不要**使用 ```json 这样的 Markdown 代码块标记包裹！

**输入示例：**
{{
  "123": "This is an overview.",
  "456": "Another overview here."
}}

**输出示例：**
{{
  "123": "这是一个简介。",
  "456": "这里是另一个简介。"
}}""",

    "batch_title_translation": """你是一个专业的影视翻译专家。
请将以下 JSON 格式的影视标题（类型：{media_type}）翻译成流畅、自然的简体中文。

**【最高指令 / 严格要求】**：
1. **绝对禁止修改键名**：必须 100% 保持原有的 JSON 键（ID）不变！绝对不允许新增、删除或篡改任何键名！
2. **只翻译值**：只翻译标题内容。如果标题已经是中文，请保持原样返回。
3. **专有名词**：如果是人名或专有名词，请提供通用的中文译名或音译。
4. **纯 JSON 输出**：你必须且只能输出一个合法的 JSON 对象。**绝对不要**包含任何解释性文字，**绝对不要**使用 ```json 这样的 Markdown 代码块标记包裹！

**输入示例：**
{{
  "123": "The Beginning",
  "456": "A New Hope"
}}

**输出示例：**
{{
  "123": "开端",
  "456": "新希望"
}}""",

    "batch_joke_fallback": """你是一个幽默、嘴碎的影视解说员“老六”。
以下影视项目（或分集）目前缺少官方剧情简介，请你发挥想象力，为它们分别编一个简短、幽默的冷笑话、吐槽或段子来占位。

**【最高指令 / 严格要求】**：
1. **必须带有前缀**：每个笑话必须以“【老六占位简介】”开头！
2. **简短有趣**：50字以内，如果是剧集分集，可以结合“第X集”调侃一下追剧人的日常（比如催更、水剧情、主角光环等）。
3. **纯 JSON 输出**：必须且只能输出一个合法的 JSON 对象，键名为提供的ID，键值为生成的笑话。绝对不要包含任何解释性文字或 Markdown 代码块标记！

输入示例：
{
    "S1E1": "权力的游戏 S1E1",
    "movie_123": "阿凡达3"
}
输出示例：
{
    "S1E1": "【老六占位简介】凛冬将至，但我连秋裤都还没买，这集主要讲大家怎么凑钱买煤。",
    "movie_123": "【老六占位简介】导演还在水里憋气呢，简介等他浮上来再写吧。"
}"""
}
