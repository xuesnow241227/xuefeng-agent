#!/usr/bin/env python3
"""
高考志愿顾问 Agent — 模型无关、支持实时搜索、结构化槽位采集。
Usage:
  python agent.py                    # 交互式对话
  python agent.py --model qwen-plus # 指定模型
  python agent.py --no-search        # 禁用搜索
"""

import os, sys, json, re, urllib.request, urllib.parse, urllib.error
from openai import OpenAI

# 高考数据模块
try:
    from gaokao_data import query_admission, format_admission_info
    HAS_DATA_MODULE = True
except ImportError:
    HAS_DATA_MODULE = False

def read_clipboard():
    """读取 Windows 剪贴板文本。"""
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        if win32clipboard.IsClipboardFormatAvailable(13):  # CF_UNICODETEXT
            data = win32clipboard.GetClipboardData(13)
            win32clipboard.CloseClipboard()
            return data
        win32clipboard.CloseClipboard()
    except:
        pass
    return None

# ── 加载 .env 文件 ──────────────────────────────────
def load_dotenv(path):
    """简单的 .env 加载器，不依赖第三方库。"""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    key, val = key.strip(), val.strip()
                    if key not in os.environ:
                        os.environ[key] = val

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))

# ── 常见模型预设 ────────────────────────────────────
# 用户只需设置 LLM_PROVIDER，系统自动填充 base_url 和 model
PRESETS = {
    "deepseek":  {"base_url": "https://api.deepseek.com",    "model": "deepseek-chat"},
    "qwen":      {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "glm":       {"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4"},
    "moonshot":  {"base_url": "https://api.moonshot.cn/v1",   "model": "moonshot-v1-8k"},
    "openai":    {"base_url": "https://api.openai.com/v1",    "model": "gpt-4o"},
    "ollama":    {"base_url": "http://localhost:11434/v1",    "model": "qwen2.5:7b"},
}

def resolve_config():
    """解析配置：支持 LLM_PROVIDER 快捷切换 或 手工指定三项。"""
    provider = os.getenv("LLM_PROVIDER", "").lower()
    if provider in PRESETS:
        preset = PRESETS[provider]
        return {
            "base_url": os.getenv("LLM_BASE_URL", preset["base_url"]),
            "api_key": os.getenv("LLM_API_KEY", ""),
            "model": os.getenv("LLM_MODEL", preset["model"]),
            "max_tokens": None,  # 不限制回复长度，让模型自由发挥
            "temperature": 0.7,
            "enable_search": True,
        }
    return {
        "base_url": os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
        "api_key": os.getenv("LLM_API_KEY", ""),
        "model": os.getenv("LLM_MODEL", "deepseek-chat"),
        "max_tokens": None,  # 不限制回复长度，让模型自由发挥
        "temperature": 0.7,
        "enable_search": True,
    }

CONFIG = resolve_config()
SEARCH_ENGINE = "https://www.baidu.com/s?wd="

# ── 加载知识库 ──────────────────────────────────────
KNOWLEDGE_BASE_PATH = os.path.join(HERE, "knowledge_base.md")
SYSTEM_PROMPT_PATH = os.path.join(HERE, "system_prompt.md")

def load_file(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""

# ── 槽位管理器 ───────────────────────────────────────
SLOTS = {
    "province":     {"label": "省份", "filled": False, "value": ""},
    "score_rank":   {"label": "分数/位次", "filled": False, "value": ""},
    "subject":      {"label": "选科", "filled": False, "value": ""},
    "interest":     {"label": "专业兴趣/厌恶", "filled": False, "value": ""},
    "region":       {"label": "地域偏好", "filled": False, "value": ""},
    "family":       {"label": "家庭资源", "filled": False, "value": ""},
    "goal":         {"label": "核心诉求", "filled": False, "value": ""},
}

def filled_slots():
    return {k: v for k, v in SLOTS.items() if v["filled"]}

def missing_slots():
    return [k for k, v in SLOTS.items() if not v["filled"]]

def slots_summary():
    lines = []
    for k, v in SLOTS.items():
        status = "[OK]" if v["filled"] else "[ ]"
        lines.append(f"  {status} {v['label']}: {v['value'] if v['filled'] else '(未填)'}")
    return "\n".join(lines)

def extract_slots_from_message(msg):
    """从用户消息中自动提取槽位信息。"""
    updated = []
    msg_lower = msg.lower()

    # 省份检测
    provinces = [
        "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林",
        "黑龙江", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
        "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西",
        "甘肃", "青海", "台湾", "内蒙古", "广西", "西藏", "宁夏", "新疆",
    ]
    for p in provinces:
        if p in msg and not SLOTS["province"]["filled"]:
            SLOTS["province"]["value"] = p
            SLOTS["province"]["filled"] = True
            updated.append(f"省份→{p}")

    # 分数/位次检测
    score_match = re.search(r'(\d{3})\s*分', msg)
    rank_match = re.search(r'(\d{4,7})\s*[位名]', msg)
    if score_match and not SLOTS["score_rank"]["filled"]:
        SLOTS["score_rank"]["value"] = score_match.group(1) + "分"
        SLOTS["score_rank"]["filled"] = True
        updated.append(f"分数→{score_match.group(1)}分")
    if rank_match and not SLOTS["score_rank"]["filled"]:
        SLOTS["score_rank"]["value"] = "位次" + rank_match.group(1)
        SLOTS["score_rank"]["filled"] = True
        updated.append(f"位次→{rank_match.group(1)}")
    if rank_match and SLOTS["score_rank"]["filled"]:
        SLOTS["score_rank"]["value"] += " / 位次" + rank_match.group(1)

    # 选科检测
    for subj in ["物理", "历史", "物化生", "物化地", "物化政", "物生政",
                  "史政地", "史政生", "史地生", "理科", "文科"]:
        if subj in msg and not SLOTS["subject"]["filled"]:
            SLOTS["subject"]["value"] = subj
            SLOTS["subject"]["filled"] = True
            updated.append(f"选科→{subj}")
            break

    # 地域检测
    for r in ["省内", "本省", "离家近", "北上广", "江浙沪", "北京", "上海",
               "深圳", "广州", "杭州", "成都", "武汉", "南京", "西安"]:
        if r in msg and not SLOTS["region"]["filled"]:
            SLOTS["region"]["value"] = r
            SLOTS["region"]["filled"] = True
            updated.append(f"地域→{r}")
            break

    # 家庭资源检测
    for fw in ["电力", "电网", "铁路", "医生", "教师", "老师", "做生意",
                "公务员", "烟草", "石油", "普通家庭", "没资源"]:
        if fw in msg and not SLOTS["family"]["filled"]:
            SLOTS["family"]["value"] = fw
            SLOTS["family"]["filled"] = True
            updated.append(f"家庭→{fw}")
            break

    # 诉求检测
    for g in ["就业", "考公", "考研", "稳定", "高薪", "赚钱", "深造", "出国"]:
        if g in msg and not SLOTS["goal"]["filled"]:
            SLOTS["goal"]["value"] = g
            SLOTS["goal"]["filled"] = True
            updated.append(f"诉求→{g}")
            break

    return updated

def is_consultation_intent(msg):
    """判断用户是否有志愿咨询意图。"""
    keywords = [
        "高考", "志愿", "选专业", "报学校", "报志愿", "填志愿", "选科",
        "分科", "考研", "选学校", "大学", "专业", "就业", "考公",
        "能报", "能上", "推荐", "建议", "帮忙看", "帮我选",
    ]
    return any(kw in msg for kw in keywords)

# ── 搜索功能 ─────────────────────────────────────────
def web_search(query, max_results=3):
    """搜索并获取网页内容。先用百度搜索找URL，再抓取页面文字。"""
    results = []
    try:
        # Step 1: 百度搜索获取结果链接
        url = SEARCH_ENGINE + urllib.parse.quote(query)
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Step 2: 提取搜索结果URL（尝试多种匹配模式）
        urls = re.findall(r'href="(https?://[^"]+)"', html)
        # 过滤掉百度自己的链接，保留真实网站
        valid_urls = [u for u in urls if 'baidu.com' not in u and len(u) > 30][:max_results]

        # Step 3: 抓取每个结果页面的文字内容
        for target_url in valid_urls:
            try:
                page_req = urllib.request.Request(target_url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                })
                with urllib.request.urlopen(page_req, timeout=8) as page_resp:
                    page_html = page_resp.read().decode("utf-8", errors="ignore")
                # 去掉所有标签，提取可见文字
                clean = re.sub(r'<script[^>]*>.*?</script>', '', page_html, flags=re.DOTALL)
                clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL)
                clean = re.sub(r'<[^>]+>', ' ', clean)
                clean = re.sub(r'\s+', ' ', clean).strip()
                # 取有效内容（100-500字）
                if len(clean) > 100:
                    results.append(clean[:500] + "...")
            except:
                continue

        if not results:
            # Step 4: 降级——只取百度摘要
            snippets = re.findall(r'<span class="content-right_[^"]*">(.*?)</span>', html)
            for s in snippets[:max_results]:
                clean = re.sub(r'<[^>]+>', '', s).strip()
                if len(clean) > 20:
                    results.append(clean)

        return results if results else ["(搜索无结果，建议手动查询官方渠道)"]
    except Exception as e:
        return [f"(搜索暂时不可用: {e})"]

def should_search(msg):
    """判断是否需要联网搜索——更积极触发。"""
    triggers = [
        "今年", "最新", "2026", "2025", "最近", "现在",
        "分数线", "录取分", "投档线", "招生计划", "录取",
        "政策", "变化", "改革", "新规",
        "就业率", "就业前景", "薪资", "月薪", "年薪",
        "排名", "第几名", "怎么样", "好不好",
        "能上", "能报", "能进", "稳不稳", "冲不冲",
        "多少分", "什么专业", "一本", "二本", "985", "211",
        "王牌专业", "优势", "缺点", "劣势", "值得", "推荐吗",
    ]
    return any(t in msg for t in triggers)

# ── LLM 对话 ─────────────────────────────────────────
def cleanup_format(text):
    """去掉 AI 模型可能会漏的 Markdown 格式，确保输出像真人聊天。"""
    if not text:
        return text
    # 去掉 **粗体**
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    # 去掉 ### 标题
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    # 去掉行首 - 列表标记
    text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.MULTILINE)
    # 去掉行首数字编号 1. 2. 等
    text = re.sub(r'^\s*\d+[\.\、]\s*', '', text, flags=re.MULTILINE)
    return text.strip()

class GaokaoAdvisor:
    def __init__(self):
        self.client = OpenAI(base_url=CONFIG["base_url"], api_key=CONFIG["api_key"])
        self.knowledge_base = load_file(KNOWLEDGE_BASE_PATH)
        self.system_prompt = load_file(SYSTEM_PROMPT_PATH)
        self.conversation = []

    def _build_system_message(self):
        """构建系统消息，包含 system prompt + 知识库摘要 + 当前槽位状态。"""
        # 加载完整知识库，不做截断
        kb = self.knowledge_base if self.knowledge_base else ""
        kb_summary = kb  # 全量加载，不限制
        slots_status = slots_summary()
        search_note = ""
        if CONFIG["enable_search"]:
            search_note = "\n\n【联网搜索已启用。遇到最新政策/分数线/就业数据等问题时，请在回答中说明需要搜索最新信息，或使用搜索工具查询。】"

        full_system = f"""{self.system_prompt}

{search_note}

【知识库参考】
{kb_summary}

【当前用户信息采集状态】
{slots_status}

请在回答时：
1. 如果用户信息不全，追问缺失的槽位（用自然的方式，不要像填表）。
2. 如果信息已经足够（至少省份+分数/位次+核心诉求），给出冲稳保推荐。
3. 遇到需要最新数据时，提示用户"建议查XX官方渠道"，或主动搜索。
4. 保持直爽、接地气的风格。"""
        return full_system

    def chat(self, user_msg):
        """处理一轮对话。返回 assistant 的回复。"""
        # 检查意图
        if is_consultation_intent(user_msg):
            # 提取槽位
            updates = extract_slots_from_message(user_msg)
        else:
            updates = []

        # 构建消息
        system_msg = self._build_system_message()
        messages = [{"role": "system", "content": system_msg}]
        # 添加历史（最近10轮=20条消息）
        for h in self.conversation[-20:]:
            messages.append(h)
        messages.append({"role": "user", "content": user_msg})

        # 如果有槽位更新，追加提示
        if updates:
            hint = f"(系统自动识别到: {', '.join(updates)}。请在回复中确认并追问缺失信息。)"
            messages.append({"role": "system", "content": hint})

        # 搜索（更积极 + 真实数据）
        search_results = None
        if CONFIG["enable_search"] and should_search(user_msg):
            # 尝试用数据模块搜真实录取数据
            school_match = re.findall(r'[一-鿿]{2,6}(?:大学|学院)', user_msg)
            prov_match = re.findall(r'(北京|天津|上海|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|广西|海南|四川|贵州|云南|陕西|甘肃|青海|台湾|内蒙古|西藏|宁夏|新疆)', user_msg)

            if school_match and prov_match and HAS_DATA_MODULE:
                try:
                    raw = query_admission(school_match[0], prov_match[0])
                    admission_text = format_admission_info(raw)
                    if admission_text and "暂无" not in admission_text:
                        search_hint = f"【真实录取数据搜索】\n{admission_text}"
                        messages.append({"role": "system", "content": search_hint})
                        search_results = "data_module_used"
                except:
                    pass

            # 降级：用普通搜索
            if not search_results:
                search_query = user_msg[:100]
                search_results = web_search(search_query)
                if search_results:
                    search_hint = f"【搜索结果】\n" + "\n".join(
                        f"· {r}" for r in search_results[:3]
                    )
                    messages.append({"role": "system", "content": search_hint})

        # 调用 LLM
        try:
            kwargs = dict(
                model=CONFIG["model"],
                messages=messages,
                temperature=CONFIG["temperature"],
            )
            if CONFIG["max_tokens"] is not None:
                kwargs["max_tokens"] = CONFIG["max_tokens"]
            resp = self.client.chat.completions.create(**kwargs)
            reply = resp.choices[0].message.content
        except Exception as e:
            reply = f"出错了：{e}\n请检查 API 配置（base_url, api_key, model 是否正确）。"

        # 清理格式：去掉模型不听 prompt 时残留的 markdown
        reply = cleanup_format(reply)

        # 保存对话历史
        self.conversation.append({"role": "user", "content": user_msg})
        self.conversation.append({"role": "assistant", "content": reply})

        return reply

    def reset(self):
        """重置对话和槽位。"""
        self.conversation = []
        for k in SLOTS:
            SLOTS[k]["filled"] = False
            SLOTS[k]["value"] = ""

# ── CLI 界面 ─────────────────────────────────────────
def test_connection():
    """测试 API 连接是否正常。"""
    try:
        client = OpenAI(base_url=CONFIG["base_url"], api_key=CONFIG["api_key"])
        resp = client.chat.completions.create(
            model=CONFIG["model"],
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5,
        )
        return True, resp.choices[0].message.content
    except Exception as e:
        return False, str(e)

def main():
    import textwrap

    print("=" * 60)
    print("  高考志愿顾问 Agent")
    print(f"  模型: {CONFIG['model']}")
    print(f"  搜索: {'开' if CONFIG['enable_search'] else '关'}")
    print("=" * 60)

    if not CONFIG["api_key"]:
        print("\n❌ 未检测到 API Key！")
        print("   请复制 .env.example 为 .env 并填入你的 API Key。")
        print("   或者设置环境变量 LLM_API_KEY=你的key")
        print()
        print("   快速开始（任选一种）：")
        print("   · DeepSeek:  set LLM_PROVIDER=deepseek && set LLM_API_KEY=sk-xxx")
        print("   · 通义千问:  set LLM_PROVIDER=qwen && set LLM_API_KEY=sk-xxx")
        print("   · 智谱GLM:   set LLM_PROVIDER=glm && set LLM_API_KEY=xxx")
        input("\n   按回车退出...")
        return

    # 测试连接
    print("  正在测试 API 连接...", end=" ", flush=True)
    ok, msg = test_connection()
    if ok:
        print("[OK] 连接成功")
    else:
        print(f"[X] 连接失败: {msg[:120]}")
        print("\n   请检查 .env 中的 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 是否正确。")
        print("   常见问题：")
        print("   · API Key 是否有效？")
        print("   · Base URL 是否需要加 /v1？")
        print("   · 模型名是否与 API 提供商匹配？")
        input("\n   按回车退出...")
        return

    print("=" * 60)
    print("  命令: /paste 粘贴 | /slots 信息 | /reset 重置 | /quit 退出")
    print("  直接描述你的情况，我会帮你分析。")
    print("=" * 60)
    print()

    advisor = GaokaoAdvisor()

    while True:
        try:
            user_input = input("\n[You] 你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue

        if user_input == "/quit":
            print("再见！")
            break
        elif user_input == "/reset":
            advisor.reset()
            print("[OK] 已重置对话和信息采集")
            continue
        elif user_input == "/slots":
            print(slots_summary())
            continue
        elif user_input == "/paste":
            cb = read_clipboard()
            if cb and cb.strip():
                user_input = " ".join(cb.strip().split("\n"))
                print(f"📋 剪贴板已读取 ({len(user_input)}字)")
                print(f"📋 内容: {user_input[:100]}...")
            else:
                print("📋 剪贴板为空或无法读取")
                continue

        print("\n🤖 顾问: ", end="", flush=True)
        reply = advisor.chat(user_input)
        print(reply)

if __name__ == "__main__":
    main()
