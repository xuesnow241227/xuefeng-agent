#!/usr/bin/env python3
"""高考数据模块 — 搜索+抓取网页获取真实录取数据"""

import os, json, re, urllib.request, urllib.parse, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))

# 省份ID（备用）
PROVINCE_IDS = {
    "北京": 11, "天津": 12, "河北": 13, "山西": 14, "内蒙古": 15,
    "辽宁": 21, "吉林": 22, "黑龙江": 23,
    "上海": 31, "江苏": 32, "浙江": 33, "安徽": 34, "福建": 35, "江西": 36, "山东": 37,
    "河南": 41, "湖北": 42, "湖南": 43, "广东": 44, "广西": 45, "海南": 46,
    "重庆": 50, "四川": 51, "贵州": 52, "云南": 53, "西藏": 54,
    "陕西": 61, "甘肃": 62, "青海": 63, "宁夏": 64, "新疆": 65,
}

def search_realtime(query, max_results=5):
    """搜索并抓取网页内容，提取高考相关数据。
    返回: list of strings (每个是一段有效信息)
    """
    results = []
    try:
        # 优先搜索特定来源
        search_url = "https://www.baidu.com/s?wd=" + urllib.parse.quote(query)
        req = urllib.request.Request(search_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # 提取搜索结果URL
        urls = re.findall(r'href="(https?://[^"]+)"', html)
        valid_urls = [u for u in urls if 'baidu.com' not in u and len(u) > 40][:max_results]

        for target_url in valid_urls:
            try:
                page_req = urllib.request.Request(target_url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                })
                with urllib.request.urlopen(page_req, timeout=8) as page_resp:
                    page_html = page_resp.read().decode("utf-8", errors="ignore")

                # 提取可见文字
                clean = re.sub(r'<script[^>]*>.*?</script>', '', page_html, flags=re.DOTALL)
                clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL)
                clean = re.sub(r'<[^>]+>', ' ', clean)
                clean = re.sub(r'\s+', ' ', clean).strip()

                if len(clean) > 200:
                    # 尝试找到包含数字的段落（更可能是录取数据）
                    paras = clean.split('。')
                    data_paras = [p for p in paras if any(c.isdigit() for c in p) and len(p) > 20]
                    if data_paras:
                        results.append('。'.join(data_paras[:5])[:800])
                    else:
                        results.append(clean[:500])
            except:
                continue
    except Exception as e:
        return [f"(搜索出错: {e})"]

    return results if results else ["(未找到相关数据)"]

def query_admission(school, province, year=2024, major=None):
    """查询录取数据 — 自动搜索并整理结果"""
    queries = []
    if major:
        queries.append(f"{school} {major} {province} {year}年 录取分数线 位次")
    queries.append(f"{school} {province} {year} 录取分数线 最低分 最低位次")
    queries.append(f"{school} {year} 各省录取分数线汇总")

    all_results = []
    for q in queries[:2]:
        results = search_realtime(q)
        for r in results:
            if r not in all_results and len(r) > 50:
                all_results.append(r)
        if len(all_results) >= 2:
            break

    return all_results

def format_admission_info(results):
    """格式化录取数据为Agent可用的文本"""
    if not results:
        return "暂无该学校录取数据。建议访问各省教育考试院官网查询。"

    text = "以下为搜索到的参考数据（请以官方公布为准）：\n\n"
    for i, r in enumerate(results[:3]):
        # 清理数据，提取关键信息
        clean = r.replace('\n', ' ').replace('\r', ' ')[:600]
        text += f"{i+1}. {clean}\n\n"
    return text

if __name__ == "__main__":
    print("测试: 武汉理工大学 湖北 2024 录取数据")
    results = query_admission("武汉理工大学", "湖北", 2024)
    for i, r in enumerate(results):
        print(f"\n--- 结果{i+1} ---")
        print(r[:500])
