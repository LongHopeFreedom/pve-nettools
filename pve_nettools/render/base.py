# [CHANGE] 2026-08-01 新增：render 層的版面元件與區段基底（待辦 #8 骨架）。
"""版面元件與區段基底。

## 為什麼區段要有基底類別

bash 版每個區段都是 `render_X` / `render_X_table` / `render_X_blocks` 三個函式，
兩種版面**各自去取值**。它自己的註解寫得很清楚（`_load_nic_health` 上方）：

> 抽出來是為了不讓表格版與區塊版各自取一次值——那正是舊版 show_*/report_* 兩套
> 實作會漂移的老問題。

也就是說 bash 版是靠**紀律**維持「兩版面同源」，一旦有人在表格版多加一個欄位而
忘了區塊版，不會有任何東西變紅。這裡改成**結構保證**：`render()` 呼叫一次
`build()`，把同一份資料分別餵給 `table()` 與 `blocks()`，兩版面**沒有辦法**看到
不同的值。

★ 這條性質是可測的（見 `TestSectionContract`：以計數 spy 斷言 `build()` 恰好一次），
  不是只寫在註解裡的期許。

## 為什麼不回傳字串而回傳行的清單

render 層一律回傳 `list[str]`，不做任何 I/O。理由是同一份輸出有三個去處——終端、
pager、報告檔（0600）——而且報告檔的內容 MUST 與終端一致。讓區段自己 print 就
無從在測試裡驗證它印了什麼，也不能把同一份內容交給兩個去處。
"""

# [CHANGE] 2026-08-01 上面兩句原本與同源保證共用同一個否定詞，於是它在同一份
#          docstring 裡出現三次。突變把同源那一處改掉時，斷言仍被另外兩處滿足而
#          **存活**——斷言的關鍵詞含否定語意還不夠，它還 MUST 能唯一定位到被守的
#          那一句。措辭因此分開，斷言也改成帶語境（見 test_T）。

from ..i18n import t
from ..width import Table, disp_width, hr, pad

__all__ = [
    "BLOCK_RULE_WIDTH",
    "DecoratedTable",
    "RenderContext",
    "Section",
    "blank",
    "block_title",
    "block_rule",
    "error",
    "header",
    "kv",
    "kv_coloured",
    "limited",
    "note",
    "section",
    "subsection",
    "success",
    "thin_hr",
]

# [CHANGE] 2026-08-02 選單 5／6／7 的區塊分隔線寬度。
#
# ★ 這個 80 是**逐字沿用 bash**（`hr 80`），刻意不改成由 ctx.width 推導。
#   base.py 的 docstring 批評過 bash 把表格門檻寫死成 131／134，但那是**版面
#   決策**（放不放得下這些欄），會隨 i18n 的表頭寬度改變而失效；這裡的 80 是
#   **裝飾性分隔線**，與欄寬無關，跟著終端寬度變動反而讓同一份報告在不同終端
#   長得不一樣。兩者不是同一件事，故結論相反。
BLOCK_RULE_WIDTH = 80

# bash 版 kv() 的鍵欄寬度。區塊版另有較窄的值，故此處只是預設而非唯一值。
KV_KEY_WIDTH = 16


class RenderContext(object):
    """一次輸出的共用環境：寬度與調色盤。

    ★ 寬度在這裡是**已經決定好的數值**，不是「去問終端」的函式。誰去問、問誰，
    由 theme.term_width() 負責；區段只管「我需要幾欄，你有沒有」。這讓每個區段的
    版面選擇都能在測試裡以固定寬度重現。
    """

    def __init__(self, width, palette):
        self.width = width
        self.palette = palette

    def fits(self, needed):
        """寬度夠不夠放下 needed 欄。"""
        return self.width >= needed

    def paint(self, text, colour):
        return self.palette.paint(text, colour)


def blank():
    return ""


def section(title, palette=None):
    """區段標題（粗體青色）＋一行空白，與 bash 版 section() 相同。"""
    text = title if palette is None else palette.paint(
        palette.paint(title, "cyan"), "bold")
    return [text, ""]


def subsection(title, palette=None):
    """次級標題（粗體），不帶空行。"""
    return [title if palette is None else palette.paint(title, "bold")]


# [CHANGE] 2026-08-03 新增：窄版區塊標題共用同一套粗體框線／青色名稱，避免九處
#          各自著色後漂移；無調色盤或停用顏色時維持既有字串逐位元不變。
def block_title(name, palette=None):
    """區塊標題：粗體框線包住青色名稱；關閉顏色時原樣回傳。"""
    plain = "── %s ──" % name
    if palette is None or not palette.enabled:
        return plain
    return "%s%s%s" % (
        palette.paint("── ", "bold"),
        palette.paint(str(name), "cyan"),
        palette.paint(" ──", "bold"),
    )


def kv(key, value, key_width=KV_KEY_WIDTH):
    """`鍵　　　：值` 一行。鍵補白到 key_width，值不補白。

    ★ 值**不補白**是刻意的：它在行末，補白只會留下看不見的尾隨空白（bash 版區塊
    版的註解特別標了「這是行末，不補白」）。
    """
    # [CHANGE] 2026-08-02 分隔符改走 i18n：原本硬編碼全形「：」，英文介面會變成
    #          半形語境裡混一個全形標點。en 用 ": " 保持同寬，欄寬計算不受影響。
    return "%s%s%s" % (pad(key, key_width), t("app.kv_sep"), value)


# [CHANGE] 2026-08-02 新增：鍵與值可各自著色的 kv（選單 5／6／7 要用）。
def kv_coloured(key, value, palette=None, key_colour=None, value_colour=None,
                key_width=KV_KEY_WIDTH):
    """與 kv() 同版面，但鍵與值可各自著色。

    ★ 著色 MUST 在**補白之後**才套用到文字本體，補白本身留在外面不著色。
      顏色碼的長度若被算進 pad()，整欄就會左移——`width.Table.render()` 的註解
      寫過同一件事，bash 特地寫 padc() 也是為此。這裡不能直接
      `pad(palette.paint(key), 16)`，那正是那個錯。
    """
    if key_colour is not None and palette is not None:
        padding = max(0, key_width - disp_width(key))
        rendered_key = palette.paint(key, key_colour) + " " * padding
    else:
        rendered_key = pad(key, key_width)

    rendered_value = value
    if value_colour is not None and palette is not None:
        rendered_value = palette.paint(value, value_colour)
    return "%s%s%s" % (rendered_key, t("app.kv_sep"), rendered_value)


def block_rule(width=BLOCK_RULE_WIDTH):
    """區塊分隔線，對應 bash 的 `hr 80`。"""
    return hr(width)


# [CHANGE] 2026-08-02 新增：bash print_limited() 的等價（選單 12 要用）。
def limited(lines, limit, unit, palette=None):
    """超過上限就截斷，並**明說**截掉多少。

    ★ 「明說」是這個函式存在的全部理由。bash 的註解寫得很直接：

        v02.000.000 用 `| head -50` 直接截斷，讀報告的人會以為那就是全部——
        盤查報告裡的靜默截斷等同給出錯誤結論。

      所以 MUST NOT 簡化成 `lines[:limit]`。這與本專案反覆踩到的「空集合被讀成
      完全合規」是同一族：**縮減過的輸出與完整的輸出長得一模一樣**。

    ★ `limit` 為 None 或非正數時不截斷。bash 那邊 LIST_LIMIT 恆為正整數（有
      `${LIST_LIMIT:-50}` 兜底），Python 這邊由 util.positive_int() 解析使用者
      輸入，解析不出來會是 None——此時「不截斷」比「用 0 截成空的」安全。
    """
    lines = list(lines)
    if not limit or limit <= 0 or len(lines) <= limit:
        return lines
    total = len(lines)
    tail = note(t("app.list_truncated", limit=limit, total=total,
                  hidden=total - limit, unit=unit), palette)
    return lines[:limit] + [tail]


def note(text, palette=None):
    """提示行（黃色）。"""
    return text if palette is None else palette.paint(text, "yellow")


# [CHANGE] 2026-08-03 新增：互動流程以語意選擇成功／錯誤樣式，避免呼叫端散落
#          red／green 字串；palette 未提供或停用時仍維持純文字。
def error(text, palette=None):
    """錯誤行（紅色）。"""
    return text if palette is None else palette.paint(text, "red")


def success(text, palette=None):
    """成功行（綠色）。"""
    return text if palette is None else palette.paint(text, "green")


def thin_hr(width):
    return hr(width, "-")


def header(title, host, timestamp, version=None, palette=None):
    """報告／畫面抬頭。

    ★ 主機名與時間**由呼叫端傳入**，這一層不去問系統。理由是報告檔要能重現：
    測試若不能固定時間戳，就只能斷言「有一行看起來像時間」，那等於沒有斷言。
    """
    # [CHANGE] 2026-08-02 兩個標籤原本是硬編碼中文，而 i18n 早就有 app.host／
    #          app.time 兩個 key——它們存在卻沒有任何呼叫端，這正是「i18n 有 key
    #          而程式沒用」的反向線索。英文介面在此之前會混入中文，而開發者用
    #          中文跑永遠不會發現（i18n.py 的 docstring 開宗明義就是這一條）。
    #          ★ 這是待辦 #10 委派時受託方指出的：它為了守 i18n 硬約束，本來已
    #          在 menu.py 自行組了一份抬頭；兩份抬頭會漂移，故改為修好這裡、
    #          讓 menu 回頭用它。
    first = title if version is None else "%s  v%s" % (title, version)
    if palette is not None:
        first = palette.paint(palette.paint(first, "cyan"), "bold")
    sep = t("app.kv_sep")
    return [first, "%s%s%s" % (t("app.host"), sep, host),
            "%s%s%s" % (t("app.time"), sep, timestamp), ""]


# [CHANGE] 2026-08-02 由 render/nic.py 的 _TrailingTable 移來，並加上 leading。
#
# ★ 為什麼移到 base：它是**版面元件**，而 nic.py 是一個區段。guest.py 與
#   netconf.py 早就得寫 `from .nic import _TrailingTable`——一個區段去 import
#   另一個區段的私有類別，是「這個東西放錯層」最直接的徵兆。
# ★ 為什麼加 leading 而不是另寫一個 _LeadingTable：兩個只差方向的類別必然漂移
#   （某一邊修了 render() 的著色順序、另一邊沒修，不會有東西變紅）。
class DecoratedTable(Table):
    """在表格前後附加固定行，不改動共用 Table 的契約。

    bash 有幾個區段會在表格前印 subsection 標題、在表格後印說明散文。那些行
    **不是表格的一部分**（不參與欄寬計算），但 MUST 與表格一起交付給 Section，
    否則 render() 的「表格版／區塊版擇一」就會把它們漏掉。
    """

    def __init__(self, headers, trailing=(), leading=(), min_widths=None, gap=2):
        Table.__init__(self, headers, min_widths=min_widths, gap=gap)
        self.leading = list(leading)
        self.trailing = list(trailing)

    def total_width(self):
        """★ 寬度判準只看表格本體，前後附加行不計入。

        附加行是散文，撐破了頂多換行，不該把整個區段推去走區塊版——而區塊版
        通常比表格版更難讀。
        """
        return Table.total_width(self)

    def render(self, colorizer=None):
        return self.leading + Table.render(self, colorizer) + self.trailing


class Section(object):
    """區段基底：取值一次，依寬度選版面。

    子類覆寫：
      build()             → 取值，回傳純資料（唯一碰 collect 層的地方）
      table(data, ctx)    → width.Table，或 None 表示此區段沒有表格版
      blocks(data, ctx)   → list[str]
      is_empty(data)      → 預設 `not data`
      empty_lines(data,ctx)→ 沒有資料時要印什麼
      colorizer(data,ctx) → 傳給 Table.render() 的著色函式，預設不著色
    """

    def build(self):
        raise NotImplementedError

    def table(self, data, ctx):
        raise NotImplementedError

    def blocks(self, data, ctx):
        raise NotImplementedError

    def colorizer(self, data, ctx):
        return None

    def is_empty(self, data):
        return not data

    # [CHANGE] 2026-08-01 加上 data 參數。原簽名 empty_lines(ctx) 收不到 build() 的
    #          結果，於是「查不到」與「查過但沒有」無法分辨——三個區段各自用 instance
    #          屬性把 data 從 build() 偷渡到 empty_lines()，還得覆寫 render()。
    #          可變狀態會在同一個 section 被 render 兩次時殘留，而那不會有東西變紅。
    def empty_lines(self, data, ctx):
        return []

    def render(self, ctx):
        """回傳這個區段的所有行。

        ★ `build()` 在此**恰好呼叫一次**，其結果同時是表格版與區塊版的唯一輸入。
        兩版面因此不可能看到不同的值——這是本模組存在的主要理由，MUST NOT 改成
        在 table()／blocks() 裡各自再取一次。

        ★ 表格版的門檻是 `Table.total_width()` **量出來的**，不是寫死的欄數。
        bash 版把它寫死成 131／134，於是中英文表頭寬度不同時那些數字就不對了；
        欄寬既然已由資料決定，門檻也必須跟著資料走。
        """
        data = self.build()
        if self.is_empty(data):
            return self.empty_lines(data, ctx)

        table = self.table(data, ctx)
        if table is not None and ctx.fits(table.total_width()):
            return table.render(self.colorizer(data, ctx))
        return self.blocks(data, ctx)
