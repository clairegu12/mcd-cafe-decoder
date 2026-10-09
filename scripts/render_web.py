#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 data/cafe_index.json 渲染成一个离线单文件网页 web/index.html。

不依赖任何 CDN —— 双击就能开，方便直接截图贴进 README。

用法：
  python scripts/render_web.py [-i data/cafe_index.json] [-o web/index.html]
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# 页面骨架。数据用 __DATA__ 占位，避免和 CSS 大括号冲突。
# ---------------------------------------------------------------------------

TPL = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>麦咖解码器 · McCafé Decoder</title>
<style>
  :root{
    --mcd-red:#DA291C; --mcd-yellow:#FFC72C;
    --cream:#FBF7F0; --card:#FFFFFF;
    --ink:#241B14; --ink-2:#5C4B3D; --ink-3:#8A7663;
    --line:#E7DACD; --milk:#C9A227; --coffee:#4A2C17; --green:#1B7F5E;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{
    background:var(--cream); color:var(--ink);
    font-family:"PingFang SC","Hiragino Sans GB","Microsoft YaHei",-apple-system,sans-serif;
    line-height:1.65; -webkit-font-smoothing:antialiased;
  }
  .wrap{max-width:1080px;margin:0 auto;padding:0 22px 80px}

  /* hero */
  header.hero{padding:52px 0 30px;border-bottom:1px solid var(--line)}
  h1{font-size:40px;letter-spacing:-.5px;font-weight:800}
  h1 .sub{display:block;font-size:15px;font-weight:500;color:var(--ink-3);letter-spacing:3px;margin-bottom:8px}
  .lead{font-size:18px;color:var(--ink-2);margin-top:14px;max-width:760px}
  .lead b{color:var(--mcd-red)}
  .meta{margin-top:16px;font-size:13px;color:var(--ink-3)}

  /* stat strip */
  .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:26px 0 0}
  .stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px}
  .stat .n{font-size:30px;font-weight:800;letter-spacing:-1px;line-height:1.15}
  .stat .l{font-size:12.5px;color:var(--ink-3);margin-top:3px}
  .stat.red .n{color:var(--mcd-red)} .stat.milk .n{color:var(--milk)} .stat.green .n{color:var(--green)}

  section{margin-top:52px}
  h2{font-size:23px;font-weight:800;letter-spacing:-.3px;margin-bottom:6px}
  h2::before{content:"";display:inline-block;width:5px;height:20px;background:var(--mcd-red);
    margin-right:10px;vertical-align:-2px;border-radius:2px}
  .desc{color:var(--ink-2);font-size:14.5px;margin-bottom:20px;max-width:800px}

  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:22px}

  /* findings */
  .findings{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:16px}
  .find{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;border-top:4px solid var(--mcd-red)}
  .find:nth-child(2){border-top-color:var(--milk)}
  .find:nth-child(3){border-top-color:var(--green)}
  .find h3{font-size:16px;font-weight:700;margin-bottom:8px}
  .find p{font-size:14px;color:var(--ink-2)}
  .find .kicker{font-size:11.5px;color:var(--ink-3);letter-spacing:1.5px;margin-bottom:6px}

  /* controls */
  .controls{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px;align-items:center}
  button.toggle{
    background:var(--card);border:1.5px solid var(--line);border-radius:999px;
    padding:8px 18px;font-size:13.5px;font-weight:600;cursor:pointer;color:var(--ink-2);
    font-family:inherit;transition:.15s;
  }
  button.toggle:hover{border-color:var(--ink-3)}
  button.toggle.on{background:var(--ink);color:#fff;border-color:var(--ink)}
  .note{font-size:12.5px;color:var(--ink-3)}

  svg{width:100%;height:auto;display:block}
  .legend{display:flex;gap:18px;flex-wrap:wrap;font-size:12.5px;color:var(--ink-2);margin-top:12px}
  .dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:0}

  /* table */
  table{width:100%;border-collapse:collapse;font-size:14px}
  th,td{padding:9px 10px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
  th{font-size:12px;color:var(--ink-3);font-weight:600;text-align:right}
  th:first-child,td:first-child{text-align:left}
  tbody tr:hover{background:#FDF6EC}
  td.name{font-weight:600}
  .pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11.5px;font-weight:700}
  .pill.card{background:#E6F4EE;color:var(--green)}
  .pill.none{background:#F3EDE6;color:var(--ink-3)}

  /* windows */
  .win{margin-bottom:14px}
  .win .top{display:flex;justify-content:space-between;font-size:13.5px;margin-bottom:5px}
  .win .nm{font-weight:600}
  .win .tm{color:var(--ink-2);font-variant-numeric:tabular-nums}
  .bar{height:12px;background:#F0E7DC;border-radius:6px;position:relative;overflow:hidden}
  .bar i{position:absolute;top:0;bottom:0;background:var(--mcd-yellow);border-radius:6px}
  .axis{display:flex;justify-content:space-between;font-size:11px;color:var(--ink-3);margin-top:4px}

  /* footnote */
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px}
  .warn{background:#FFF8E6;border:1px solid #F0DFB0;border-radius:12px;padding:16px 18px;font-size:13.5px;color:#6B5416}
  .collide{max-height:210px;overflow:auto;font-size:12.5px;color:var(--ink-2);margin-top:10px}
  .collide div{padding:3px 0;border-bottom:1px dashed var(--line)}
  footer{margin-top:56px;padding-top:20px;border-top:1px solid var(--line);font-size:12.5px;color:var(--ink-3)}
  a{color:var(--mcd-red)}
</style>
</head>
<body>
<div class="wrap">

<header class="hero">
  <h1><span class="sub">MCD CAFÉ DECODER</span>麦咖解码器</h1>
  <p class="lead">麦当劳会告诉你一杯咖啡多少钱，但从不告诉你
    <b>那杯「咖啡」里究竟有多少是咖啡</b>。
    本项目用官方公布的营养数据做解卷积，把它算出来 —— 再除以<b>你实际付的钱</b>。</p>
  <p class="meta" id="metaLine"></p>
  <div class="stats" id="stats"></div>
</header>

<section>
  <h2>三个结论</h2>
  <div class="findings">
    <div class="find">
      <div class="kicker">发现 01</div>
      <h3>整条麦咖啡产品线，几乎都是同一份浓缩</h3>
      <p>美式、奶铁、卡布奇诺、燕麦奶铁、焦糖玛奇朵解出来的咖啡当量全部落在
        <b id="shotRange"></b> 份之间。差距来自杯型，不来自品类。
        也就是说 —— <b>提神效果基本一样，你多付的钱买到的是奶。</b></p>
    </div>
    <div class="find">
      <div class="kicker">发现 02</div>
      <h3>奶铁里九成以上的热量来自牛奶</h3>
      <p id="milkLine"></p>
    </div>
    <div class="find">
      <div class="kicker">发现 03</div>
      <h3>同一杯存在两条价格通道，最多差 <span id="maxGap"></span> 倍</h3>
      <p id="gapLine"></p>
    </div>
  </div>
</section>

<section>
  <h2>提神性价比地图</h2>
  <p class="desc">横轴＝这杯里<b>牛奶提供了多少比例的热量</b>（越靠右越像一杯奶）；
     纵轴＝<b>每元能买到多少咖啡当量</b>（越高越划算）；气泡大小＝总热量。
     真正的咖啡在左上角，真正的奶饮在右下角。</p>
  <div class="controls">
    <button class="toggle on" data-ch="original">按门店原价</button>
    <button class="toggle" data-ch="card">按随单购麦金卡价</button>
    <span class="note" id="toggleNote"></span>
  </div>
  <div class="card">
    <svg id="scatter" viewBox="0 0 1000 520" role="img" aria-label="奶占比与每元咖啡当量散点图"></svg>
    <div class="legend">
      <span><span class="dot" style="background:#4A2C17"></span>黑咖啡（奶占比 &lt; 20%）</span>
      <span><span class="dot" style="background:#B5762E"></span>混合（20%–70%）</span>
      <span><span class="dot" style="background:#C9A227"></span>奶咖（&gt; 70%）</span>
      <span class="note">气泡半径 ∝ 热量</span>
    </div>
  </div>
</section>

<section>
  <h2>排行榜</h2>
  <p class="desc">按当前所选价格通道排序。标记为「需随单购」的价格意味着
     不随单买那张卡，你拿不到这个价。</p>
  <div class="card">
    <table id="rankTable">
      <thead><tr>
        <th>饮品</th><th>咖啡当量</th><th>奶占比</th><th>热量</th>
        <th>单价</th><th>每元咖啡当量</th><th>价格通道</th>
      </tr></thead>
      <tbody></tbody>
    </table>
  </div>
</section>

<section>
  <h2>双通道差价</h2>
  <p class="desc">同一杯饮品，<code class="mono">originalPrice</code> 与
     <code class="mono">currentPrice</code> 在官方接口里是两个字段。
     差额不是折扣，而是<b>一道门槛</b>：<code class="mono">canWithOrder=true</code>
     意味着必须随单购麦金卡才能享受。</p>
  <div class="card" id="channels"></div>
</section>

<section>
  <h2>早餐窗口：最便宜的咖啡有时间锁</h2>
  <p class="desc">门店接口返回的 <code class="mono">reservationTimeOptions</code> 里藏着各店各自的供餐时段。
     早餐<b>开门时间逐店不同</b>，但<b>关门时间高度统一</b> —— 9.9 元早餐组合（含鲜萃咖啡）只在这个窗口内有效。</p>
  <div class="card" id="windows"></div>
</section>

<section>
  <h2>方法与自检</h2>
  <p class="desc">结论能不能信，取决于有没有办法证伪。这里给出两条自检和一处主动披露。</p>
  <div class="card">
    <p><b>模型</b>：<code class="mono">一杯饮品 ≈ a × 浓缩咖啡 + b × 奶基底</code>，
       在能量/蛋白质/脂肪/碳水/钙五个维度上做非负最小二乘解卷积。
       奶基底按「是否燕麦」与「冰热」切换，取门店同产品线、同温度的纯奶。</p>
    <p style="margin-top:10px"><b>为什么用普通最小二乘</b>：官方营养数据按整数发布，舍入噪声在绝对单位上近似同方差。
       实测四种加权方案里，OLS 是唯一能把阴性对照（纯牛奶、纯燕麦奶、纯茶）的咖啡当量压到
       <b id="ctrlMax"></b> 份的方案；其余方案会落到 0.43–0.47 份，说明在拟合噪声。</p>
    <div class="warn" style="margin-top:16px">
      <b>主动披露：官方营养表存在条目撞车。</b>
      有 <b id="collideN"></b> 个条目的五维营养数值与另一完全不同的产品一字不差，
      例如「热浓浓黑巧大杯」完全等同于「热牛奶大杯」、「冰焦糖玛奇朵」完全等同于「冰奶铁中杯」。
      这说明这些 SKU 并未单独公布配方，<b>本项目因此不把它们当作独立的咖啡结论输出</b>。
    </div>
    <div class="collide" id="collideList"></div>
  </div>
</section>

<footer>
  <p>数据来源：麦当劳中国官方 MCP Server（<code class="mono">list-nutrition-foods</code> /
     <code class="mono">query-meals</code> / <code class="mono">query-nearby-stores</code>），
     由本项目的 <code class="mono">scripts/analyze_cafe.py</code> 计算。</p>
  <p style="margin-top:6px">价格与菜单具门店与时效性，以上取数自 <span id="footStore"></span>，
     仅供研究用途，不构成消费建议。</p>
</footer>

</div>

<script>
const DATA = __DATA__;

const fmt = (v, n=2) => (v===null||v===undefined) ? '—' : Number(v).toFixed(n);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

// ---- 可参与排行/绘图的样本：有价格、且模型适用 ----
const pool = DATA.drinks.filter(d => d.price_original && !d.out_of_model);

// ---- 元信息 ----
const stock = new Set(pool.filter(d=>d.size===null || d.size==='中').map(d=>d.name));
document.getElementById('metaLine').textContent =
  `门店 ${DATA.store.storeName} · ${DATA.store.storeCode} ｜ 菜单取数 ${DATA.store.menuFetchedAt} ｜ ` +
  `共解析 ${DATA.drink_count} 款饮品，其中 ${DATA.priced_count} 款可定价 ｜ 生成 ${DATA.generated_at}`;
document.getElementById('footStore').textContent = `${DATA.store.storeName}（${DATA.store.storeCode}）`;

// ---- 顶部数字 ----
// 真正的咖啡产品线。刻意排除「浓浓黑巧」系列：它们在官方营养表里
// 与纯牛奶数值撞车，把它们算进来会把"典型咖啡当量"拉成 0.00 这种废结论。
const COFFEE_CORE = /美式|奶铁|卡布奇诺|玛奇朵|鲜萃咖啡|浓缩/;
const coffeeCore = pool.filter(d => COFFEE_CORE.test(d.name) && !d.data_collision);

const shotsAll = coffeeCore.map(d=>d.espresso_equiv).sort((a,b)=>a-b);
const coreMin = Math.min(...shotsAll), coreMax = Math.max(...shotsAll);
document.getElementById('shotRange').textContent = `${fmt(coreMin,2)} – ${fmt(coreMax,2)}`;

const latte = pool.filter(d=>/奶铁|卡布奇诺|玛奇朵/.test(d.name));
const mr = latte.map(d=>d.milk_ratio);
document.getElementById('milkLine').innerHTML =
  `全部 ${latte.length} 款奶咖的奶占比落在 <b>${(Math.min(...mr)*100).toFixed(0)}% – ${(Math.max(...mr)*100).toFixed(0)}%</b>，` +
  `而美式只有 <b>${(Math.max(...pool.filter(d=>/美式/.test(d.name)).map(d=>d.milk_ratio))*100).toFixed(0)}%</b> 以下。` +
  `一杯 ¥${latte[0] ? latte[0].price_original : 21} 的奶铁，你买的热量里九成是牛奶。`;

const dual = pool.filter(d=>d.has_card_channel);
const gaps = dual.map(d=>d.cafe_per_yuan_card/d.cafe_per_yuan_original);
const gapMax = Math.max(...gaps);
const gi = gaps.indexOf(gapMax);
document.getElementById('maxGap').textContent = gapMax.toFixed(2);
document.getElementById('gapLine').innerHTML =
  `${esc(dual[gi].name)} 原价 ¥${dual[gi].price_original}，随单购麦金卡后 ¥${dual[gi].price_card}，` +
  `提神性价比直接翻 <b>${gapMax.toFixed(2)} 倍</b>。全场共有 ${dual.length} 款 SKU 存在这条通道，` +
  `但 <code class="mono">canWithOrder=true</code> 这道门槛并不写在菜单价格旁边。`;

document.getElementById('stats').innerHTML = `
  <div class="stat"><div class="n">${pool.length}</div><div class="l">款饮品完成解码</div></div>
  <div class="stat"><div class="n">${fmt(shotsAll[Math.floor(shotsAll.length/2)],2)}</div><div class="l">杯咖啡当量中位数（份浓缩）</div></div>
  <div class="stat milk"><div class="n">${(Math.max(...mr)*100).toFixed(0)}%</div><div class="l">奶咖的最高奶占比</div></div>
  <div class="stat green"><div class="n">${gapMax.toFixed(2)}×</div><div class="l">同一杯的最大性价比差</div></div>
  <div class="stat red"><div class="n">${DATA.validation.data_collision_count}</div><div class="l">处官方营养数据撞车</div></div>`;

document.getElementById('ctrlMax').textContent = fmt(DATA.validation.max_espresso_equiv,3);
document.getElementById('collideN').textContent = DATA.validation.data_collision_count;
document.getElementById('collideList').innerHTML =
  Object.entries(DATA.validation.data_collision_detail).slice(0,40)
    .map(([k,v]) => `<div>${esc(k)} &nbsp;≡&nbsp; ${esc(v.join('、'))}</div>`).join('');

// ---- 早餐窗口 ----
(function(){
  const ws = DATA.time_windows.filter(w=>w.breakfast_start && w.breakfast_end);
  if(!ws.length) return;
  const toMin = s => { const [h,m]=s.split(':').map(Number); return h*60+m; };
  const LO = 4*60, HI = 11*60;
  document.getElementById('windows').innerHTML = ws.map(w=>{
    const a = toMin(w.breakfast_start), b = toMin(w.breakfast_end);
    const l = Math.max(0,(a-LO)/(HI-LO)*100), r = Math.max(0,(b-LO)/(HI-LO)*100);
    return `<div class="win">
      <div class="top"><span class="nm">${esc(w.storeName)}</span>
        <span class="tm">早餐 ${w.breakfast_start} – ${w.breakfast_end}　（${Math.round((b-a))} 分钟）</span></div>
      <div class="bar"><i style="left:${l}%;width:${Math.max(.6,r-l)}%"></i></div></div>`;
  }).join('') + `<div class="axis"><span>04:00</span><span>07:30</span><span>11:00</span></div>`;
})();

// ---- 散点图 ----
let channel = 'original';
function yVal(d){ return channel==='card' ? d.cafe_per_yuan_card : d.cafe_per_yuan_original; }

function draw(){
  const pts = pool.filter(d=>yVal(d)!==null && yVal(d)>0);
  if(!pts.length) return;
  const W=1000,H=520,ML=78,MR=26,MT=26,MB=64;
  const xs = pts.map(d=>d.milk_ratio), ys = pts.map(yVal), ks = pts.map(d=>d.kcal);
  const xmax = Math.max(...xs)*1.06, ymax = Math.max(...ys)*1.16;
  const X = v => ML + v/xmax*(W-ML-MR);
  const Y = v => H-MB - v/ymax*(H-MT-MB);
  const R = v => 5 + Math.sqrt(v/Math.max(...ks))*13;

  let s = '';
  // y grid
  const step = ymax>0.1 ? 0.02 : 0.01;
  for(let g=0; g<=ymax+1e-9; g+=step){
    s += `<line x1="${ML}" y1="${Y(g)}" x2="${W-MR}" y2="${Y(g)}" stroke="#EFE5D9" stroke-width="1"/>`
       + `<text x="${ML-10}" y="${Y(g)+4}" text-anchor="end" font-size="11" fill="#8A7663">${g.toFixed(2)}</text>`;
  }
  s += `<text transform="translate(18,${H/2}) rotate(-90)" text-anchor="middle" font-size="12" fill="#5C4B3D">每元咖啡当量</text>`;
  // x ticks
  for(let p=0;p<=100;p+=20){
    s += `<line x1="${X(p/100)}" y1="${MT}" x2="${X(p/100)}" y2="${H-MB}" stroke="#EFE5D9" stroke-width="1"/>`
       + `<text x="${X(p/100)}" y="${H-MB+20}" text-anchor="middle" font-size="11" fill="#8A7663">${p}%</text>`;
  }
  s += `<text x="${(ML+W-MR)/2}" y="${H-22}" text-anchor="middle" font-size="12" fill="#5C4B3D">奶提供热量的占比</text>`;

  const color = r => r<0.2 ? '#4A2C17' : (r<0.7 ? '#B5762E' : '#C9A227');
  pts.sort((a,b)=>b.kcal-a.kcal).forEach(d=>{
    const cx=X(d.milk_ratio), cy=Y(yVal(d));
    s += `<circle cx="${cx}" cy="${cy}" r="${R(d.kcal)}" fill="${color(d.milk_ratio)}" fill-opacity=".30"
            stroke="${color(d.milk_ratio)}" stroke-width="1.4"><title>${esc(d.name)}｜奶占比 ${
            (d.milk_ratio*100).toFixed(1)}%｜每元咖啡当量 ${yVal(d).toFixed(3)}｜热量 ${d.kcal} kcal</title></circle>`;
    if(d.kcal>60 || d.milk_ratio<0.2 || d.milk_ratio>0.85){
      s += `<text x="${cx}" y="${cy-R(d.kcal)-5}" text-anchor="middle" font-size="11" fill="#241B14">${esc(d.name.replace(/^(冰|热)/,''))}</text>`;
    }
  });
  document.getElementById('scatter').innerHTML = s;
}

function renderTable(){
  const rows = pool.filter(d=>yVal(d)>0).sort((a,b)=>yVal(b)-yVal(a));
  document.querySelector('#rankTable tbody').innerHTML = rows.map(d=>{
    const need = (channel==='card') && d.has_card_channel;
    return `<tr>
      <td class="name">${esc(d.name)}</td>
      <td>${fmt(d.espresso_equiv,2)}</td>
      <td>${(d.milk_ratio*100).toFixed(1)}%</td>
      <td>${d.kcal}</td>
      <td>¥${channel==='card'?d.price_card:d.price_original}</td>
      <td><b>${fmt(yVal(d),3)}</b></td>
      <td><span class="pill ${need?'card':'none'}">${need?'需随单购':'无门槛'}</span></td>
    </tr>`;
  }).join('');
}

function renderChannels(){
  const rows = pool.filter(d=>d.has_card_channel);
  const seen = new Set();
  document.getElementById('channels').innerHTML = rows.filter(d=>{
    const k = d.name.replace(/^(冰|热)/,'');
    if(seen.has(k)) return false; seen.add(k); return true;
  }).sort((a,b)=>(b.cafe_per_yuan_card/b.cafe_per_yuan_original)-(a.cafe_per_yuan_card/a.cafe_per_yuan_original))
    .map(d=>{
      const x = d.cafe_per_yuan_card/d.cafe_per_yuan_original;
      return `<div class="win">
        <div class="top"><span class="nm">${esc(d.name)}</span>
          <span class="tm">¥${d.price_original} → <b style="color:#1B7F5E">¥${d.price_card}</b>　性价比 ×${x.toFixed(2)}</span></div>
        <div class="bar"><i style="left:0;width:${(d.price_card/d.price_original*100).toFixed(1)}%;background:#1B7F5E"></i></div>
        <div class="axis"><span>门槛：${esc(d.card_gate||'')}（membershipCode ${(DATA.drinks.find(z=>z.menu_code===d.menu_code)||{}).menu_code||''}）</span></div>
      </div>`;
    }).join('');
}

document.querySelectorAll('button.toggle').forEach(b=>{
  b.onclick = () => {
    document.querySelectorAll('button.toggle').forEach(z=>z.classList.remove('on'));
    b.classList.add('on');
    channel = b.dataset.ch;
    document.getElementById('toggleNote').textContent =
      channel==='card' ? '已切换：只比较随单购麦金卡后的价格。'
                       : '已切换：只比较门店划线原价。';
    draw(); renderTable(); renderChannels();
  };
});

document.getElementById('toggleNote').textContent = '当前按门店划线原价比较。';
draw(); renderTable(); renderChannels();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--inp", default=os.path.join(HERE, "data", "cafe_index.json"))
    ap.add_argument("-o", "--out", default=os.path.join(HERE, "web", "index.html"))
    a = ap.parse_args()

    with open(a.inp, encoding="utf-8") as f:
        data = json.load(f)

    html = TPL.replace("__DATA__", json.dumps(data, ensure_ascii=False))

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[ok] 渲染完成 -> {a.out}  ({len(html)} 字节)")
    print(f"     门店 {data['store']['storeName']} | 饮品 {data['drink_count']} "
          f"| 可定价 {data['priced_count']} | 自检通过 {data['validation']['passed']}")


if __name__ == "__main__":
    main()
