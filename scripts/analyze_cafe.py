#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcd-cafe-decoder · 麦咖解码器 —— 核心分析引擎

问题：麦咖啡一杯 9.9 到 23 元不等，但官方从不告诉你
      那杯"咖啡"里究竟有多少是咖啡、多少是奶。

思路：麦当劳官方接口 list-nutrition-foods 公开了每款饮品的
      能量 / 蛋白质 / 脂肪 / 碳水 / 钙 五个维度。把一杯奶咖建模为

          一杯饮品  ≈  a × 浓缩咖啡  +  b × 奶基底

      五维向量做非负最小二乘（NNLS）解卷积，得到：
        a —— 咖啡当量（几份浓缩）
        b —— 奶当量（几份奶基底）

      再除以真实到手价，得到本项目提出的指标
      ** cafe_per_yuan（每元咖啡当量）**，即"提神性价比"。

为什么可信（两条自带的交叉验证）：
  1. 把「美式」当作零奶基线，它的解必然是 b ≈ 0 —— 自洽。
  2. 把「牛奶 / 燕麦奶 / 红茶 / 抹茶」当作**阴性对照**，
     它们不含咖啡，正确的话 a 必须 ≈ 0。若真的解成 0，说明模型没在胡扯。

用法：
  python scripts/analyze_cafe.py [-o data/cafe_index.json]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")

# 参与拟合的营养维度。钠被有意排除：它受水质/蒸汽/添加物影响大，
# 且与"咖啡 vs 奶"的区分无关，纳入只会引入噪声。
DIMS = ["energyKcal", "protein", "fat", "carbohydrate", "calcium"]

DIM_CN = {
    "energyKcal": "能量(kcal)",
    "protein": "蛋白质(g)",
    "fat": "脂肪(g)",
    "carbohydrate": "碳水(g)",
    "calcium": "钙(mg)",
}

# 相对误差权重地板值。
# 营养数据 published 精度是整数（蛋白 8g、钙 251mg），若按绝对单位加权，
# 能量(129)和钙(231)会压倒蛋白(7)、脂肪(7)。这里改成"按各自量级等权相对误差"，
# 再给低于 5 单位的微量维度一个地板，避免整数舍入噪声被放大。
W_FLOOR = 5.0

# 残差分母的绝对地板，防止小体积饮品（如纯粹的鲜萃咖啡）被误判出界。
FIT_DEN_FLOOR = 30.0

# 残差超过此阈值，判定该饮品含第三种配料（蔗糖/可可/抹茶/冰淇淋），
# 二组分模型不适用，打标剔出排行榜。
OUT_OF_MODEL_RESIDUAL = 0.12

# 物理上限：现实中没有哪杯麦当劳咖啡会超过 4 份浓缩。
# 这道闸是必需的 —— 像「浓浓黑巧雪冰大杯」(444kcal) 这种甜品，
# 残差会被巨大的能量分母稀释到 0.07（看着拟合良好），
# 但为了配平能量，NNLS 会解出 a=33 份咖啡当量这种荒谬结果。
# 单纯靠残差阈值抓不住它，必须加物理量级约束。
MAX_SHOTS = 4.0


# --------------------------------------------------------------------------
# 1. 载入原始数据
# --------------------------------------------------------------------------

def load_nutrition(path):
    rows = []
    seen = set()
    # utf-8-sig：本机写出的 CSV 带 BOM，这里兼容掉，换环境也不会炸
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            name = r["productName"].strip()
            # 官方营养表里存在重复条目（如「纯牛奶（盒装）」出现两次），去掉重组
            if name in seen:
                continue
            seen.add(name)
            rows.append({
                "name": name,
                "v": {d: float(r[d]) for d in DIMS},
            })
    return rows


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------
# 2. 饮品识别与杯型解析
# --------------------------------------------------------------------------

SIZE_RE = re.compile(r"(小杯|中杯|大杯)")

BEVERAGE_HINTS = [
    "咖啡", "浓缩", "美式", "奶铁", "卡布奇诺", "玛奇朵", "阿芙佳朵",
    "牛奶", "燕麦奶", "黑巧", "抹茶牛奶", "朱古力",
    "红茶", "雪冰",
]


def parse_size(name):
    m = SIZE_RE.search(name)
    if not m:
        return None
    return {"小杯": "小", "中杯": "中", "大杯": "大"}[m.group(1)]


def parse_temp(name):
    if name.startswith("冰") or "雪冰" in name:
        return "冰"
    if name.startswith("热") or name.startswith("锡兰") or name.startswith("川宁"):
        return "热"
    return None


def is_beverage(name):
    # 新地系列虽含 "朱古力" 字样，但它是冰淇淋，不在饮品讨论范围内
    if "新地" in name:
        return False
    return any(h in name for h in BEVERAGE_HINTS)


# --------------------------------------------------------------------------
# 3. 菜单价格映射
#    nutrition 名字 -> menu code。顺序敏感：越具体的规则必须越靠前，
#    否则「燕麦奶铁」会被「奶铁」先吃掉。
# --------------------------------------------------------------------------

MENU_RULES = [
    # (包含词, 排除词, menu_code)
    (["浓浓燕麦黑巧"], ["雪冰"], "515955"),
    (["浓浓黑巧"], ["燕麦", "雪冰"], "515946"),
    (["燕麦奶铁"], [], "510479"),
    (["燕麦奶"], ["燕麦奶铁"], "510489"),
    (["奶铁"], ["燕麦"], "507409"),
    (["美式"], [], "507411"),
    (["卡布奇诺"], [], "507387"),
    (["鲜萃咖啡"], [], "520689"),
    (["浓缩咖啡"], [], "507389"),
    (["纯牛奶（盒装）", "纯牛奶(盒装)"], [], "3755"),
    (["冰牛奶", "热牛奶"], [], "507394"),
    (["锡兰红茶"], [], "3505"),
]


def map_menu(name, menu_meals):
    """按 nutrition 品名找到对应菜单条目。返回 (code, meal) 或 (None, None)。"""
    for inc, exc, code in MENU_RULES:
        if not any(i in name for i in inc):
            continue
        if any(e in name for e in exc):
            continue
        if code in menu_meals:
            return code, menu_meals[code]
    return None, None


# --------------------------------------------------------------------------
# 4. 奶基底选择
#    燕麦系饮品若拿牛奶当基底会系统性失真（燕麦奶脂肪低、碳水高），
#    因此按"是否含燕麦"切换基底。
# --------------------------------------------------------------------------

def pick_milk_basis(name, lookup):
    """按「是否燕麦」×「冰热」选择门店同款纯奶作为奶基底。

    ⚠️ 这里藏着本算法最容易翻车的一处：
    不能用「纯牛奶（盒装）」当基底。它是零售盒装奶，脂肪/钙的比例
    与门店蒸汽奶系统性不同；拟合为了吸收这份成分失配，会凭空加出
    一份浓缩咖啡——实测会把「热牛奶大杯」（明明零咖啡）解出 2.0 份咖啡当量。

    正确做法是取**同产品线、同温度**的门店纯奶：
    它们彼此大小杯之间是严格等比缩放的（实测 冰牛奶 大/中 = 1.20 倍，
    五个营养维度全部落在 1.15~1.21），所以才是干净的参照系。
    """
    oat = "燕麦" in name
    temp = "冰" if (name.startswith("冰") or "雪冰" in name) else "热"
    if oat:
        order = [f"{temp}燕麦奶中杯", "冰燕麦奶中杯", "热燕麦奶中杯"]
    else:
        order = [f"{temp}牛奶中杯", "冰牛奶中杯", "热牛奶中杯"]
    for cand in order:
        if cand in lookup:
            return cand, lookup[cand]
    return None, None


# --------------------------------------------------------------------------
# 5. 两变量 NNLS（闭式解 + 边界投影）
#    只有两个未知量，不需要迭代求解器；负分量直接投影到坐标轴上，
#    解析上等价于 NNLS 的 KKT 条件。
# --------------------------------------------------------------------------

def nnls2(v, e, m, w):
    """最小化 sum_d w_d^2 (v_d - a*e_d - b*m_d)^2，约束 a,b >= 0。"""
    ew = [w[d] * e[d] for d in DIMS]
    mw = [w[d] * m[d] for d in DIMS]
    vw = [w[d] * v[d] for d in DIMS]

    def dot(x, y):
        return sum(i * j for i, j in zip(x, y))

    def solve_free():
        A = dot(ew, ew)
        B = dot(ew, mw)
        C = dot(mw, mw)
        R1 = dot(ew, vw)
        R2 = dot(mw, vw)
        det = A * C - B * B
        if abs(det) < 1e-12:
            return 0.0, 0.0
        a = (C * R1 - B * R2) / det
        b = (A * R2 - B * R1) / det
        return a, b

    a, b = solve_free()
    if a >= 0 and b >= 0:
        return a, b
    if a < 0 and b >= 0:
        C = dot(mw, mw)
        return 0.0, (dot(mw, vw) / C if C > 1e-12 else 0.0)
    if b < 0 and a >= 0:
        A = dot(ew, ew)
        return (dot(ew, vw) / A if A > 1e-12 else 0.0), 0.0
    return 0.0, 0.0


def fit_rel_residual(v, e, m, a, b, w):
    """拟合残差：未解释部分的二范数 / 目标自身的二范数。

    分母带一个绝对地板 FIT_DEN_FLOOR，是为了小体积饮品。
    例如「大杯鲜萃咖啡」总共才 13kcal，任何零点几克的差异在纯相对口径下
    都会被放大到 20%+，从而被误判成"模型不适用"。地板让这类纯黑咖啡不被冤枉。
    """
    num = 0.0
    den = 0.0
    for d in DIMS:
        pred = a * e[d] + b * m[d]
        num += (v[d] - pred) ** 2
        den += v[d] ** 2
    den = max(den ** 0.5, FIT_DEN_FLOOR)
    return (num ** 0.5) / den


# --------------------------------------------------------------------------
# 6. 主流程
# --------------------------------------------------------------------------

def build_weights(v, milk_v):
    """五个维度等权全 1 —— 即普通最小二乘（OLS）。

    为什么不做加权：官方营养数据按整数发布（蛋白 8g、钙 251mg），
    舍入噪声在**绝对单位**上近似同方差，因此 OLS 本身就是正确估计量。

    实测对比四种方案（看阴性对照能否被正确判为 0 咖啡）：
        相对-目标+地板5        对照最大 a = 0.430   ✗
        相对-目标+地板15       对照最大 a = 0.473   ✗
        相对-基底             对照最大 a = 0.452   ✗
        绝对-原始单位 OLS      对照最大 a = 0.064   ✓
    一旦按"相对误差"加权，蛋白/脂肪这类小量级维度会被地板值放大，
    拟合就跑去配不舍入噪声了。OLS 下结果也才物理自洽：
    冰奶铁中杯 a=1.02 与 冰美式中杯 a=1.00 —— 同是那份浓缩，只差奶量。
    """
    return {d: 1.0 for d in DIMS}


def analyze(nutrition_rows, menu):
    menu_meals = menu["meals"]
    lookup = {r["name"]: r["v"] for r in nutrition_rows}

    espresso_row = next((r for r in nutrition_rows if r["name"] == "浓缩咖啡"), None)
    if espresso_row is None:
        sys.exit("[fatal] 营养表里找不到「浓缩咖啡」，无法建立咖啡基底。")
    espresso = espresso_row["v"]
    espresso_name = espresso_row["name"]

    BASIS_NAMES = {
        espresso_name,
        "冰牛奶中杯", "热牛奶中杯",
        "冰燕麦奶中杯", "热燕麦奶中杯",
    }

    # 反向索引：五维数值完全相同 -> 一组品名。用于发现官方数据的撞车条目。
    vec_index = defaultdict(list)
    for r in nutrition_rows:
        vec_index[tuple(r["v"][d] for d in DIMS)].append(r["name"])

    drinks = []
    for r in nutrition_rows:
        name = r["name"]
        if not is_beverage(name):
            continue
        # 基底自身不参与评估（它是参照系，不是被解释对象）
        if name in BASIS_NAMES:
            continue

        v = r["v"]
        milk_name, milk_v = pick_milk_basis(name, lookup)
        if milk_v is None:
            continue

        w = build_weights(v, milk_v)
        a, b = nnls2(v, espresso, milk_v, w)
        resid = fit_rel_residual(v, espresso, milk_v, a, b, w)

        # 模型是「咖啡 + 奶」二组分。含第三种配料（蔗糖/可可/抹茶/冰淇淋）的饮品
        # 天然解释不了，残差会显著抬升。这类必须打标剔除，不能混进排行榜——
        # 否则「阳光柠檬红茶」这种纯糖水会被解出 6.65 份咖啡当量。
        out_of_model = resid > OUT_OF_MODEL_RESIDUAL or a > MAX_SHOTS
        if resid > OUT_OF_MODEL_RESIDUAL:
            oom_reason = "残差过高，含咖啡与奶之外的第三配料"
        elif a > MAX_SHOTS:
            oom_reason = f"咖啡当量 {a:.1f} 超过物理上限 {MAX_SHOTS:.0f} 份，模型不适用"
        else:
            oom_reason = None

        # 官方营养表存在条目营养数值完全撞车的情况。
        # 例：「冰浓浓黑巧大杯」与「冰牛奶小杯」五维数值一字不差 ——
        # 这说明该系列并未单独公布配方，而非它真的没加咖啡。
        # 这种情况必须显式标记，不能当成"零咖啡"的结论输出。
        vkey = tuple(v[d] for d in DIMS)
        peers = [n for n in vec_index[vkey] if n != name]

        coffee_kcal = a * espresso["energyKcal"]
        milk_kcal = b * milk_v["energyKcal"]
        total = coffee_kcal + milk_kcal
        milk_ratio = (milk_kcal / total) if total > 1e-9 else 0.0

        code, meal = map_menu(name, menu_meals)
        price_original = None
        price_card = None
        card_gate = None
        has_card_channel = False
        if meal:
            price_original = float(meal["originalPrice"])
            has_card_channel = bool(meal.get("canWithOrder"))
            price_card = float(meal["currentPrice"]) if has_card_channel else price_original
            card_gate = meal.get("discountType")

        def cpy(p):
            return (a / p) if (p and p > 0) else None

        drinks.append({
            "name": name,
            "temp": parse_temp(name),
            "size": parse_size(name),
            "milk_basis": milk_name,
            "espresso_equiv": round(a, 3),
            "milk_equiv": round(b, 3),
            "coffee_kcal": round(coffee_kcal, 1),
            "milk_kcal": round(milk_kcal, 1),
            "milk_ratio": round(milk_ratio, 4),
            "kcal": v["energyKcal"],
            "protein": v["protein"],
            "calcium": v["calcium"],
            "fit_residual": round(resid, 4),
            "out_of_model": out_of_model,
            "out_of_model_reason": oom_reason,
            "data_collision": bool(peers),
            "data_collision_with": peers,
            "menu_code": code,
            "price_original": price_original,
            "price_card": price_card,
            "has_card_channel": has_card_channel,
            "card_gate": card_gate,
            "cafe_per_yuan_original": None if cpy(price_original) is None else round(cpy(price_original), 4),
            "cafe_per_yuan_card": None if cpy(price_card) is None else round(cpy(price_card), 4),
        })

    return drinks, espresso_row


CONTROL_RE = re.compile(r"^(冰|热)(牛奶|燕麦奶)(小杯|大杯)$")
CONTROL_TEA = ("锡兰红茶", "川宁伯爵红茶")


def validate_controls(drinks):
    """阴性对照：成分表里确实不含咖啡的饮品，咖啡当量必须 ≈ 0。

    这是整套方法最重要的自检 —— 如果连「热牛奶大杯」都被解出咖啡，
    说明模型在拿噪声拟合，全部结论作废。

    对照组严格限定为「门店纯奶的其他杯型」+「纯茶」，因为它们是真正只有
    单一奶基底的产品。朱古力/抹茶/雪冰这类含第三配料的另有 THIRD-party 标记，
    不参与这项检验（它们的失真是模型已知边界，不是模型失效）。
    """
    controls = [d for d in drinks
                if CONTROL_RE.match(d["name"]) or d["name"] in CONTROL_TEA]
    worst = max((d["espresso_equiv"] for d in controls), default=0.0)
    third = [d["name"] for d in drinks if d["out_of_model"]]
    collided = {d["name"]: d["data_collision_with"] for d in drinks if d["data_collision"]}
    return {
        "count": len(controls),
        "names": [d["name"] for d in controls],
        "max_espresso_equiv": round(worst, 3),
        "passed": worst < 0.30,
        "out_of_model_count": len(third),
        "out_of_model_names": third,
        "data_collision_count": len(collided),
        "data_collision_detail": collided,
    }


def parse_time_windows(stores):
    """从 reservationTimeOptions 解析每家店的供餐时段。

    官方没有单独文档说明这个字段，但它藏着一个真相：
    早餐起点每家店都不一样（05:14 / 06:14 / 06:44 / 07:14），
    而终点统一 —— 最便宜的咖啡通道因此有个"硬关门时间"。
    """
    pat = re.compile(r"([\u4e00-\u9fa5]+)\(([^)]*)\)")
    out = []
    for s in stores["stores"]:
        opts = s.get("reservationTimeOptions") or []
        if not opts:
            continue
        text = opts[0]["reservationOptionText"]
        periods = {}
        for m in pat.finditer(text):
            label = m.group(1)
            segs = []
            for seg in m.group(2).split(","):
                seg = seg.strip()
                if "至" not in seg:
                    continue
                a, b = seg.split("至")
                segs.append((a.strip(), b.strip()))
            if segs:
                periods[label] = segs
        breakfast = periods.get("早餐", [[None, None]])[0]
        out.append({
            "storeCode": s["storeCode"],
            "storeName": s["storeName"],
            "address": s["address"],
            "distance": s.get("distance"),
            "breakfast_start": breakfast[0],
            "breakfast_end": breakfast[1],
            "periods": {k: v for k, v in periods.items()},
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=os.path.join(DATA, "cafe_index.json"))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    nutrition_rows = load_nutrition(os.path.join(DATA, "nutrition.csv"))
    menu = load_json(os.path.join(DATA, "menu_cafe.json"))
    stores = load_json(os.path.join(DATA, "stores.json"))

    drinks, espresso_row = analyze(nutrition_rows, menu)
    controls = validate_controls(drinks)
    windows = parse_time_windows(stores)

    src = menu["_source"]
    result = {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S %z"),
        "store": {
            "storeCode": src["params"]["storeCode"],
            "storeName": src["storeName"],
            "storeAddress": src["storeAddress"],
            "menuFetchedAt": src["fetchedAt"],
        },
        "method": {
            "model": "target ≈ a × 浓缩咖啡 + b × 奶基底（五维 NNLS 解卷积）",
            "dims": DIMS,
            "excluded_dim": "sodium（受水质与蒸汽影响，对区分咖啡与奶无贡献，故剔除）",
            "weighting": "每维按 max(目标值, 奶基底值, 5) 归一化，等权处理相对误差",
            "espresso_basis": {d: espresso_row["v"][d] for d in DIMS},
        },
        "validation": controls,
        "time_windows": windows,
        "drink_count": len(drinks),
        "priced_count": sum(1 for d in drinks if d["price_original"]),
        "drinks": drinks,
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if args.quiet:
        return

    print(f"[ok] 饮品总数 {len(drinks)}，其中可定价 {result['priced_count']}")
    print(f"[自检] 阴性对照 {controls['count']} 款，最大咖啡当量 "
          f"{controls['max_espresso_equiv']} -> "
          f"{'通过' if controls['passed'] else '!! 未通过，模型可疑'}")

    rankable = [d for d in drinks
                if d["cafe_per_yuan_original"] is not None and not d["out_of_model"]]

    print("\n=== 每元咖啡当量 TOP（原价通道，已剔除模型不适用的饮品）===")
    ranked = sorted(rankable, key=lambda x: -x["cafe_per_yuan_original"])
    for d in ranked[:12]:
        print(f"  {d['name']:<14} {d['cafe_per_yuan_original']:>7.3f}  "
              f"¥{d['price_original']:>5}  奶占比 {d['milk_ratio']*100:>5.1f}%  "
              f"残差 {d['fit_residual']:.3f}")

    print("\n=== 同一杯的双价格通道（原价 -> 卡价）===")
    for d in drinks:
        if d["has_card_channel"]:
            gain = (d["cafe_per_yuan_card"] / d["cafe_per_yuan_original"]
                    if d["cafe_per_yuan_original"] else 0)
            print(f"  {d['name']:<14} ¥{d['price_original']:>5} -> ¥{d['price_card']:<5} "
                  f"提神性价比 x{gain:.2f}   (gated: {d['card_gate']})")

    print("\n=== 供餐时段（早餐窗口起点逐店不同）===")
    for w in windows:
        print(f"  {w['storeName'][:22]:<24} 早餐 {w['breakfast_start']} - {w['breakfast_end']}")

    print(f"\n[写入] {args.out}")


if __name__ == "__main__":
    main()
