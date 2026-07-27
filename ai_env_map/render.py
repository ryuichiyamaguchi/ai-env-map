"""スキャン結果から自己完結 HTML を生成する。

主役は階層ツリー。どの階層にどの設定ファイルがあり、それが何を規定して
いるのかを、ディレクトリ構造のまま読めることを最優先にしている。
外部リソースは一切参照しない。CSS も含めて1ファイルに閉じる。
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime
from pathlib import Path

from .model import ScanResult, SCOPE_RANK, TreeNode

SCOPE_LABEL = {
    "user": "ユーザー全体",
    "project": "プロジェクト",
    "local": "ローカル個人",
    "enterprise": "組織管理",
}

KIND_LABEL = {
    "instructions": "指示",
    "settings": "設定",
    "rules": "ルール",
    "skill": "スキル",
    "agent": "エージェント",
    "mcp": "MCP",
}

GIT_LABEL = {
    "tracked": ("追跡", "ok"),
    "untracked": ("未追跡", "warn"),
    "none": ("git 外", "plain"),
}

STORE_LABEL = {
    "deliverables": "最終成果物", "engagements": "案件記録",
    "research": "リサーチ", "graph": "ナレッジグラフ",
}

SEV = {"high": ("要対応", "warn"), "mid": ("確認", "mid"), "low": ("参考", "plain")}

CSS = """
/* ==========================================================================
   AI 設定の階層マップ — 製図（ブループリント）の意匠
   温かみのある製図紙に方眼と粒子を重ね、見出しは明朝、構造は等幅で組む。
   外部リソースは一切参照しない。フォントは OS 標準、質感は SVG の data URI。
   ========================================================================== */
*,*::before,*::after{box-sizing:border-box}
[hidden]{display:none!important}

:root{
  /* 製図紙 */
  --bg:#f2eee4; --bg2:#e9e4d7; --panel:#fbf9f3; --panel2:#f5f1e7;
  --ink:#191713; --muted:#6a635a; --faint:#9a9287;
  --line:#ddd6c7; --line2:#eae4d6; --grid:rgba(28,79,99,.055);
  /* 製図インク */
  --accent:#1c4f63; --accent-soft:#dfe9ec; --accent-ink:#123845;
  --warn:#a83a17; --warn-soft:#f7e3da;
  --ok:#2f6b4f; --ok-soft:#e0ede5;
  --mid:#8a6410; --mid-soft:#f6ecd4;
  --shadow:0 1px 1px rgba(60,50,35,.05),0 14px 32px -26px rgba(60,50,35,.5);
  --serif:"Hiragino Mincho ProN","Yu Mincho",YuMincho,"MS Mincho",
    "Noto Serif JP","Noto Serif CJK JP","Songti SC","Times New Roman",serif;
  --sans:"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic UI","Yu Gothic",
    "Meiryo","Noto Sans JP","Noto Sans CJK JP",system-ui,-apple-system,sans-serif;
  --mono:"SF Mono","JetBrains Mono","Menlo","Cascadia Mono","Consolas",
    "DejaVu Sans Mono",ui-monospace,monospace;
}
@media (prefers-color-scheme:dark){
  :root{
    --bg:#0f1216; --bg2:#0b0e11; --panel:#161a20; --panel2:#1b2028;
    --ink:#e6e4dd; --muted:#9aa0a8; --faint:#6b7079;
    --line:#272d36; --line2:#1f242c; --grid:rgba(111,179,201,.05);
    --accent:#6fb3c9; --accent-soft:#182a33; --accent-ink:#9fd0e0;
    --warn:#e08a5c; --warn-soft:#31201a;
    --ok:#7fc0a0; --ok-soft:#16281f;
    --mid:#d3b169; --mid-soft:#2b2416;
    --shadow:0 1px 1px rgba(0,0,0,.4),0 14px 32px -26px rgba(0,0,0,.9);
  }
}
:root[data-theme="dark"]{
  --bg:#0f1216; --bg2:#0b0e11; --panel:#161a20; --panel2:#1b2028;
  --ink:#e6e4dd; --muted:#9aa0a8; --faint:#6b7079;
  --line:#272d36; --line2:#1f242c; --grid:rgba(111,179,201,.05);
  --accent:#6fb3c9; --accent-soft:#182a33; --accent-ink:#9fd0e0;
  --warn:#e08a5c; --warn-soft:#31201a; --ok:#7fc0a0; --ok-soft:#16281f;
  --mid:#d3b169; --mid-soft:#2b2416;
  --shadow:0 1px 1px rgba(0,0,0,.4),0 14px 32px -26px rgba(0,0,0,.9);
}
:root[data-theme="light"]{
  --bg:#f2eee4; --bg2:#e9e4d7; --panel:#fbf9f3; --panel2:#f5f1e7;
  --ink:#191713; --muted:#6a635a; --faint:#9a9287;
  --line:#ddd6c7; --line2:#eae4d6; --grid:rgba(28,79,99,.055);
  --accent:#1c4f63; --accent-soft:#dfe9ec; --accent-ink:#123845;
  --warn:#a83a17; --warn-soft:#f7e3da; --ok:#2f6b4f; --ok-soft:#e0ede5;
  --mid:#8a6410; --mid-soft:#f6ecd4;
  --shadow:0 1px 1px rgba(60,50,35,.05),0 14px 32px -26px rgba(60,50,35,.5);
}

html{scroll-behavior:smooth}
body{margin:0;color:var(--ink);font-family:var(--sans);
  line-height:1.72;font-size:14.5px;-webkit-font-smoothing:antialiased;
  background-color:var(--bg);
  background-image:
    linear-gradient(var(--grid) 1px,transparent 1px),
    linear-gradient(90deg,var(--grid) 1px,transparent 1px),
    radial-gradient(120% 80% at 50% -10%,var(--panel2) 0%,transparent 55%);
  background-size:26px 26px,26px 26px,100% 100%}
/* 粒子。紙の質感を出して平坦さを消す */
body::after{content:"";position:fixed;inset:0;pointer-events:none;z-index:60;
  opacity:.05;mix-blend-mode:multiply;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")}
@media (prefers-color-scheme:dark){body::after{mix-blend-mode:screen;opacity:.035}}
:root[data-theme="dark"] body::after{mix-blend-mode:screen;opacity:.035}

.wrap{max-width:1260px;margin:0 auto;padding:3rem 1.4rem 6rem;position:relative;z-index:2}

/* Japanese text layout fix */
h1,h2,h3{word-break:keep-all;overflow-wrap:break-word}
p,span,li,a,td{overflow-wrap:break-word}
img{object-fit:cover}
.phrase{display:inline}
@media (min-width:768px){.phrase{display:inline-block}}
@media (max-width:767px){
  .hero-main{font-size:clamp(1.5rem,7vw,2.5rem)!important;line-height:1.3!important}
  .hero-sub{font-size:clamp(.9rem,3.5vw,1.25rem)!important;line-height:1.5!important}
}

/* 読み込み時の段階的な出現 */
@keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@keyframes rule{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.rz{animation:rise .5s cubic-bezier(.22,.7,.3,1) both}

/* ---- 見出し ---- */
header.top{position:relative;padding:0 0 1.6rem;margin-bottom:2rem;
  border-bottom:1px solid var(--line)}
header.top::after{content:"";position:absolute;left:0;right:0;bottom:-1px;height:2px;
  background:var(--accent);transform-origin:left;
  animation:rule .9s cubic-bezier(.22,.7,.3,1) .15s both;width:82px}
.stamp{display:inline-flex;align-items:center;gap:.5rem;font-family:var(--mono);
  font-size:.68rem;letter-spacing:.18em;text-transform:uppercase;color:var(--accent);
  border:1px solid var(--accent);border-radius:2px;padding:.12rem .5rem;
  margin-bottom:.9rem}
.stamp::before{content:"";width:5px;height:5px;background:var(--accent);
  border-radius:50%}
.hero-main{font-family:var(--serif);font-weight:600;
  font-size:clamp(1.9rem,4vw,2.9rem);margin:0 0 .35rem;letter-spacing:.02em;
  line-height:1.25}
.hero-sub{font-family:var(--serif);font-size:clamp(.95rem,1.6vw,1.12rem);
  color:var(--muted);margin:0;letter-spacing:.02em}
.meta{margin-top:1rem;font-size:.76rem;color:var(--faint);font-family:var(--mono);
  font-variant-numeric:tabular-nums;display:flex;gap:1.2rem;flex-wrap:wrap}
.meta b{color:var(--muted);font-weight:600}

/* ---- 指標カード ---- */
.cards{display:grid;gap:.8rem;grid-template-columns:repeat(auto-fit,minmax(146px,1fr));
  margin:0 0 3rem}
.card{position:relative;background:var(--panel);border:1px solid var(--line);
  border-radius:3px;padding:1rem .95rem .85rem;box-shadow:var(--shadow);
  overflow:hidden;transition:transform .18s cubic-bezier(.22,.7,.3,1),
    border-color .18s}
.card::before{content:"";position:absolute;top:0;left:0;width:26px;height:2px;
  background:var(--accent)}
.card:hover{transform:translateY(-2px);border-color:var(--accent)}
.card.alert::before{background:var(--warn);width:100%}
.card .n{font-family:var(--mono);font-size:1.72rem;font-weight:600;
  font-variant-numeric:tabular-nums;letter-spacing:-.03em;line-height:1.15}
.card.alert .n{color:var(--warn)}
.card .l{font-size:.73rem;color:var(--muted);margin-top:.25rem;line-height:1.5;
  letter-spacing:.02em}

/* ---- 節 ---- */
section{margin:0 0 3.6rem;scroll-margin-top:1rem}
.sec-h{display:flex;align-items:flex-start;gap:.85rem;margin:0 0 .45rem}
.idx{flex:0 0 auto;font-family:var(--mono);font-size:.72rem;font-weight:600;
  letter-spacing:.1em;color:var(--accent);border:1px solid var(--accent);
  border-radius:2px;padding:.12rem .42rem;margin-top:.3rem}
h2{font-family:var(--serif);font-size:1.34rem;font-weight:600;margin:0;
  letter-spacing:.03em}
.lede{color:var(--muted);font-size:.87rem;margin:0 0 1.25rem;max-width:74ch;
  padding-left:2.6rem;font-family:var(--serif);letter-spacing:.015em}

/* ---- 面 ---- */
.panel{background:var(--panel);border:1px solid var(--line);border-radius:4px;
  box-shadow:var(--shadow);overflow:hidden}
.panel + .panel{margin-top:1rem}
.panel-h{padding:.72rem 1.05rem;border-bottom:1px solid var(--line);font-size:.83rem;
  font-weight:650;display:flex;justify-content:space-between;gap:1rem;
  align-items:center;flex-wrap:wrap;background:var(--panel2);
  font-family:var(--mono);letter-spacing:.02em}
.panel-h .sub{font-weight:400;color:var(--muted);font-size:.74rem;
  font-family:var(--sans)}

/* ---- 操作卓 ---- */
.treebar{display:flex;gap:.4rem;align-items:center;flex-wrap:wrap;
  padding:.6rem 1.05rem;border-bottom:1px solid var(--line);background:var(--panel2)}
.tbtn{background:var(--panel);border:1px solid var(--line);border-radius:2px;
  padding:.22rem .62rem;font-size:.73rem;cursor:pointer;color:var(--muted);
  font-family:var(--mono);letter-spacing:.03em;transition:all .15s}
.tbtn:hover{border-color:var(--accent);color:var(--accent);background:var(--accent-soft)}
.tbtn.on{border-color:var(--accent);color:var(--panel);background:var(--accent)}
.tsearch{flex:1 1 190px;min-width:150px;background:var(--panel);
  border:1px solid var(--line);border-radius:2px;padding:.24rem .6rem;
  font-size:.76rem;color:var(--ink);font-family:var(--mono)}
.tsearch:focus{outline:none;border-color:var(--accent)}
.tsearch::placeholder{color:var(--faint)}
.treebar .hint{font-size:.72rem;color:var(--faint);font-family:var(--mono);
  width:100%}
.tsep{width:1px;height:16px;background:var(--line)}

/* ---- 階層ツリー ----
   入れ子は DOM の入れ子そのもので表現する。フラットな行に余白を計算して
   付ける方式では、どこで階層が切り替わったのかが目で追えないため。 */
/* 木は本来横に伸びるもの。狭い画面で切り落とすより、枠の中で横スクロール
   させたほうがパスを最後まで読める。 */
.tree{padding:.85rem 1.05rem 1.2rem;font-size:.845rem;overflow-x:auto}
.dnode{margin:0}
.dnode > summary{list-style:none;cursor:pointer;display:flex;align-items:center;
  gap:.45rem;flex-wrap:wrap;padding:.26rem .4rem;border-radius:3px;
  margin-left:-.4rem;transition:background .14s}
.dnode > summary::-webkit-details-marker{display:none}
.dnode > summary:hover{background:var(--line2)}
.tw{width:.8rem;flex:0 0 .8rem;text-align:center;color:var(--faint);
  font-size:.62rem;transition:transform .16s cubic-bezier(.22,.7,.3,1)}
.dnode[open] > summary .tw,.grouped[open] > summary .tw{transform:rotate(90deg)}
.dnode.leaf > summary{cursor:default}
.dnode.leaf > summary .tw{opacity:.2}
.lv{flex:0 0 auto;font-family:var(--mono);font-size:.62rem;font-weight:600;
  letter-spacing:.06em;color:var(--faint);border:1px solid var(--line);
  border-radius:2px;padding:0 .26rem;font-variant-numeric:tabular-nums;
  background:var(--panel2)}
.dname{font-weight:600;font-family:var(--mono);font-size:.845rem;
  word-break:break-all;letter-spacing:.01em}
.dcount{font-size:.7rem;color:var(--faint);font-family:var(--mono);
  font-variant-numeric:tabular-nums}
.repo{font-size:.7rem;color:var(--muted);font-family:var(--mono);
  font-variant-numeric:tabular-nums}
summary.is-repo{background:linear-gradient(90deg,var(--accent-soft),transparent 72%);
  box-shadow:inset 2px 0 0 var(--accent)}
summary.is-repo:hover{background:linear-gradient(90deg,var(--accent-soft),transparent 55%)}

/* 深さ1段ごとに実際の罫線を1本引く。色は段ごとに変える。 */
.kids{margin-left:.44rem;padding-left:.95rem;
  border-left:1.5px solid var(--rail,var(--line));position:relative}
.kids::before{content:"";position:absolute;left:-1.5px;top:0;width:1.5px;height:9px;
  background:var(--panel)}

/* ---- ファイル行 ---- */
.f{display:flex;width:100%;text-align:left;gap:.45rem;align-items:flex-start;
  background:none;border:0;border-radius:3px;padding:.3rem .42rem;cursor:pointer;
  font-family:inherit;color:inherit;margin-left:-.42rem;font-size:inherit;
  transition:background .14s,box-shadow .14s;position:relative}
.f:hover{background:var(--line2);box-shadow:inset 2px 0 0 var(--accent)}
.f:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.f .fic{flex:0 0 .8rem;text-align:center;color:var(--accent);font-size:.66rem;
  line-height:1.75;opacity:.75}
.f-body{flex:1 1 auto;min-width:0}
.f-head{display:flex;align-items:baseline;gap:.4rem;flex-wrap:wrap}
.fname{font-family:var(--mono);font-size:.815rem;font-weight:600;
  word-break:break-all}
.decl{color:var(--muted);font-size:.775rem;margin-top:.04rem;line-height:1.6}
.decl b{color:var(--accent);font-weight:600;font-family:var(--mono);
  font-size:.72rem;letter-spacing:.05em;margin-right:.2rem}
.st{color:var(--faint);font-size:.72rem;font-family:var(--mono);
  font-variant-numeric:tabular-nums}

.grouped > summary{list-style:none;cursor:pointer;font-size:.78rem;
  color:var(--muted);display:flex;gap:.42rem;align-items:center;flex-wrap:wrap;
  padding:.26rem .42rem;border-radius:3px;margin-left:-.42rem;
  font-family:var(--mono);transition:background .14s}
.grouped > summary:hover{background:var(--line2)}
.grouped > summary::-webkit-details-marker{display:none}
/* grid の子は既定で min-width:auto。列を minmax(0,1fr) にしないと、中の
   nowrap 要素が列幅を押し上げて親を突き抜ける。 */
.glist{display:grid;grid-template-columns:minmax(0,1fr);gap:.04rem;
  margin:.24rem 0 .4rem .44rem;border-left:1.5px solid var(--line);
  padding-left:.95rem}
.gitem{font-size:.775rem;display:flex;gap:.45rem;align-items:flex-start;
  background:none;border:0;padding:.18rem .42rem;border-radius:3px;cursor:pointer;
  font-family:inherit;color:inherit;text-align:left;width:100%;min-width:0;
  transition:background .14s}
.gitem:hover{background:var(--line2);box-shadow:inset 2px 0 0 var(--accent)}
.gitem .gn{font-family:var(--mono);font-weight:600;flex:0 0 auto}
/* nowrap の要素は min-width:0 を明示しないと縮まず、親を横に押し広げて
   ツリー全体に横スクロールを生む。flex の既定 min-width:auto を打ち消す。 */
.gitem .gd{color:var(--faint);font-size:.73rem;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap;flex:1 1 0;min-width:0}
.glist,.grouped,.kids,.dnode,.tree{min-width:0}

/* ---- 標識 ---- */
.pill{display:inline-block;padding:.02rem .42rem;border-radius:2px;font-size:.68rem;
  border:1px solid var(--line);background:var(--panel2);color:var(--muted);
  white-space:nowrap;font-weight:600;line-height:1.65;font-family:var(--mono);
  letter-spacing:.03em}
.pill.plain{background:transparent;color:var(--faint)}
.pill.ok{background:var(--ok-soft);color:var(--ok);border-color:transparent}
.pill.warn{background:var(--warn-soft);color:var(--warn);border-color:transparent}
.pill.mid{background:var(--mid-soft);color:var(--mid);border-color:transparent}

/* ---- 検出 ---- */
.issue{padding:.95rem 1.05rem;border-bottom:1px solid var(--line2);
  position:relative}
.issue::before{content:"";position:absolute;left:0;top:0;bottom:0;width:2px;
  background:var(--line)}
.issue.sev-high::before{background:var(--warn)}
.issue.sev-mid::before{background:var(--mid)}
.issue:last-child{border-bottom:none}
.issue-h{display:flex;gap:.5rem;align-items:baseline;flex-wrap:wrap}
.issue-t{font-weight:650;font-size:.93rem;font-family:var(--serif);
  letter-spacing:.02em}
.issue-d{color:var(--muted);font-size:.82rem;margin-top:.2rem;max-width:84ch}
.issue details{margin-top:.45rem}
.issue summary{cursor:pointer;font-size:.75rem;color:var(--accent);
  list-style:none;font-family:var(--mono);letter-spacing:.03em}
.issue summary::-webkit-details-marker{display:none}
.issue summary::before{content:"▸ ";font-size:.68rem}
.issue details[open] summary::before{content:"▾ "}
.issue ul{margin:.4rem 0 0;padding-left:1.1rem;columns:2;column-gap:1.4rem}
@media (max-width:820px){.issue ul{columns:1}}
.issue li{font-family:var(--mono);font-size:.73rem;color:var(--muted);
  word-break:break-all;line-height:1.65;break-inside:avoid}

/* ---- 表 ---- */
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:.81rem}
th,td{text-align:left;padding:.48rem .85rem;border-bottom:1px solid var(--line2);
  vertical-align:top}
th{font-weight:600;color:var(--muted);font-size:.71rem;white-space:nowrap;
  position:sticky;top:0;background:var(--panel2);font-family:var(--mono);
  letter-spacing:.06em;text-transform:uppercase}
tbody tr{transition:background .14s}
tbody tr:hover{background:var(--line2)}
tbody tr:last-child td{border-bottom:none}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;
  font-family:var(--mono)}
code{font-family:var(--mono);font-size:.86em}

/* ---- トリガー ---- */
.trig-row{display:grid;grid-template-columns:minmax(148px,190px) minmax(0,1fr);
  border-bottom:1px solid var(--line2)}
.trig-row:last-child{border-bottom:none}
.trig-ev{padding:.75rem 1.05rem;border-right:1px solid var(--line2);
  background:var(--panel2)}
.trig-ev .name{font-weight:650;font-size:.81rem;word-break:break-all;
  font-family:var(--mono)}
.trig-ev .cnt{font-size:.7rem;color:var(--faint);font-family:var(--mono)}
.trig-list{padding:.42rem .3rem}
.trig-item{display:grid;grid-template-columns:auto minmax(0,1fr);gap:.55rem;
  padding:.3rem .58rem;border-radius:3px;transition:background .14s}
.trig-item:hover{background:var(--line2)}
.trig-cmd{font-family:var(--mono);font-size:.75rem;word-break:break-all;
  line-height:1.6}
.trig-src{color:var(--faint);font-size:.7rem;font-family:var(--mono)}

/* ---- 容量 ---- */
.bars{padding:.9rem 1.05rem}
.bar-row{margin-bottom:.85rem}
.bar-row:last-child{margin-bottom:0}
.bar-top{display:flex;justify-content:space-between;gap:1rem;font-size:.79rem;
  margin-bottom:.26rem}
.bar-top .sz{font-variant-numeric:tabular-nums;color:var(--muted);
  white-space:nowrap;font-family:var(--mono)}
.track{height:9px;background:var(--line2);border-radius:1px;overflow:hidden;
  display:flex;border:1px solid var(--line)}
.seg{height:100%;transition:filter .15s}
.seg:hover{filter:brightness(1.15)}
.legend{margin-top:.28rem;font-size:.7rem;color:var(--faint);display:flex;
  flex-wrap:wrap;gap:.1rem .7rem;font-family:var(--mono)}

/* ---- 本文ビューア ---- */
@keyframes slidein{from{transform:translateX(28px);opacity:0}to{transform:none;opacity:1}}
@keyframes fadein{from{opacity:0}to{opacity:1}}
.scrim{position:fixed;inset:0;background:rgba(12,10,6,.42);z-index:70;
  backdrop-filter:blur(2px);animation:fadein .2s both}
.viewer{position:fixed;top:0;right:0;bottom:0;width:min(780px,95vw);z-index:71;
  background:var(--panel);border-left:1px solid var(--line);display:flex;
  flex-direction:column;box-shadow:-20px 0 60px -30px rgba(0,0,0,.7);
  animation:slidein .26s cubic-bezier(.22,.7,.3,1) both}
.viewer-h{padding:.9rem 1.05rem;border-bottom:1px solid var(--line);display:flex;
  gap:.75rem;align-items:flex-start;background:var(--panel2)}
.viewer-h .vt{flex:1 1 auto;min-width:0}
.viewer-h .vp{font-family:var(--mono);font-size:.79rem;font-weight:650;
  word-break:break-all;letter-spacing:.01em}
.viewer-h .vm{font-size:.72rem;color:var(--muted);margin-top:.3rem;
  display:flex;gap:.32rem;flex-wrap:wrap;align-items:center}
.vclose{background:var(--panel);border:1px solid var(--line);border-radius:2px;
  padding:.28rem .7rem;cursor:pointer;font-size:.74rem;color:var(--muted);
  font-family:var(--mono);flex:0 0 auto;letter-spacing:.04em;transition:all .15s}
.vclose:hover{border-color:var(--warn);color:var(--warn);background:var(--warn-soft)}
.vbody{margin:0;padding:1.1rem 1.2rem 2rem;overflow:auto;flex:1 1 auto;
  font-family:var(--mono);font-size:.775rem;line-height:1.78;
  white-space:pre-wrap;word-break:break-word;tab-size:2;background:var(--panel)}
/* 簡易な構文の着色 */
.vbody .h{color:var(--accent);font-weight:700}
.vbody .k{color:var(--mid)}
.vbody .s{color:var(--ok)}
.vbody .c{color:var(--faint);font-style:italic}
.vbody .em{color:var(--warn);font-weight:700}
.vnote{padding:.7rem 1.05rem;border-top:1px solid var(--line);font-size:.74rem;
  color:var(--muted);background:var(--panel2)}

.fold{margin-top:1rem}
.fold > summary{cursor:pointer;font-size:.84rem;color:var(--accent);font-weight:600;
  list-style:none;padding:.55rem 0;font-family:var(--mono);letter-spacing:.03em}
.fold > summary::-webkit-details-marker{display:none}
.fold > summary::before{content:"▸ "}
.fold[open] > summary::before{content:"▾ "}

/* ---- 取り扱い注意の帯 ---- */
.notice{border:1px solid var(--warn);border-left-width:3px;border-radius:3px;
  background:var(--warn-soft);padding:.75rem 1rem;margin:0 0 2rem;
  display:flex;gap:.7rem;align-items:flex-start}
.notice .ni{flex:0 0 auto;font-family:var(--mono);font-size:.66rem;font-weight:700;
  letter-spacing:.12em;color:var(--warn);border:1px solid var(--warn);
  border-radius:2px;padding:.1rem .4rem;margin-top:.15rem}
.notice .nb{flex:1 1 auto;min-width:0;font-size:.83rem;color:var(--ink)}
.notice .nb b{color:var(--warn)}
.notice .nl{font-family:var(--mono);font-size:.74rem;color:var(--muted);
  margin-top:.3rem;line-height:1.6;word-break:break-all}

.empty{padding:1.4rem 1rem;color:var(--muted);font-size:.83rem;text-align:center}
footer{border-top:1px solid var(--line);padding-top:1.3rem;color:var(--faint);
  font-size:.76rem;max-width:80ch}
footer p{margin:.35rem 0}
.toggle{position:fixed;right:1.1rem;bottom:1.1rem;background:var(--panel);
  border:1px solid var(--line);border-radius:2px;padding:.42rem .85rem;
  font-size:.73rem;cursor:pointer;color:var(--muted);box-shadow:var(--shadow);
  font-family:var(--mono);letter-spacing:.06em;z-index:50;transition:all .15s}
.toggle:hover{border-color:var(--accent);color:var(--accent)}

/* 狭い画面。L7 まで潜るツリーは、1段あたりの字下げを詰めないと収まらない。 */
@media (max-width:640px){
  .wrap{padding:2rem .75rem 4rem}
  .kids{margin-left:.2rem;padding-left:.5rem}
  .glist{margin-left:.2rem;padding-left:.5rem}
  .tree{padding:.7rem .6rem 1rem}
  .lede{padding-left:0}
  .sec-h{gap:.5rem}
  .viewer{width:100vw;border-left:0}
  .issue ul{columns:1}
  .trig-row{grid-template-columns:minmax(0,1fr)}
  .trig-list,.trig-ev{min-width:0}
  .trig-item{grid-template-columns:minmax(0,1fr)}
  .pill{white-space:normal;word-break:break-all}
  .gitem{flex-wrap:wrap}
  .gitem .gn{white-space:normal;word-break:break-all}
  .gitem .gd{flex:1 1 100%}
  .trig-ev{border-right:0;border-bottom:1px solid var(--line2)}
  .dname,.fname{font-size:.79rem}
  .decl{font-size:.75rem}
}
"""

PALETTE = ["#1c4f63", "#3a7387", "#5d94a3", "#8a6410", "#a83a17", "#2f6b4f",
           "#4a6b7c", "#8a5f4a", "#6b7a5a", "#6a635a"]


def _e(s: object) -> str:
    return html.escape(str(s), quote=True)


def _human(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    v = float(n)
    for unit in ("KB", "MB", "GB", "TB"):
        v /= 1024.0
        if v < 1024 or unit == "TB":
            return f"{v:.1f} {unit}"
    return f"{v:.1f} TB"


class Renderer:
    def __init__(self, result: ScanResult, redact: bool = False):
        self.r = result
        self.redact = redact
        self._alias: dict[str, str] = {}
        self._secrets: list[str] = []
        if redact:
            self._build_alias_table()

    def _build_alias_table(self) -> None:
        """伏字にすべき語を、描画の前にまとめて登録する。

        パスの伏字だけでは足りない。見出しやスキルの説明文といった
        ファイルの中身にもディレクトリ名と同じ固有名詞が現れるため、
        先に全パスから語彙を作り、本文にも同じ置換をかける。
        """
        paths: list[Path] = [c.path for c in self.r.configs]
        paths += [Path(r.root) for r in self.r.repos]
        paths += [s.path for s in self.r.stores]
        paths += list(self.r.roots)

        def walk(nodes):
            for n in nodes:
                paths.append(n.path)
                walk(n.children)
        walk(self.r.tree)

        def register(seg: str) -> None:
            if (len(seg) >= 3 and seg not in self._KEEP
                    and not seg.endswith((".md", ".json", ".toml", ".mdc"))):
                self._mask(seg)

        for p in paths:
            for seg in Path(p).parts:
                seg = seg.strip("/")
                register(seg)
                # 「05_案件名」のような連番付きフォルダは、本文では連番なしの
                # 「案件名」で呼ばれる。接頭の連番を落とした形も語彙に入れる。
                bare = re.sub(r"^\d+[_\-.]\s*", "", seg)
                if bare != seg:
                    register(bare)
        # 長い語から先に置換しないと、短い語が長い語の一部を壊す
        self._secrets = sorted(self._alias, key=len, reverse=True)

    def _scrub(self, s: str) -> str:
        """登録済みの固有名詞を本文からも消す。"""
        for token in self._secrets:
            if token in s:
                s = s.replace(token, self._alias[token])
        return s

    # -- パス表記 ---------------------------------------------------------
    _KEEP = {
        "~", "", ".claude", ".codex", ".gemini", ".cursor", ".sena", ".github",
        "skills", "agents", "rules", "dev", "Deliverables", "engagements",
        "graphify-out", "research", "hooks", "plugins", "projects",
    }

    def path(self, p: Path | str) -> str:
        # Windows のパスは区切りが \ になる。正規化せずに / で分割すると
        # パス全体が1個の区切りになり、末尾が .json なら「ファイル名だから
        # 残す」と判定されて丸ごと漏れる。先に区切りをそろえる。
        s = str(p).replace("\\", "/")
        home = str(self.r.home).replace("\\", "/")
        if s.startswith(home):
            s = "~" + s[len(home):]
        if not self.redact:
            return s
        out = []
        for seg in s.split("/"):
            if seg in self._KEEP or seg.endswith((".md", ".json", ".toml", ".mdc")):
                out.append(seg)
            else:
                out.append(self._mask(seg))
        return "/".join(out)

    def _mask(self, seg: str) -> str:
        if seg not in self._alias:
            self._alias[seg] = f"«{hashlib.sha256(seg.encode()).hexdigest()[:4]}»"
        return self._alias[seg]

    # 本文に紛れ込む絶対パス。Windows の `C:\Users\...` も拾えるようにする。
    _PATH_RE = re.compile(
        r"(?:~|/Users/[^/\s\"';:,]+|/home/[^/\s\"';:,]+"
        r"|[A-Za-z]:[\\/]Users[\\/][^\\/\s\"';:,]+)"
        r"(?:[\\/][^\s\"';,()\[\]]+)*")
    # Claude Code は ~/.claude/projects/ の下に、絶対パスの区切りをハイフンに
    # 置き換えた名前でディレクトリを作る。名前自体がパスなので伏字対象になる。
    _DASH_PATH_RE = re.compile(r"-(?:Users|home)-[^\s\"'/]+")

    def text(self, s: str) -> str:
        s = str(s)
        if not self.redact:
            return s.replace(str(self.r.home), "~")
        s = self._PATH_RE.sub(lambda m: self.path(m.group(0)), s)
        # 先頭の Users / home だけ残し、以降は利用者名を含めてすべて伏せる。
        s = self._DASH_PATH_RE.sub(
            lambda m: "-".join(seg if i < 1 else self._mask(seg)
                               for i, seg in enumerate(m.group(0).lstrip("-").split("-"))),
            s)
        user = self.r.home.name
        if user:
            s = re.sub(rf"\b{re.escape(user)}\b", self._mask(user), s)
        return self._scrub(s)

    # -- サマリ -----------------------------------------------------------
    def _cards(self) -> str:
        r = self.r
        instr = [c for c in r.configs if c.kind in ("instructions", "rules")]
        untracked = sum(1 for c in r.configs if c.git_state == "untracked")
        high = sum(1 for i in r.issues if i.severity == "high")
        items = [
            (len(r.configs), "設定ファイル<br>総数", False),
            (len(instr), "指示ファイル<br>とルール", False),
            (len(r.repos), "git<br>リポジトリ", False),
            (untracked, "git 未追跡の<br>設定", untracked > 0),
            (len(r.triggers), "自動発火<br>トリガー", False),
            (len(r.issues), f"検出した散らかり<br>うち要対応 {high}", high > 0),
        ]
        return '<div class="cards">' + "".join(
            f'<div class="card rz{" alert" if a else ""}">'
            f'<div class="n">{_e(n)}</div><div class="l">{l}</div></div>'
            for n, l, a in items) + "</div>"

    # -- 階層ツリー -------------------------------------------------------
    # 段ごとの罫線の色。深さが変わったことを目で追えるようにするための手掛かり。
    RAILS = ["#3a7387", "#7a8f6a", "#a08050", "#8a7196", "#5d94a3", "#9a7060"]

    def _open_attr(self, c) -> str:
        """本文を持つファイルだけクリックできるようにする。"""
        if not c.content:
            return ""
        return f' onclick="openFile(\'{c.uid}\')" title="クリックで中身を表示"'

    def _file_row(self, c) -> str:
        badges = [f'<span class="pill plain">{_e(KIND_LABEL.get(c.kind, c.kind))}</span>',
                  f'<span class="pill">{_e(SCOPE_LABEL.get(c.scope, c.scope))}</span>']
        gl, gc = GIT_LABEL.get(c.git_state, ("?", "plain"))
        badges.append(f'<span class="pill {gc}">{_e(gl)}</span>')
        if c.lines > 200:
            badges.append(f'<span class="pill warn">{c.lines}行</span>')

        decl = ""
        if c.declares:
            joined = " / ".join(self.text(d) for d in c.declares[:8])
            if len(c.declares) > 8:
                joined += f" ほか{len(c.declares) - 8}項目"
            decl = f'<div class="decl"><b>規定</b> {_e(joined)}</div>'
        st = ""
        if c.stats:
            st = ('<div class="st">'
                  + " · ".join(f"{_e(k)} {_e(v)}" for k, v in c.stats.items())
                  + "</div>")
        tag = "button" if c.content else "div"
        # 絞り込みは DOM 属性だけで完結させる。検索のために本文を再走査しない。
        haystack = " ".join([c.name, c.label, str(c.path.parent.name),
                             *(c.declares[:4])]).lower()
        return (f'<{tag} class="f" data-k="{_e(c.kind)}" data-g="{_e(c.git_state)}"'
                f' data-q="{_e(self.text(haystack))}"{self._open_attr(c)}>'
                f'<span class="fic">{"◧" if c.content else "·"}</span>'
                f'<span class="f-body"><span class="f-head">'
                f'<span class="fname">{_e(c.name)}</span>{"".join(badges)}</span>'
                f"{decl}{st}</span></{tag}>")

    def _group_row(self, kind: str, items: list) -> str:
        label = KIND_LABEL.get(kind, kind)
        lis = []
        for c in sorted(items, key=lambda c: c.label or c.name):
            d = self.text(c.declares[0]) if c.declares else ""
            extra = " · ".join(f"{k} {v}" for k, v in c.stats.items())
            tag = "button" if c.content else "div"
            hay = f"{c.label or c.name} {d}".lower()
            lis.append(f'<{tag} class="gitem" data-k="{_e(c.kind)}"'
                       f' data-g="{_e(c.git_state)}" data-q="{_e(self.text(hay))}"'
                       f'{self._open_attr(c)}>'
                       f'<span class="gn">{_e(c.label or c.name)}</span>'
                       f'<span class="gd">{_e(d[:110])}'
                       f'{" · " + _e(extra) if extra else ""}</span></{tag}>')
        return (f'<details class="grouped"><summary>'
                f'<span class="tw">▸</span>{_e(label)} {len(items)} 件'
                f'<span class="pill plain">展開</span></summary>'
                f'<div class="glist">{"".join(lis)}</div></details>')

    def _node(self, node: TreeNode, top: bool = False) -> str:
        name = self.path(node.path) if node.depth == 0 else (
            self._mask(node.path.name)
            if (self.redact and node.path.name not in self._KEEP) else node.path.name)

        singles, groups = [], {}
        for c in node.configs:
            (groups.setdefault(c.kind, []) if c.kind in ("skill", "agent")
             else singles).append(c)

        # skills/ の下はスキル1件につきディレクトリが1つ切られる。そのまま描くと
        # 1スキルあたり2段ずつ積み上がるので、葉がスキルだけの子はここで畳む。
        leaves, rest = self._split_skill_leaves(node.children)

        inner = []
        if singles:
            inner.extend(self._file_row(c) for c in singles)
        for kind, items in groups.items():
            inner.append(self._group_row(kind, items) if len(items) > 3
                         else "".join(self._file_row(c) for c in items))
        if leaves:
            inner.append(self._group_row("skill", leaves))
        inner.extend(self._node(ch) for ch in rest)

        nfile = len(singles) + sum(len(v) for v in groups.values()) + len(leaves)
        ndir = len(rest)
        counts = []
        if nfile:
            counts.append(f"{nfile} ファイル")
        if ndir:
            counts.append(f"{ndir} フォルダ")
        repo = ""
        if node.is_repo:
            repo = (f'<span class="pill ok">{_e(node.repo_label)}</span>'
                    f'<span class="repo">{_e(self.text(node.repo_info))}</span>')

        leaf = "" if inner else " leaf"
        rail = self.RAILS[node.depth % len(self.RAILS)]
        return (
            f'<details class="dnode{leaf}" data-depth="{node.depth}"'
            f'{" open" if top or node.depth < 2 else ""}>'
            f'<summary class="{"is-repo" if node.is_repo else ""}">'
            f'<span class="tw">▸</span>'
            f'<span class="lv">L{node.depth}</span>'
            f'<span class="dname">{_e(name)}/</span>'
            f'{repo}<span class="dcount">{_e(" · ".join(counts))}</span></summary>'
            f'<div class="kids" style="--rail:{rail}">{"".join(inner)}</div>'
            f"</details>")

    @staticmethod
    def _split_skill_leaves(children: list[TreeNode]) -> tuple[list, list[TreeNode]]:
        leaves, rest = [], []
        for ch in children:
            if (not ch.children and len(ch.configs) == 1
                    and ch.configs[0].kind == "skill"):
                leaves.append(ch.configs[0])
            else:
                rest.append(ch)
        return (leaves, rest) if len(leaves) > 3 else ([], children)

    def _tree(self) -> str:
        if not self.r.tree:
            return '<div class="panel"><div class="empty">設定ファイルが見つからなかった</div></div>'
        body = "".join(self._node(n, top=True) for n in self.r.tree)
        clickable = sum(1 for c in self.r.configs if c.content)
        hint = (f"◧ 付きの {clickable} ファイルはクリックで中身を表示"
                if clickable else "共有モードのため本文は埋め込んでいない")
        chips = "".join(
            f'<button class="tbtn chip" data-f="{k}" onclick="setFilter(\'{k}\')">'
            f"{_e(lab)}</button>"
            for k, lab in (("all", "すべて"), ("instructions", "指示"),
                           ("settings", "設定"), ("skill", "スキル"),
                           ("agent", "エージェント"), ("untracked", "未追跡")))
        return ('<div class="panel"><div class="panel-h">ディレクトリ階層と設定ファイル'
                '<span class="sub">L の数字が階層の深さ。深い階層が浅い階層を上書きする'
                '</span></div>'
                '<div class="treebar">'
                '<button class="tbtn" onclick="treeAll(true)">全展開</button>'
                '<button class="tbtn" onclick="treeAll(false)">全収納</button>'
                '<button class="tbtn" onclick="treeDepth(2)">2段</button>'
                '<button class="tbtn" onclick="treeDepth(3)">3段</button>'
                '<span class="tsep"></span>'
                f"{chips}"
                '<input class="tsearch" id="q" type="search" placeholder="名前・規定内容で絞り込み"'
                ' oninput="applyFilter()">'
                f'<span class="hint" id="fhint">{_e(hint)}</span></div>'
                f'<div class="tree">{body}</div></div>')

    # -- 散らかりの検出 ---------------------------------------------------
    def _issues(self) -> str:
        if not self.r.issues:
            return '<div class="panel"><div class="empty">散らかりの兆候は見つからなかった</div></div>'
        rows = []
        for i in self.r.issues:
            lab, cls = SEV.get(i.severity, ("参考", "plain"))
            lis = "".join(f"<li>{_e(self.path(p))}</li>" for p in i.paths[:40])
            more = (f"<li>ほか {len(i.paths) - 40} 件</li>" if len(i.paths) > 40 else "")
            rows.append(
                f'<div class="issue sev-{i.severity}"><div class="issue-h">'
                f'<span class="pill {cls}">{_e(lab)}</span>'
                f'<span class="issue-t">{_e(i.title)}</span>'
                f'<span class="pill plain">{len(i.paths)} 件</span></div>'
                f'<div class="issue-d">{_e(self.text(i.detail))}</div>'
                f"<details><summary>対象ファイルを見る</summary>"
                f"<ul>{lis}{more}</ul></details></div>")
        return ('<div class="panel"><div class="panel-h">検出した散らかり'
                '<span class="sub">断定ではなく確認対象。上から順に効く</span></div>'
                + "".join(rows) + "</div>")

    # -- git 階層 ---------------------------------------------------------
    def _repos(self) -> str:
        if not self.r.repos:
            return ""
        rows = []
        for r in sorted(self.r.repos, key=lambda r: str(r.root)):
            cfg = sum(1 for c in self.r.configs if c.repo_root == r.root)
            state = []
            if r.dirty:
                state.append(f'<span class="pill mid">未コミット {r.dirty}</span>')
            if r.untracked:
                state.append(f'<span class="pill warn">未追跡 {r.untracked}</span>')
            if not r.remote:
                state.append('<span class="pill plain">リモートなし</span>')
            if not state:
                state.append('<span class="pill ok">クリーン</span>')
            nest = (f'<span class="pill plain">{_e(r.depth_label)}</span>'
                    if r.parent_repo or r.is_submodule else "")
            rows.append(
                f"<tr><td><code>{_e(self.path(r.root))}</code> {nest}</td>"
                f"<td><code>{_e(r.branch)}</code></td>"
                f'<td>{"".join(state)}</td>'
                f'<td class="num">{cfg}</td>'
                f'<td class="num">{_e(r.last_commit or "–")}</td></tr>')
        return ('<div class="panel"><div class="panel-h">git リポジトリ'
                f'<span class="sub">{len(self.r.repos)} 件</span></div>'
                '<div class="scroll"><table><thead><tr><th>ルート</th><th>ブランチ</th>'
                '<th>状態</th><th>設定ファイル</th><th>最終コミット</th></tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table></div></div>')

    # -- 以下は補助セクション ---------------------------------------------
    def _triggers(self) -> str:
        if not self.r.triggers:
            return '<div class="panel"><div class="empty">自動発火するものはなかった</div></div>'
        groups: dict[str, list] = {}
        for t in self.r.triggers:
            groups.setdefault(t.event, []).append(t)
        rows = []
        for event, items in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            lis = "".join(
                f'<div class="trig-item">'
                + (f'<span class="pill">{_e(self.text(t.matcher))}</span>' if t.matcher
                   else '<span class="pill plain">全対象</span>')
                + f'<div><div class="trig-cmd">{_e(self.text(t.short_command))}</div>'
                  f'<div class="trig-src">{_e(self.path(t.source))}</div></div></div>'
                for t in items)
            rows.append(f'<div class="trig-row"><div class="trig-ev">'
                        f'<div class="name">{_e(event)}</div>'
                        f'<div class="cnt">{len(items)} 件</div></div>'
                        f'<div class="trig-list">{lis}</div></div>')
        return ('<div class="panel"><div class="panel-h">発火条件と実行内容'
                '<span class="sub">左が発火のきっかけ、右が実際に走るもの</span></div>'
                + "".join(rows) + "</div>")

    def _mcp(self) -> str:
        if not self.r.mcp_servers:
            return ""
        seen, rows = set(), []
        for m in sorted(self.r.mcp_servers, key=lambda m: (m.tool, m.name)):
            key = (m.tool, m.name, m.detail)
            if key in seen:
                continue
            seen.add(key)
            rows.append(f"<tr><td><b>{_e(m.name)}</b></td><td>{_e(m.tool)}</td>"
                        f'<td><span class="pill plain">{_e(m.transport)}</span></td>'
                        f'<td><code>{_e(self.text(m.detail)[:150])}</code></td></tr>')
        return ('<div class="panel"><div class="panel-h">MCP サーバ'
                f'<span class="sub">重複を除いて {len(rows)} 件</span></div>'
                '<div class="scroll"><table><thead><tr><th>名前</th><th>ツール</th>'
                '<th>方式</th><th>接続先</th></tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table></div></div>')

    def _stores(self) -> str:
        if not self.r.stores:
            return ""
        rows = "".join(
            f"<tr><td><code>{_e(self.path(s.path))}</code></td>"
            f'<td><span class="pill plain">{_e(STORE_LABEL.get(s.kind, s.kind))}</span></td>'
            f'<td class="num">{_human(s.size)}</td><td class="num">{s.file_count:,}</td>'
            f'<td class="num">'
            f'{datetime.fromtimestamp(s.mtime).strftime("%Y-%m-%d") if s.mtime else "–"}'
            f"</td></tr>"
            for s in sorted(self.r.stores, key=lambda s: -s.size))
        return ('<div class="panel"><div class="panel-h">成果物の格納先</div>'
                '<div class="scroll"><table><thead><tr><th>パス</th><th>種別</th>'
                '<th>容量</th><th>ファイル数</th><th>更新</th></tr></thead>'
                f'<tbody>{rows}</tbody></table></div></div>')

    def _disk(self) -> str:
        if not self.r.disk:
            return ""
        top = max(d.size for d in self.r.disk) or 1
        rows = []
        for d in self.r.disk:
            segs, legend = [], []
            for i, c in enumerate(d.children[:8]):
                if c.size <= 0:
                    continue
                color = PALETTE[i % len(PALETTE)]
                segs.append(f'<div class="seg" style="width:{100*c.size/max(d.size,1):.2f}%;'
                            f'background:{color}"></div>')
                legend.append(f'<span><b style="color:{color}">■</b> '
                              f"{_e(self.text(c.label))} {_human(c.size)}</span>")
            rows.append(
                f'<div class="bar-row"><div class="bar-top"><span><b>{_e(d.label)}</b> '
                f'<code>{_e(self.path(d.path))}</code></span>'
                f'<span class="sz">{_human(d.size)}</span></div>'
                f'<div class="track" style="width:{max(6, int(100*d.size/top))}%">'
                f'{"".join(segs)}</div><div class="legend">{"".join(legend)}</div></div>')
        return ('<div class="panel"><div class="panel-h">ツール別の占有容量'
                f'<span class="sub">合計 {_human(sum(d.size for d in self.r.disk))}</span>'
                f'</div><div class="bars">{"".join(rows)}</div></div>')

    def _notice(self) -> str:
        """伏字なし版にだけ出す取り扱い注意。値は隠さないので、隠さない旨を伝える。"""
        if self.redact:
            return ""
        hits = [c for c in self.r.configs if c.secrets]
        if not hits:
            return ""
        total = sum(len(c.secrets) for c in hits)
        lines = "".join(
            f"<div class=\"nl\">{_e(self.path(c.path))} — "
            + "、".join(f"{_e(s.kind)}（{c.path.name} {s.line}行目"
                        + (f" / {_e(s.name)}" if s.name else "") + "）"
                        for s in c.secrets[:3])
            + (f" ほか{len(c.secrets) - 3}件" if len(c.secrets) > 3 else "")
            + "</div>"
            for c in hits[:6])
        more = (f'<div class="nl">ほか {len(hits) - 6} ファイル</div>'
                if len(hits) > 6 else "")
        return (
            '<div class="notice"><span class="ni">取扱注意</span><div class="nb">'
            f'このファイルには<b>認証情報が {total} 件</b>、値をそのまま含んでいる。'
            f'手元で点検するためにあえて伏せていない。<b>共有・添付・貼り付けはしないこと。</b>'
            'ほかの人に渡すときは <code>--redact</code> を付けて生成し直す'
            '（共有モードは本文を一切埋め込まない）。'
            f"{lines}{more}</div></div>")

    def _all_nodes(self):
        """ツリーの全ノードを平坦に辿る。最大深度の表示などに使う。"""
        def walk(nodes):
            for n in nodes:
                yield n
                yield from walk(n.children)
        return walk(self.r.tree)

    # -- 本文データ -------------------------------------------------------
    def _file_data(self) -> str:
        """クリックで開くための本文を JSON として埋め込む。

        外部リクエストを禁じているので、本文はページの中に持つしかない。
        script 要素の中に置くため、終了タグとして解釈されうる並びだけ潰す。
        """
        # 共有モードでは本文を持たない。走査側でも読まない設定にしてあるが、
        # 安全側の判断を呼び出し側の作法に委ねない。ここでも必ず落とす。
        if self.redact:
            return '<script id="filedata" type="application/json">{}</script>'
        data = {}
        for c in self.r.configs:
            if not c.content:
                continue
            gl, _gc = GIT_LABEL.get(c.git_state, ("?", ""))
            meta = [KIND_LABEL.get(c.kind, c.kind),
                    SCOPE_LABEL.get(c.scope, c.scope), gl,
                    f"{c.lines}行", _human(c.size)]
            if c.mtime:
                meta.append(datetime.fromtimestamp(c.mtime).strftime("%Y-%m-%d 更新"))
            data[c.uid] = {
                "p": self.path(c.path),
                "m": meta,
                "t": c.truncated,
                "b": c.content,
            }
        blob = json.dumps(data, ensure_ascii=False)
        blob = blob.replace("</", "<\\/").replace(" ", "\\u2028")
        return f'<script id="filedata" type="application/json">{blob}</script>'

    VIEWER_HTML = """
<div class="scrim" id="scrim" hidden onclick="closeFile()"></div>
<aside class="viewer" id="viewer" hidden aria-label="ファイルの中身">
  <div class="viewer-h">
    <div class="vt"><div class="vp" id="v-path"></div>
      <div class="vm" id="v-meta"></div></div>
    <button class="vclose" onclick="closeFile()">閉じる</button>
  </div>
  <pre class="vbody" id="v-body"></pre>
  <div class="vnote" id="v-note" hidden></div>
</aside>"""

    VIEWER_JS = """
var FD = JSON.parse(document.getElementById('filedata').textContent || '{}');
var $ = function(id){ return document.getElementById(id); };

/* 本文の簡易着色。外部ライブラリを持ち込まずに読みやすさだけ上げる。
   Markdown の見出し・強調語、JSON/TOML のキーと文字列、コメント行を拾う。 */
function paint(text, path){
  var esc = text.replace(/[&<>]/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];
  });
  var md = /\\.(md|mdc)$/i.test(path);
  return esc.split('\\n').map(function(line){
    if(md){
      if(/^#{1,6}\\s/.test(line)) return '<span class="h">' + line + '</span>';
      if(/^---\\s*$/.test(line))  return '<span class="c">' + line + '</span>';
      line = line.replace(/\\b(IMPORTANT|NEVER|MUST|ALWAYS|禁止|必ず|絶対)\\b/g,
                          '<span class="em">$1</span>');
      return line.replace(/(`[^`]+`)/g, '<span class="k">$1</span>');
    }
    if(/^\\s*(#|\\/\\/)/.test(line)) return '<span class="c">' + line + '</span>';
    if(/^\\s*\\[.*\\]\\s*$/.test(line)) return '<span class="h">' + line + '</span>';
    line = line.replace(/(&quot;|")([^"&]*)(&quot;|")(\\s*:)/g,
                        '<span class="k">$1$2$3</span>$4');
    return line.replace(/(:\\s*)((&quot;|")[^"&]*(&quot;|"))/g,
                        '$1<span class="s">$2</span>');
  }).join('\\n');
}

function openFile(id){
  var d = FD[id]; if(!d) return;
  $('v-path').textContent = d.p;
  var m = $('v-meta'); m.innerHTML = '';
  d.m.forEach(function(x){
    var s = document.createElement('span');
    s.className = 'pill plain'; s.textContent = x; m.appendChild(s);
  });
  $('v-body').innerHTML = paint(d.b, d.p);
  var n = $('v-note');
  n.hidden = !d.t;
  n.textContent = d.t ? '長いため先頭 80,000 文字までを表示している。' : '';
  $('viewer').hidden = false;
  $('scrim').hidden = false;
  $('v-body').scrollTop = 0;
  $('viewer').querySelector('.vclose').focus();
}
function closeFile(){
  $('viewer').hidden = true;
  $('scrim').hidden = true;
}
function treeAll(open){
  document.querySelectorAll('details.dnode').forEach(function(d){ d.open = open; });
}
function treeDepth(n){
  document.querySelectorAll('details.dnode').forEach(function(d){
    d.open = parseInt(d.getAttribute('data-depth'), 10) < n;
  });
}

/* 絞り込み。一致しない行を隠したうえで、中身が空になった枝ごと畳む。 */
var FKIND = 'all';
function setFilter(k){
  FKIND = k;
  document.querySelectorAll('.chip').forEach(function(b){
    b.classList.toggle('on', b.getAttribute('data-f') === k);
  });
  applyFilter();
}
function applyFilter(){
  var q = ($('q').value || '').trim().toLowerCase();
  var rows = document.querySelectorAll('[data-q]');
  var shown = 0;
  rows.forEach(function(el){
    var okK = FKIND === 'all' ||
      (FKIND === 'untracked' ? el.getAttribute('data-g') === 'untracked'
                             : el.getAttribute('data-k') === FKIND);
    var okQ = !q || el.getAttribute('data-q').indexOf(q) >= 0;
    var on = okK && okQ;
    el.hidden = !on;
    if(on) shown++;
  });
  var active = FKIND !== 'all' || q;
  document.querySelectorAll('details.grouped').forEach(function(d){
    var any = d.querySelector('[data-q]:not([hidden])');
    d.hidden = !any;
    if(active && any) d.open = true;
  });
  document.querySelectorAll('details.dnode').forEach(function(d){
    var any = d.querySelector('[data-q]:not([hidden])');
    d.hidden = active && !any;
    if(active && any) d.open = true;
  });
  $('fhint').textContent = active
    ? shown + ' 件が該当（絞り込み中）'
    : $('fhint').getAttribute('data-base');
  if(!active) treeDepth(2);
}

document.addEventListener('keydown', function(e){
  if(e.key === 'Escape'){ closeFile(); }
  if(e.key === '/' && e.target.tagName !== 'INPUT'){ e.preventDefault(); $('q').focus(); }
});
function toggleTheme(){
  var r = document.documentElement;
  var dark = r.getAttribute('data-theme') === 'dark' ||
    (!r.getAttribute('data-theme') &&
     matchMedia('(prefers-color-scheme:dark)').matches);
  r.setAttribute('data-theme', dark ? 'light' : 'dark');
}
(function(){
  var h = $('fhint'); h.setAttribute('data-base', h.textContent);
  setFilter('all');
  /* 読み込み時に上から順に立ち上げる */
  document.querySelectorAll('.rz').forEach(function(el, i){
    el.style.animationDelay = (0.05 + i * 0.06) + 's';
  });
})();"""

    # -- 全体 -------------------------------------------------------------
    def render(self) -> str:
        r = self.r
        note = (f"<b>共有モード</b>：パスとディレクトリ名 {len(self._secrets)} 語を «…» に"
                "置換済み。ただし設定ファイルの本文から抜き出した見出しや説明文には、"
                "ディレクトリ名と一致しない固有名詞（人名・社名・製品名など）が残りうる。"
                "外部に出す前に本文を一度目視で確認すること。"
                if self.redact else
                "このファイルには実際のパスが含まれる。共有時は <code>--redact</code> を使う。")
        secs = [
            ("01", "設定ファイルの階層",
             "どの階層にどの設定ファイルがあり、それが何を規定しているか。"
             "深い階層のものが浅い階層を上書きするため、同じ名前が複数の段に現れたら"
             "下の段が勝つ。git の追跡状態も併記してある。追跡されていない設定は"
             "その人のマシンにしか効かない。",
             self._tree()),
            ("02", "検出した散らかり",
             "重複・併存・上書き・未追跡・陳腐化の兆候。使い込むほど溜まる種類のもの。",
             self._issues()),
            ("03", "git リポジトリ階層",
             "どこがリポジトリの境界で、設定ファイルが何件属しているか。"
             "入れ子やサブモジュールは設定の見え方に影響する。",
             self._repos()),
            ("04", "自動発火するもの",
             "何をきっかけに勝手に動くか。", self._triggers() + self._mcp()),
        ]
        body = "".join(f'<section class="rz"><div class="sec-h">'
                       f'<span class="idx">{i}</span><h2>{_e(t)}</h2></div>'
                       f'<p class="lede">{_e(l)}</p>{c}</section>'
                       for i, t, l, c in secs)
        extra = ""
        if self.r.stores or self.r.disk:
            extra = ('<details class="fold"><summary>成果物の格納先と容量の内訳</summary>'
                     + self._stores() + self._disk() + "</details>")
        errs = "".join(f"<li>{_e(self.text(e))}</li>" for e in r.errors)
        return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI 設定の階層マップ — {_e(r.scanned_at)}</title>
<style>{CSS}</style></head><body><div class="wrap">
<header class="top">
  <span class="stamp">環境図 / AI-ENV-MAP</span>
  <h1 class="hero-main">AI 設定の階層マップ</h1>
  <p class="hero-sub">どの階層にどの設定ファイルがあり、何を規定しているか</p>
  <p class="meta"><span><b>走査</b> {_e(r.scanned_at)}</span>
    <span><b>起点</b> {_e(self.path(r.home))}</span>
    <span><b>対象</b> {len(r.roots)} ディレクトリ</span>
    <span><b>最大深度</b> L{max((n.depth for n in self._all_nodes()), default=0)}</span></p>
</header>
{self._notice()}
{self._cards()}
{body}
{extra}
<footer>
  <p>{note}</p>
  <p>ネットワーク通信は行っていない。すべてローカルのファイル読み取りのみ。</p>
  <details><summary>走査ログ</summary><ul>{errs}</ul></details>
</footer>
</div>
{self.VIEWER_HTML}
<button class="toggle" onclick="toggleTheme()">表示切替</button>
{self._file_data()}
<script>{self.VIEWER_JS}</script>
</body></html>"""


def render(result: ScanResult, redact: bool = False) -> str:
    return Renderer(result, redact=redact).render()
