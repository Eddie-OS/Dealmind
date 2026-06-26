"""国家 / 货币 / 可信信源域名 单一映射表 + persona 推断器。

v0.2.1 真实性 / 地区一致性补丁的"数据底座"：
- 11 个国家（覆盖现有 44 个 persona）的 currency + market_domains 内置常量
- ``infer_market_from_persona`` 根据 persona.locale / source / prompt_text 关键词
  自动反推国家 → 给 patch 脚本和 UI"自动填充"按钮共用

设计原则：
- **strict_local**：每个国家的 market_domains 只列该国 huawei 官网 + 该国主流电商 1-2 个，
  避免 web_search 跨境
- **可扩展**：新增国家只要在 ``COUNTRY_REGISTRY`` 里加一项；推断器自动覆盖
- **失败安全**：推不出来时返回 ``DEFAULT_GLOBAL_MARKET``（user 决策 q3=default_global）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CountryMarket:
    """单个国家的市场信息。供 sales_prompt / web_search / Judge 共用。"""

    code: str                 # ISO-3166-1 alpha-2，如 "MY"
    name_cn: str              # 中文显示名，如 "马来西亚"
    name_en: str              # 英文显示名，如 "Malaysia"
    currency: str             # ISO-4217，如 "MYR"
    currency_symbol: str      # 显示符号，如 "RM"
    market_domains: list[str] = field(default_factory=list)
    # 推断关键词：source / prompt_text 出现任一即视为命中此国家
    infer_keywords: tuple[str, ...] = field(default_factory=tuple)

    @property
    def display(self) -> str:
        """sales_prompt / UI 用的紧凑显示字符串。"""
        return f"{self.name_cn} {self.name_en} ({self.code} · {self.currency} {self.currency_symbol})"


# ============================================================
# 11 个国家市场（覆盖现有 44 个 persona）
# ============================================================
# 域名约定：每个国家只列
#   1) consumer.huawei.com/<country_code_lower>  — 华为官方该国分站
#   2) 1-2 个该国主流电商或运营商旗舰店
# 总数控制在 ≤ 4，避免 query OR 太长。

COUNTRY_REGISTRY: dict[str, CountryMarket] = {
    "MY": CountryMarket(
        code="MY", name_cn="马来西亚", name_en="Malaysia",
        currency="MYR", currency_symbol="RM",
        market_domains=[
            "consumer.huawei.com/my",
            "shopee.com.my",
            "lazada.com.my",
        ],
        infer_keywords=(
            "malaysia", "malaysian", "kuala lumpur", "KL ", "lowyat",
            "马来西亚", "马来", "吉隆坡", "槟城", "雪兰莪", "八打灵", "PJ ",
            "RM2", "RM3", "RM4", "RM5", "马来亚大学", "Lowyat", "shopee.com.my",
        ),
    ),
    "PH": CountryMarket(
        code="PH", name_cn="菲律宾", name_en="Philippines",
        currency="PHP", currency_symbol="₱",
        market_domains=[
            "consumer.huawei.com/ph",
            "shopee.ph",
            "lazada.com.ph",
        ],
        infer_keywords=(
            "philippines", "philippine", "manila", "cebu", "quezon",
            "菲律宾", "马尼拉", "宿务", "奎松", "达沃", "BGC", "Ateneo",
            "studentsph", "phmoneysa", "Tech_Philippines", "shopee.ph",
        ),
    ),
    "ID": CountryMarket(
        code="ID", name_cn="印度尼西亚", name_en="Indonesia",
        currency="IDR", currency_symbol="Rp",
        market_domains=[
            "consumer.huawei.com/id",
            "tokopedia.com",
            "shopee.co.id",
        ],
        infer_keywords=(
            "indonesia", "indonesian", "jakarta", "surabaya", "bandung",
            "印度尼西亚", "印尼", "雅加达", "万隆", "泗水", "Jaksel",
            "tokopedia", "shopee.co.id",
        ),
    ),
    "TH": CountryMarket(
        code="TH", name_cn="泰国", name_en="Thailand",
        currency="THB", currency_symbol="฿",
        market_domains=[
            "consumer.huawei.com/th",
            "lazada.co.th",
            "shopee.co.th",
        ],
        infer_keywords=(
            "thailand", "thai", "bangkok", "chiang mai",
            "泰国", "曼谷", "清迈", "朱拉隆功", "Pantip", "Studygramthailand",
            "lazada.co.th", "shopee.co.th",
        ),
    ),
    "AE": CountryMarket(
        code="AE", name_cn="阿联酋", name_en="United Arab Emirates",
        currency="AED", currency_symbol="د.إ",
        market_domains=[
            "consumer.huawei.com/ae",
            "amazon.ae",
            "noon.com",
        ],
        infer_keywords=(
            "uae", "united arab emirates", "dubai", "abu dhabi",
            "阿联酋", "迪拜", "阿布扎比", "DIFC", "ExpatWoman",
            "amazon.ae", "noon.com",
        ),
    ),
    "SA": CountryMarket(
        code="SA", name_cn="沙特阿拉伯", name_en="Saudi Arabia",
        currency="SAR", currency_symbol="﷼",
        market_domains=[
            "consumer.huawei.com/sa",
            "amazon.sa",
            "noon.com",
        ],
        infer_keywords=(
            "saudi", "saudi arabia", "riyadh", "jeddah", "dhahran", "dammam",
            "沙特", "沙特阿拉伯", "利雅得", "吉达", "宰兰", "达曼", "KFUPM",
            "ADSLGate", "amazon.sa",
        ),
    ),
    "ZA": CountryMarket(
        code="ZA", name_cn="南非", name_en="South Africa",
        currency="ZAR", currency_symbol="R",
        market_domains=[
            "consumer.huawei.com/za",
            "takealot.com",
            "incredible.co.za",
        ],
        infer_keywords=(
            "south africa", "south african", "johannesburg", "cape town",
            "pretoria", "sandton",
            "南非", "约翰内斯堡", "开普敦", "普利托里亚",
            "MyBroadband", "Reddit SA", "takealot",
        ),
    ),
    "TR": CountryMarket(
        code="TR", name_cn="土耳其", name_en="Türkiye",
        currency="TRY", currency_symbol="₺",
        market_domains=[
            "consumer.huawei.com/tr",
            "hepsiburada.com",
            "trendyol.com",
        ],
        infer_keywords=(
            "turkey", "türkiye", "turkish", "istanbul", "ankara", "izmir", "bursa",
            "土耳其", "伊斯坦布尔", "安卡拉", "伊兹密尔", "布尔萨",
            "DonanımHaber", "Donanim", "Technopat", "Ekşi", "Eksi",
            "hepsiburada", "trendyol",
        ),
    ),
    "RU": CountryMarket(
        code="RU", name_cn="俄罗斯", name_en="Russia",
        currency="RUB", currency_symbol="₽",
        market_domains=[
            "consumer.huawei.com/ru",
            "mvideo.ru",
            "dns-shop.ru",
        ],
        infer_keywords=(
            "russia", "russian", "moscow", "saint petersburg", "st petersburg",
            "novosibirsk",
            "俄罗斯", "莫斯科", "圣彼得堡", "新西伯利亚",
            "Pikabu", "4PDA", "DTF", "灰色进口",
            "mvideo", "dns-shop",
        ),
    ),
    "MX": CountryMarket(
        code="MX", name_cn="墨西哥", name_en="Mexico",
        currency="MXN", currency_symbol="MX$",
        market_domains=[
            "consumer.huawei.com/mx",
            "mercadolibre.com.mx",
            "amazon.com.mx",
        ],
        infer_keywords=(
            "mexico", "mexican", "ciudad de mexico", "mexico city",
            "guadalajara", "monterrey", "querétaro", "queretaro",
            "墨西哥", "墨西哥城", "瓜达拉哈拉", "蒙特雷", "克雷塔罗", "波兰科",
            "UNAM", "Tec de Monterrey",
            "mercadolibre", "amazon.com.mx",
        ),
    ),
    # ---------- 欧洲（V2-② 新增主力，11 国）----------
    "FR": CountryMarket(
        code="FR", name_cn="法国", name_en="France",
        currency="EUR", currency_symbol="€",
        market_domains=[
            "consumer.huawei.com/fr",
            "fnac.com",
            "amazon.fr",
        ],
        infer_keywords=(
            "france", "french", "paris", "lyon", "marseille", "toulouse",
            "法国", "巴黎", "里昂", "马赛", "图卢兹", "波尔多",
            "fnac", "amazon.fr", "Frandroid",
        ),
    ),
    "GB": CountryMarket(
        code="GB", name_cn="英国", name_en="United Kingdom",
        currency="GBP", currency_symbol="£",
        market_domains=[
            "consumer.huawei.com/uk",
            "amazon.co.uk",
            "currys.co.uk",
        ],
        infer_keywords=(
            "united kingdom", "britain", "british", "england", "london",
            "manchester", "birmingham", "edinburgh",
            "英国", "伦敦", "曼彻斯特", "伯明翰", "爱丁堡",
            "currys", "amazon.co.uk", "MoneySavingExpert",
        ),
    ),
    "DE": CountryMarket(
        code="DE", name_cn="德国", name_en="Germany",
        currency="EUR", currency_symbol="€",
        market_domains=[
            "consumer.huawei.com/de",
            "amazon.de",
            "mediamarkt.de",
        ],
        infer_keywords=(
            "germany", "german", "berlin", "munich", "münchen", "hamburg",
            "frankfurt", "cologne", "köln",
            "德国", "柏林", "慕尼黑", "汉堡", "法兰克福", "科隆",
            "mediamarkt", "amazon.de", "ComputerBase",
        ),
    ),
    "IT": CountryMarket(
        code="IT", name_cn="意大利", name_en="Italy",
        currency="EUR", currency_symbol="€",
        market_domains=[
            "consumer.huawei.com/it",
            "amazon.it",
            "mediaworld.it",
        ],
        infer_keywords=(
            "italy", "italian", "rome", "roma", "milan", "milano", "naples",
            "turin", "torino",
            "意大利", "罗马", "米兰", "那不勒斯", "都灵",
            "mediaworld", "amazon.it",
        ),
    ),
    "ES": CountryMarket(
        code="ES", name_cn="西班牙", name_en="Spain",
        currency="EUR", currency_symbol="€",
        market_domains=[
            "consumer.huawei.com/es",
            "amazon.es",
            "elcorteingles.es",
        ],
        infer_keywords=(
            "spain", "spanish", "madrid", "barcelona", "valencia", "sevilla",
            "西班牙", "马德里", "巴塞罗那", "瓦伦西亚", "塞维利亚",
            "elcorteingles", "amazon.es", "pccomponentes",
        ),
    ),
    "PL": CountryMarket(
        code="PL", name_cn="波兰", name_en="Poland",
        currency="PLN", currency_symbol="zł",
        market_domains=[
            "consumer.huawei.com/pl",
            "allegro.pl",
            "mediaexpert.pl",
        ],
        infer_keywords=(
            "poland", "polish", "warsaw", "warszawa", "krakow", "kraków",
            "wroclaw", "gdansk",
            "波兰", "华沙", "克拉科夫", "弗罗茨瓦夫", "格但斯克",
            "allegro", "mediaexpert", "zł",
        ),
    ),
    "RO": CountryMarket(
        code="RO", name_cn="罗马尼亚", name_en="Romania",
        currency="RON", currency_symbol="lei",
        market_domains=[
            "consumer.huawei.com/ro",
            "emag.ro",
            "altex.ro",
        ],
        infer_keywords=(
            "romania", "romanian", "bucharest", "bucurești", "cluj", "timisoara",
            "罗马尼亚", "布加勒斯特", "克卢日", "蒂米什瓦拉",
            "emag", "altex", "RON",
        ),
    ),
    "NL": CountryMarket(
        code="NL", name_cn="荷兰", name_en="Netherlands",
        currency="EUR", currency_symbol="€",
        market_domains=[
            "consumer.huawei.com/nl",
            "bol.com",
            "coolblue.nl",
        ],
        infer_keywords=(
            "netherlands", "dutch", "amsterdam", "rotterdam", "the hague",
            "den haag", "utrecht", "eindhoven",
            "荷兰", "阿姆斯特丹", "鹿特丹", "海牙", "乌得勒支", "埃因霍温",
            "bol.com", "coolblue", "tweakers",
        ),
    ),
    "CZ": CountryMarket(
        code="CZ", name_cn="捷克", name_en="Czechia",
        currency="CZK", currency_symbol="Kč",
        market_domains=[
            "consumer.huawei.com/cz",
            "alza.cz",
            "mall.cz",
        ],
        infer_keywords=(
            "czech", "czechia", "prague", "praha", "brno", "ostrava",
            "捷克", "布拉格", "布尔诺", "俄斯特拉发",
            "alza", "mall.cz", "Kč",
        ),
    ),
    "HU": CountryMarket(
        code="HU", name_cn="匈牙利", name_en="Hungary",
        currency="HUF", currency_symbol="Ft",
        market_domains=[
            "consumer.huawei.com/hu",
            "emag.hu",
            "alza.hu",
        ],
        infer_keywords=(
            "hungary", "hungarian", "budapest", "debrecen", "szeged",
            "匈牙利", "布达佩斯", "德布勒森", "塞格德",
            "emag.hu", "alza.hu", "Ft",
        ),
    ),
    "AT": CountryMarket(
        code="AT", name_cn="奥地利", name_en="Austria",
        currency="EUR", currency_symbol="€",
        market_domains=[
            "consumer.huawei.com/at",
            "amazon.at",
            "mediamarkt.at",
        ],
        infer_keywords=(
            "austria", "austrian", "vienna", "wien", "graz", "salzburg",
            "linz", "innsbruck",
            "奥地利", "维也纳", "格拉茨", "萨尔茨堡", "林茨", "因斯布鲁克",
            "geizhals", "mediamarkt.at",
        ),
    ),
    # ---------- 亚太新增（V2-②，3 国；VN 官网建设中→退授权零售）----------
    "VN": CountryMarket(
        code="VN", name_cn="越南", name_en="Vietnam",
        currency="VND", currency_symbol="₫",
        market_domains=[
            "thegioididong.com",
            "fptshop.com.vn",
            "tiki.vn",
        ],
        infer_keywords=(
            "vietnam", "vietnamese", "hanoi", "ho chi minh", "saigon", "da nang",
            "越南", "河内", "胡志明", "西贡", "岘港",
            "thegioididong", "fptshop", "tinhte",
        ),
    ),
    "JP": CountryMarket(
        code="JP", name_cn="日本", name_en="Japan",
        currency="JPY", currency_symbol="¥",
        market_domains=[
            "consumer.huawei.com/jp",
            "kakaku.com",
            "amazon.co.jp",
        ],
        infer_keywords=(
            "japan", "japanese", "tokyo", "osaka", "yokohama", "nagoya", "kyoto",
            "日本", "东京", "大阪", "横滨", "名古屋", "京都",
            "kakaku", "amazon.co.jp", "価格.com",
        ),
    ),
    "HK": CountryMarket(
        code="HK", name_cn="香港", name_en="Hong Kong",
        currency="HKD", currency_symbol="HK$",
        market_domains=[
            "consumer.huawei.com/hk",
            "price.com.hk",
            "fortress.com.hk",
        ],
        infer_keywords=(
            "hong kong", "hongkong", "kowloon", "mong kok", "causeway bay",
            "香港", "九龙", "旺角", "铜锣湾", "尖沙咀", "中环",
            "price.com.hk", "fortress", "丰泽",
        ),
    ),
    # ---------- 拉美新增（V2-②，4 国；BR 无官网商城→退电商）----------
    "PE": CountryMarket(
        code="PE", name_cn="秘鲁", name_en="Peru",
        currency="PEN", currency_symbol="S/",
        market_domains=[
            "consumer.huawei.com/pe",
            "falabella.com.pe",
            "mercadolibre.com.pe",
        ],
        infer_keywords=(
            "peru", "perú", "peruvian", "lima", "arequipa", "trujillo", "cusco",
            "秘鲁", "利马", "阿雷基帕", "特鲁希略", "库斯科",
            "falabella", "mercadolibre", "PEN",
        ),
    ),
    "CL": CountryMarket(
        code="CL", name_cn="智利", name_en="Chile",
        currency="CLP", currency_symbol="CLP$",
        market_domains=[
            "consumer.huawei.com/cl",
            "falabella.com",
            "mercadolibre.cl",
        ],
        infer_keywords=(
            "chile", "chilean", "santiago", "valparaiso", "valparaíso",
            "concepción", "concepcion",
            "智利", "圣地亚哥", "瓦尔帕莱索", "康塞普西翁",
            "falabella.com", "mercadolibre.cl", "CLP",
        ),
    ),
    "CO": CountryMarket(
        code="CO", name_cn="哥伦比亚", name_en="Colombia",
        currency="COP", currency_symbol="COL$",
        market_domains=[
            "consumer.huawei.com/co",
            "mercadolibre.com.co",
            "falabella.com.co",
        ],
        infer_keywords=(
            "colombia", "colombian", "bogota", "bogotá", "medellin", "medellín",
            "cali", "barranquilla",
            "哥伦比亚", "波哥大", "麦德林", "卡利", "巴兰基亚",
            "mercadolibre.com.co", "falabella.com.co", "COP",
        ),
    ),
    "BR": CountryMarket(
        code="BR", name_cn="巴西", name_en="Brazil",
        currency="BRL", currency_symbol="R$",
        market_domains=[
            "mercadolivre.com.br",
            "amazon.com.br",
            "magazineluiza.com.br",
        ],
        infer_keywords=(
            "brazil", "brasil", "brazilian", "sao paulo", "são paulo",
            "rio de janeiro", "brasilia", "brasília",
            "巴西", "圣保罗", "里约热内卢", "巴西利亚",
            "mercadolivre", "magazineluiza", "BRL",
        ),
    ),
    # ---------- 中东非新增（V2-②，3 国；QA/KW 无官网商城→退授权零售）----------
    "EG": CountryMarket(
        code="EG", name_cn="埃及", name_en="Egypt",
        currency="EGP", currency_symbol="E£",
        market_domains=[
            "consumer.huawei.com/eg",
            "jumia.com.eg",
            "amazon.eg",
        ],
        infer_keywords=(
            "egypt", "egyptian", "cairo", "alexandria", "giza",
            "埃及", "开罗", "亚历山大", "吉萨",
            "jumia", "amazon.eg", "EGP",
        ),
    ),
    "QA": CountryMarket(
        code="QA", name_cn="卡塔尔", name_en="Qatar",
        currency="QAR", currency_symbol="QR",
        market_domains=[
            "noon.com",
            "axiomtelecom.com",
            "carrefourqatar.com",
        ],
        infer_keywords=(
            "qatar", "qatari", "doha", "al rayyan",
            "卡塔尔", "多哈", "赖扬",
            "noon.com", "axiomtelecom", "QAR",
        ),
    ),
    "KW": CountryMarket(
        code="KW", name_cn="科威特", name_en="Kuwait",
        currency="KWD", currency_symbol="KD",
        market_domains=[
            "xcite.com",
            "blink.com.kw",
            "best.com.kw",
        ],
        infer_keywords=(
            "kuwait", "kuwaiti", "kuwait city", "hawalli", "salmiya",
            "科威特", "科威特城", "哈瓦利", "萨尔米耶",
            "xcite", "blink.com.kw", "KWD",
        ),
    ),
    "CN": CountryMarket(
        code="CN", name_cn="中国大陆", name_en="China",
        currency="CNY", currency_symbol="￥",
        market_domains=[
            "consumer.huawei.com/cn",
            "huawei.com.cn",
            "jd.com",
            "tmall.com",
        ],
        infer_keywords=(
            # 注意：不要用 "中国" / "china" 这种过宽词
            # —— 别国 persona 经常说"对比中国友商""中国品牌友好型"导致误判。
            "中国大陆", "北京", "上海", "广州", "深圳", "杭州", "成都", "大理",
            "B站", "小红书", "微博", "知乎", "京东", "天猫", "淘宝", "linmu",
            "上海跨国", "外企项目经理", "B站数码", "微博科技",
            "huawei.com.cn", "vmall", "jd.com", "tmall.com",
        ),
    ),
}


# 全球兜底（user q3=default_global）：当 persona 没设 country_code 也推不出时使用
DEFAULT_GLOBAL_MARKET = CountryMarket(
    code="GLOBAL",
    name_cn="全球",
    name_en="Global",
    currency="USD",
    currency_symbol="$",
    market_domains=[
        "consumer.huawei.com",          # 国际站
        "consumer.huawei.com/en",
    ],
    infer_keywords=(),
)


# ============================================================
# 推断器
# ============================================================


def get_market(country_code: Optional[str]) -> CountryMarket:
    """显式 country_code 查表；查不到返回 DEFAULT_GLOBAL_MARKET。"""
    if not country_code:
        return DEFAULT_GLOBAL_MARKET
    return COUNTRY_REGISTRY.get(country_code.upper(), DEFAULT_GLOBAL_MARKET)


def infer_market_from_persona(
    *,
    locale: Optional[str] = None,
    source: Optional[str] = None,
    prompt_text: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> CountryMarket:
    """根据 persona 的弱信号（source + prompt_text + tags）反推国家。

    打分规则（每关键词同位置最多累加 1 次）：
      - **source** 命中 → +5 分（最强信号：Pikabu/Technopat/Lowyat 这种社区平台名几乎是国家身份证）
      - **tags** 命中 → +2 分
      - **prompt_text** 命中 → +1 分（最弱：prompt 里很容易蹦出"对比中国友商"这种无关字眼）

    **不靠 locale** —— 项目里 locale 全是语言码（zh-CN = "用中文写"），并不代表客户国家。

    无任何命中返回 DEFAULT_GLOBAL_MARKET。本函数完全失败安全。

    ``locale`` 参数保留只为向后兼容，不参与打分。
    """
    _ = locale  # 显式忽略，避免 unused 警告
    try:
        scores: dict[str, int] = {code: 0 for code in COUNTRY_REGISTRY}
        text_src = (source or "").lower()
        text_pt = (prompt_text or "").lower()
        tags_lc = [str(t).lower() for t in (tags or [])]

        for code, mkt in COUNTRY_REGISTRY.items():
            for kw in mkt.infer_keywords:
                kw_lc = kw.lower().strip()
                if not kw_lc:
                    continue
                if kw_lc in text_src:
                    scores[code] += 5
                if kw_lc in text_pt:
                    scores[code] += 1
                for t in tags_lc:
                    if kw_lc in t:
                        scores[code] += 2
                        break

        best_code, best_score = max(scores.items(), key=lambda x: x[1])
        if best_score <= 0:
            return DEFAULT_GLOBAL_MARKET
        return COUNTRY_REGISTRY[best_code]
    except Exception as exc:  # noqa: BLE001
        logger.warning("infer_market_from_persona 失败，使用全球兜底：%s", exc)
        return DEFAULT_GLOBAL_MARKET


def all_country_options() -> list[dict[str, str]]:
    """UI 下拉框用的国家清单：[{code, label}, ...]。"""
    return [
        {"code": m.code, "label": f"{m.name_cn} ({m.code})", "currency": m.currency}
        for m in COUNTRY_REGISTRY.values()
    ]


def render_client_market_block(
    *,
    country_code: Optional[str],
    country_name: Optional[str],
    currency: Optional[str],
    market_domains: Optional[list[str]],
) -> str:
    """渲染成可直接注入 sales_prompt 的"客户所在市场"段落。

    优先用 persona 已存的字段（即便 country_code 是 GLOBAL）；4 个字段都空时走全球兜底。
    """
    has_any = any([country_code, currency, market_domains])
    if not has_any:
        mkt = DEFAULT_GLOBAL_MARKET
        country_code = mkt.code
        country_name = mkt.name_cn
        currency = mkt.currency
        market_domains = list(mkt.market_domains)
    else:
        # 已有 country_code 就把 currency / domains 用 registry 补齐缺失项
        mkt = get_market(country_code)
        if not currency:
            currency = mkt.currency
        if not country_name:
            country_name = mkt.name_cn
        if not market_domains:
            market_domains = list(mkt.market_domains)

    sym = COUNTRY_REGISTRY.get((country_code or "").upper(), DEFAULT_GLOBAL_MARKET).currency_symbol
    domains_str = "\n".join(f"  · {d}" for d in (market_domains or [])) or "  · （未配置）"
    return (
        f"客户所在国家 / 地区：**{country_name}** ({country_code})\n"
        f"该国家通用货币：**{currency}**（符号 **{sym}**）—— 你所有报价 / 估价 / 比价必须用这个货币\n"
        f"该市场可信信源（web_search 工具被锁定只查这些域名）：\n"
        f"{domains_str}"
    )
