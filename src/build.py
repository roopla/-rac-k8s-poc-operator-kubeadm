#!/usr/bin/env python3
"""Build the learning guide as HTML from the section Markdown files.

Writes:
  out/index.html          full document for GitHub Pages (with a PDF link)
  out/artifact.html       the same page without the document wrapper, for the Artifact viewer
  out/print.html          the same page in print layout, used to make the PDF
"""
import glob
import html
import os
import re

import markdown
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, TextLexer

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

files = sorted(glob.glob(os.path.join(HERE, "[0-9][0-9]-*.md")))
src = "\n\n".join(open(f, encoding="utf-8").read().strip() for f in files)

# ---------------------------------------------------------------- code blocks -> placeholders
blocks = []
FENCE = re.compile(r"^```([a-zA-Z0-9_+-]*)\n(.*?)^```\s*$", re.M | re.S)


def where_class(label):
    l = label.lower()
    if "powershell" in l or "git bash" in l:
        return "win"
    if "racnode" in l:
        return "pod"
    return "node"


def code_html(lang, code):
    label = ""
    lines = code.split("\n")
    if lang in ("bash", "powershell") and lines and lines[0].startswith("# "):
        label = lines[0][2:].strip()
        code = "\n".join(lines[1:])
    code = code.rstrip("\n")
    try:
        lexer = get_lexer_by_name({"powershell": "powershell", "bash": "bash", "python": "python"}.get(lang, lang or "text"))
    except Exception:
        lexer = TextLexer()
    body = highlight(code, lexer, HtmlFormatter(nowrap=True))
    head = ""
    if label:
        main, _, note = label.partition("(")
        note = note.strip()
        if note.endswith(")"): note = note[:-1]
        i = note.find("connect")
        conn = [note[i:].strip()] if i >= 0 else []
        rest = note[:i].strip().rstrip(";").strip() if i >= 0 else note.strip()
        note = ("(" + rest + ")") if rest else ""
        head = (f'<div class="cmd-head"><span class="where {where_class(label)}">{html.escape(main.strip())}</span>'
                f'<span class="where-note">{html.escape(note)}</span></div>')
        if conn:
            text = "; ".join(conn)
            text = re.sub(r"^connect:\s*", "", text)
            CMD = re.compile(r"(ssh -p \d+ root@127\.0\.0\.1|kubectl -n rac exec -it racnode\d-0 -- bash)")
            out, pos = [], 0
            for m in CMD.finditer(text):
                out.append(html.escape(text[pos:m.start()]))
                c = html.escape(m.group(1))
                out.append(f'<span class="conn-cmd"><code>{c}</code><button class="copy-mini" type="button" data-copy="{c}" aria-label="Copy {c}">Copy</button></span>')
                pos = m.end()
            out.append(html.escape(text[pos:]))
            head += f'<div class="connect"><span class="connect-lbl">Connect first</span>{"".join(out)}</div>' 
    else:
        head = f'<div class="cmd-head"><span class="where file">{html.escape(lang or "text")}</span><span class="where-note"></span></div>'
    if lang == "text":
        return (f'<div class="cmd out"><div class="cmd-head"><span class="where outl">Output</span><span class="where-note">what this lab printed; nothing to run</span></div>'
                f'<pre><code>{html.escape(code)}</code></pre></div>')
    return (f'<div class="cmd">{head}<button class="copy" type="button" aria-label="Copy commands">Copy</button>'
            f'<pre><code>{body}</code></pre></div>')


def fence_sub(m):
    blocks.append(code_html(m.group(1), m.group(2)))
    return f"\n\n@@CODE{len(blocks) - 1}@@\n\n"


src = FENCE.sub(fence_sub, src)

# ---------------------------------------------------------------- diagrams
ARCH = """<figure class="diagram"><svg viewBox="0 0 760 516" role="img" aria-label="Two RAC pods share the ASM disks and talk over two private networks">
<text class="d-title" x="24" y="30">Two RAC pods share the ASM disks and talk over two private networks</text>
<rect class="d-box" x="24" y="48" width="712" height="48" rx="8"/>
<text class="d-name" x="40" y="70">Windows PC · VirtualBox 7 · 64 GB, 8 threads</text>
<text class="d-quiet" x="40" y="87">SSH 2210–2212 and NodePorts 30200–30204 reach the lab through NAT port forwards</text>
<g class="d-line"><line x1="24" y1="124" x2="736" y2="124"/><line x1="380" y1="96" x2="380" y2="124"/><line x1="100" y1="124" x2="100" y2="148"/><line x1="304" y1="124" x2="304" y2="148"/><line x1="616" y1="124" x2="616" y2="148"/></g>
<text class="d-quiet" x="392" y="117">k8s-public 10.0.1.0/24 · NAT Network</text>
<rect class="d-box" x="24" y="148" width="152" height="104" rx="8"/>
<text class="d-name" x="40" y="172">controlplane</text>
<text class="d-quiet" x="40" y="190">10.0.1.10 · 4 GB</text>
<text class="d-text" x="40" y="206">API server, etcd</text>
<text class="d-text" x="40" y="222">CoreDNS resolves</text>
<text class="d-text" x="40" y="238">SCAN and VIP names</text>
<rect class="d-box" x="192" y="148" width="224" height="248" rx="8"/>
<text class="d-name" x="208" y="172">worker1 · 10.0.1.11</text>
<text class="d-quiet" x="208" y="190">4 vCPU · 22 GB · 2048 hugepages</text>
<rect class="d-pod" x="208" y="204" width="192" height="136" rx="8"/>
<text class="d-name" x="224" y="228">racnode1-0 (pod)</text>
<text class="d-text" x="224" y="244">eth0 public · Flannel</text>
<text class="d-text" x="224" y="260">eth1 10.0.11.141 · Multus</text>
<text class="d-text" x="224" y="276">eth2 10.0.12.141 · Multus</text>
<text class="d-text" x="224" y="292">/u01 hostPath · homes</text>
<text class="d-text" x="224" y="308">asm-disk1/2 · block PVCs</text>
<text class="d-text" x="224" y="324">Grid · ASM · ORCLCDB1</text>
<text class="d-quiet" x="208" y="364">enp0s8, enp0s9 promiscuous</text>
<text class="d-quiet" x="208" y="380">/scratch 80 GB holds /u01</text>
<rect class="d-box" x="496" y="148" width="240" height="248" rx="8"/>
<text class="d-name" x="512" y="172">worker2 · 10.0.1.12</text>
<text class="d-quiet" x="512" y="190">4 vCPU · 22 GB · 2048 hugepages</text>
<rect class="d-pod" x="512" y="204" width="208" height="136" rx="8"/>
<text class="d-name" x="528" y="228">racnode2-0 (pod)</text>
<text class="d-text" x="528" y="244">eth0 public · Flannel</text>
<text class="d-text" x="528" y="260">eth1 10.0.11.142 · Multus</text>
<text class="d-text" x="528" y="276">eth2 10.0.12.142 · Multus</text>
<text class="d-text" x="528" y="292">/u01 hostPath · homes</text>
<text class="d-text" x="528" y="308">asm-disk1/2 · block PVCs</text>
<text class="d-text" x="528" y="324">Grid · ASM · ORCLCDB2</text>
<text class="d-quiet" x="512" y="364">enp0s8, enp0s9 promiscuous</text>
<text class="d-quiet" x="512" y="380">/scratch 80 GB holds /u01</text>
<g class="d-line"><line x1="400" y1="256" x2="512" y2="256"/><line x1="400" y1="272" x2="512" y2="272"/><line x1="304" y1="396" x2="304" y2="436"/><line x1="616" y1="396" x2="616" y2="436"/></g>
<text class="d-small" x="456" y="250" text-anchor="middle">rac-priv1</text>
<text class="d-small" x="456" y="287" text-anchor="middle">rac-priv2</text>
<rect class="d-box" x="192" y="436" width="544" height="56" rx="8"/>
<text class="d-name" x="208" y="460">Shared ASM disks: asm1 + asm2 → DATA disk group</text>
<text class="d-quiet" x="208" y="478">50 GB each · VirtualBox shareable · local block PVs by /dev/disk/by-id</text>
</svg><figcaption>Lab architecture: 3 VMs, 2 RAC pods, 3 networks, 2 shared disks.</figcaption></figure>"""

SCAN = """<figure class="diagram"><svg viewBox="0 0 760 236" role="img" aria-label="A SCAN connection takes two hops: SCAN listener, then the chosen instance">
<defs><marker id="scan-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path class="d-arrowhead" d="M0 0L10 5L0 10z"/></marker></defs>
<text class="d-title" x="24" y="30">A SCAN connection takes two hops: SCAN listener, then the chosen instance</text>
<rect class="d-box" x="24" y="56" width="160" height="88" rx="8"/>
<text class="d-name" x="40" y="80">1 · Client</text>
<text class="d-text" x="40" y="100">asks CoreDNS for</text>
<text class="d-text" x="40" y="116">racnode-scan</text>
<rect class="d-box" x="208" y="56" width="160" height="88" rx="8"/>
<text class="d-name" x="224" y="80">2 · DNS answer</text>
<text class="d-text" x="224" y="100">both pod IPs, from</text>
<text class="d-text" x="224" y="116">the headless Service</text>
<rect class="d-pod" x="392" y="56" width="160" height="88" rx="8"/>
<text class="d-name" x="408" y="80">3 · SCAN listener</text>
<text class="d-text" x="408" y="100">port 1521; picks the</text>
<text class="d-text" x="408" y="116">less busy instance</text>
<rect class="d-pod" x="576" y="56" width="160" height="88" rx="8"/>
<text class="d-name" x="592" y="80">4 · Local listener</text>
<text class="d-text" x="592" y="100">redirect target;</text>
<text class="d-text" x="592" y="116">session in ORCLPDB</text>
<g class="d-line"><line x1="184" y1="100" x2="206" y2="100" marker-end="url(#scan-arrow)"/><line x1="368" y1="100" x2="390" y2="100" marker-end="url(#scan-arrow)"/><line x1="552" y1="100" x2="574" y2="100" marker-end="url(#scan-arrow)"/></g>
<rect class="d-band" x="24" y="164" width="712" height="48" rx="8"/>
<text class="d-text" x="40" y="185">Redirect target inside the cluster: the pod IP on port 1522 (set by Grid).</text>
<text class="d-text" x="40" y="202">After the NodePort change (13.3): racnode&lt;n&gt;-0-vip.rac.svc.cluster.local on 30203 / 30204.</text>
</svg><figcaption>How a client reaches an instance through SCAN.</figcaption></figure>"""

RESTART = """<figure class="diagram"><svg viewBox="0 0 760 452" role="img" aria-label="A recreated RAC pod rejoins by itself in about four minutes">
<defs><marker id="rs-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path class="d-arrowhead" d="M0 0L10 5L0 10z"/></marker></defs>
<text class="d-title" x="24" y="30">A recreated RAC pod rejoins by itself in about four minutes</text>
<rect class="d-box" x="24" y="52" width="456" height="40" rx="8"/>
<text class="d-name" x="40" y="77">kubectl delete pod racnode2-0</text>
<rect class="d-box" x="24" y="112" width="456" height="40" rx="8"/>
<text class="d-text" x="40" y="137">StatefulSet recreates it on worker2 · about 30 s · new pod IP</text>
<rect class="d-box" x="24" y="172" width="456" height="40" rx="8"/>
<text class="d-text" x="40" y="197">rc.local → setupContainerEnv.sh → /u01/…/onstart.sh</text>
<rect class="d-box" x="24" y="232" width="456" height="40" rx="8"/>
<text class="d-text" x="40" y="257">restore homes, SSH host keys, oratab, oraInst.loc, oraenv</text>
<rect class="d-box" x="24" y="292" width="456" height="40" rx="8"/>
<text class="d-text" x="40" y="317">tfa_setup · rootcrs.sh -updateosfiles (the doc's steps)</text>
<rect class="d-box" x="24" y="352" width="456" height="40" rx="8"/>
<text class="d-text" x="40" y="377">crsctl start crs -wait → ASM, listeners, ORCLCDB2</text>
<rect class="d-pod" x="24" y="404" width="456" height="40" rx="8"/>
<text class="d-name" x="40" y="429">Pod 1/1 Ready · about 4 minutes after the delete</text>
<g class="d-line"><line x1="252" y1="92" x2="252" y2="110" marker-end="url(#rs-arrow)"/><line x1="252" y1="152" x2="252" y2="170" marker-end="url(#rs-arrow)"/><line x1="252" y1="212" x2="252" y2="230" marker-end="url(#rs-arrow)"/><line x1="252" y1="272" x2="252" y2="290" marker-end="url(#rs-arrow)"/><line x1="252" y1="332" x2="252" y2="350" marker-end="url(#rs-arrow)"/><line x1="252" y1="392" x2="252" y2="402" marker-end="url(#rs-arrow)"/></g>
<rect class="d-band" x="512" y="52" width="224" height="140" rx="8"/>
<text class="d-name" x="528" y="76">Meanwhile</text>
<text class="d-text" x="528" y="98">node 1 evicts node 2</text>
<text class="d-text" x="528" y="116">and recovers its work</text>
<text class="d-text" x="528" y="140">new connections go to</text>
<text class="d-text" x="528" y="158">ORCLCDB1 through SCAN</text>
<text class="d-text" x="528" y="176">no data lost</text>
<g class="d-line"><line x1="480" y1="72" x2="510" y2="72" marker-end="url(#rs-arrow)"/></g>
</svg><figcaption>Automatic restart path (Phase 14.3). The doc's manual path runs the same steps by hand.</figcaption></figure>"""

import sys as _sys; _sys.path.insert(0, "/home/claude/tools"); _sys.path.insert(0, "/home/claude/sysdesign")
from dia import to_svg as _to_svg; import specs as _specs
DIAGRAMS = {"arch": ARCH, "scan": SCAN, "restart": RESTART, "system": _to_svg(_specs.SYSTEM)}

# ---------------------------------------------------------------- markdown -> html
md = markdown.Markdown(extensions=["tables", "toc", "sane_lists"], extension_configs={"toc": {"toc_depth": "2-3"}})
body = md.convert(src)
for i, b in enumerate(blocks):
    body = body.replace(f"<p>@@CODE{i}@@</p>", b)
for k, d in DIAGRAMS.items():
    body = body.replace(f"<p>@@DIAGRAM:{k}@@</p>", d)
assert "@@" not in body, "unreplaced placeholder"
body = re.sub(r"<table>", '<div class="table-wrap"><table>', body)
body = body.replace("</table>", "</table></div>")

# sections: wrap every h2 and its content
parts = re.split(r'(?=<h2 id=")', body)
sections = []
toc = []
for part in parts:
    m = re.match(r'<h2 id="([^"]+)">(.*?)</h2>', part)
    if not m:
        continue
    sid, title = m.group(1), m.group(2)
    plain = re.sub("<[^>]+>", "", title)
    pm = re.match(r"Phase (\d+): (.*)", plain)
    if pm:
        num, short = pm.group(1), pm.group(2)
        toc.append(f'<li><a href="#{sid}"><span class="toc-num">{num}</span>{html.escape(short)}</a></li>')
        part = part.replace(m.group(0), f'<h2 id="{sid}"><span class="eyebrow">Phase {num}</span>{html.escape(short)}</h2>', 1)
    else:
        toc.append(f'<li><a href="#{sid}"><span class="toc-num"></span>{html.escape(plain)}</a></li>')
    sections.append(f'<section class="sec">{part}</section>')
toc_html = "\n".join(toc)
content = "\n".join(sections)

STYLE = open(os.path.join(HERE, "guide.css"), encoding="utf-8").read()
SCRIPT = open(os.path.join(HERE, "guide.js"), encoding="utf-8").read()
PYG = HtmlFormatter().get_style_defs("pre code")  # replaced by our token colours in guide.css


def page(pdf_link, print_mode=False):
    pdf = ('<a class="pdf" href="rac-k8s-operator-lab-guide.pdf">PDF version</a>' if pdf_link else "")
    cls = "print" if print_mode else ""
    return f"""<title>RAC Operator Lab Guide</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700;800&family=Source+Sans+3:ital,wght@0,400;0,600;0,700;1,400&family=JetBrains+Mono:wght@400;600&display=swap">
<style>{STYLE}</style>
<div class="shell {cls}">
<header class="hero">
  <div class="hero-in">
    <p class="kicker">Operator lab · Oracle RAC 19c on kubeadm</p>
    <h1>The operator lab: Phases 0–11</h1>
    <p class="lede">A second, separate lab next to the manual one, built the same way up to Multus, then handed to Oracle&#39;s database operator for the RAC database. Own VM names, IPs, ports and disks; the same golden image.</p>
    <ul class="stack"><li>op-controlplane · op-worker1 · op-worker2</li><li>10.0.1.20–22</li><li>SSH 2220–2222</li><li>D:&#92;VMs&#92;rac-op</li><li>Oracle Database Operator v2.2.0</li></ul>
    <p class="meta">26 Oct 2026 · Companion to the manual lab guide; Phases 7 onward follow <a href="https://github.com/oracle/oracle-database-operator">oracle/oracle-database-operator</a>. {pdf}</p>
    <div class="legend" aria-label="Where commands run">
      <span class="where win">PowerShell / Git Bash</span><span>on your PC</span>
      <span class="where node">golden VM · controlplane · worker</span><span>root shell on a VM</span>
      <span class="where pod">racnode1-0 · racnode2-0</span><span>root shell in a RAC pod</span>
    </div>
  </div>
</header>
<div class="layout">
  <nav class="toc" aria-label="Contents">
    <details open><summary>Contents</summary><ol>{toc_html}</ol></details>
  </nav>
  <main class="content">{content}
  <footer class="foot">Built from the lab's build log and scripts (rac-k8s-poc). Values are from the author's lab; change them to match yours.</footer>
  </main>
</div>
</div>
<script>{SCRIPT}</script>
"""


inner = page(pdf_link=False)
open(os.path.join(OUT, "artifact.html"), "w", encoding="utf-8").write(inner)
full = '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n' + page(pdf_link=True).replace("<style>", "<style>", 1) + "\n</html>\n"
# move the head-ish parts (title, meta, links, style) into <head>
head_end = full.index('<div class="shell')
full = full[:head_end] + "</head>\n<body>\n" + full[head_end:].replace("\n</html>\n", "\n</body>\n</html>\n")
open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(full)
pr = page(pdf_link=False, print_mode=True)
open(os.path.join(OUT, "print.html"), "w", encoding="utf-8").write(
    '<!doctype html><html lang="en"><head><meta charset="utf-8">' + pr[:pr.index('<div class="shell')] + "</head><body>" + pr[pr.index('<div class="shell'):] + "</body></html>")
print("sections:", len(sections), "code blocks:", len(blocks), "bytes:", len(full))
