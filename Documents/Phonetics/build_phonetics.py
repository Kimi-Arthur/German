import os
import re
import ssl
import urllib.request
import urllib.parse
import hashlib
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

ctx = ssl._create_unverified_context()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "audios")
IMG_DIR = os.path.join(BASE_DIR, "img")

os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(IMG_DIR, exist_ok=True)

URLS = [
    ("01_德语字母表", "第01讲 - 德语字母表", "https://www.sharplingo.cn/courses/show-lecture/5f4910f3c5ff5bb665f03780/5f653134238d21efc1dc331e/5f653134238d21efc1dc331d", "https://www.bilibili.com/video/BV1Ly4y1E79o"),
    ("02_德语发音规则（一）", "第02讲 - 单元音与发音规则", "https://www.sharplingo.cn/courses/show-lecture/5f4910f3c5ff5bb665f03780/5f653474238d21efc1dc3320/5f653474238d21efc1dc331f", "https://www.bilibili.com/video/BV1R5411A76Y"),
    ("03_德语发音规则（二）", "第03讲 - 复合元音与发音规则", "https://www.sharplingo.cn/courses/show-lecture/5f4910f3c5ff5bb665f03780/5f653b57dd0f7d0b86fcec26/5f653b57dd0f7d0b86fcec25", "https://www.bilibili.com/video/BV1ny4y187Mb"),
    ("04_德语发音规则（三）", "第04讲 - 辅音与发音规则", "https://sharplingo.cn/courses/show-lecture/5f4910f3c5ff5bb665f03780/5f653c48dd0f7d0b86fcec28/5f653c48dd0f7d0b86fcec27", "https://www.bilibili.com/video/BV1ry4y177qy")
]

url_to_local_audio = {}
url_to_local_img = {}

def get_audio_relpath(src_url):
    if not src_url:
        return ""
    abs_url = urllib.parse.urljoin("https://www.sharplingo.cn", src_url)
    if abs_url in url_to_local_audio:
        return url_to_local_audio[abs_url]
    
    parsed = urllib.parse.urlparse(abs_url)
    filename = os.path.basename(parsed.path)
    if not filename or not (filename.endswith('.mp3') or filename.endswith('.ogg') or filename.endswith('.wav')):
        filename = 'audio.mp3'
    
    url_hash = hashlib.md5(abs_url.encode('utf-8')).hexdigest()[:6]
    safe_filename = f"{url_hash}_{filename}"
    rel_path = f"audios/{safe_filename}"
    url_to_local_audio[abs_url] = rel_path
    return rel_path

def download_single_audio(abs_url):
    rel_path = url_to_local_audio[abs_url]
    safe_filename = os.path.basename(rel_path)
    local_path = os.path.join(AUDIO_DIR, safe_filename)
    
    if not os.path.exists(local_path) or os.path.getsize(local_path) == 0:
        parsed = urllib.parse.urlparse(abs_url)
        quoted_path = urllib.parse.quote(parsed.path)
        full_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, quoted_path, parsed.params, parsed.query, parsed.fragment))
        try:
            req = urllib.request.Request(full_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=15) as resp, open(local_path, 'wb') as f:
                f.write(resp.read())
        except Exception as e:
            print(f"  Error downloading audio {full_url}: {e}")

def get_img_relpath(src_url):
    if not src_url:
        return "img/speaker-jpg.png"
    abs_url = urllib.parse.urljoin("https://www.sharplingo.cn", src_url)
    if abs_url in url_to_local_img:
        return url_to_local_img[abs_url]
    
    parsed = urllib.parse.urlparse(abs_url)
    filename = os.path.basename(parsed.path) or 'speaker-jpg.png'
    rel_path = f"img/{filename}"
    url_to_local_img[abs_url] = rel_path
    return rel_path

def download_single_img(abs_url):
    rel_path = url_to_local_img[abs_url]
    filename = os.path.basename(rel_path)
    local_path = os.path.join(IMG_DIR, filename)
    
    if not os.path.exists(local_path) or os.path.getsize(local_path) == 0:
        parsed = urllib.parse.urlparse(abs_url)
        quoted_path = urllib.parse.quote(parsed.path)
        full_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, quoted_path, parsed.params, parsed.query, parsed.fragment))
        try:
            req = urllib.request.Request(full_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=15) as resp, open(local_path, 'wb') as f:
                f.write(resp.read())
        except Exception as e:
            print(f"  Error downloading img {full_url}: {e}")

class Node:
    def __init__(self, tag, attrs=None):
        self.tag = tag
        self.attrs = dict(attrs) if attrs else {}
        self.children = []

class HTMLTreeParser(HTMLParser):
    VOID_TAGS = {'img', 'br', 'hr', 'source', 'input', 'meta', 'link'}
    
    def __init__(self):
        super().__init__()
        self.root = Node('root')
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_endtag(self, tag):
        if len(self.stack) > 1 and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_data(self, data):
        if self.stack:
            self.stack[-1].children.append(data)

def node_to_html(node):
    if isinstance(node, str):
        return node
    
    tag = node.tag
    if tag == 'root':
        return "".join(node_to_html(c) for c in node.children)
    
    attrs = dict(node.attrs)
    
    if tag == 'source':
        src = attrs.get('src', '')
        if src:
            attrs['src'] = get_audio_relpath(src)
    
    if tag == 'img':
        src = attrs.get('src', '')
        if src:
            attrs['src'] = get_img_relpath(src)
            style = attrs.get('style', '')
            if 'cursor' not in style:
                attrs['style'] = (style + ';cursor:pointer;').lstrip(';')
    
    attrs_str = ""
    for k, v in attrs.items():
        attrs_str += f' {k}="{v}"'
        
    if tag in HTMLTreeParser.VOID_TAGS:
        return f"<{tag}{attrs_str}/>"
    
    inner = "".join(node_to_html(c) for c in node.children)
    return f"<{tag}{attrs_str}>{inner}</{tag}>"

def node_to_md_cell(node):
    if isinstance(node, str):
        return node.replace('\n', ' ').strip()
    
    tag = node.tag
    if tag == 'audio':
        audio_src = ""
        for c in node.children:
            if isinstance(c, Node) and c.tag == 'source':
                audio_src = c.attrs.get('src', '')
                break
        if not audio_src:
            audio_src = node.attrs.get('src', '')
        if audio_src:
            rel_audio = get_audio_relpath(audio_src)
            return f' <audio controls src="{rel_audio}" style="height:24px;width:110px;vertical-align:middle;"></audio> '
        return ""
    
    if tag in ('img', 'script', 'style', 'source'):
        return ""
    
    cell_str = ""
    for c in node.children:
        cell_str += node_to_md_cell(c)
    
    return cell_str

def table_to_md(table_node):
    rows = []
    def collect_tr(n):
        if isinstance(n, Node):
            if n.tag == 'tr':
                rows.append(n)
            else:
                for c in n.children:
                    collect_tr(c)
    collect_tr(table_node)
    
    if not rows:
        return ""
    
    md_rows = []
    for i, tr in enumerate(rows):
        cells = [c for c in tr.children if isinstance(c, Node) and c.tag in ('th', 'td')]
        cell_texts = []
        for cell in cells:
            txt = node_to_md_cell(cell).strip()
            txt = re.sub(r'\s+', ' ', txt)
            txt = txt.replace('|', '\\|')
            cell_texts.append(txt)
        
        if cell_texts:
            md_rows.append("| " + " | ".join(cell_texts) + " |")
            if i == 0:
                divider = "| " + " | ".join(["---"] * len(cell_texts)) + " |"
                md_rows.append(divider)
            
    return "\n".join(md_rows) + "\n\n"

def node_to_md(node):
    if isinstance(node, str):
        text = node.strip()
        if text:
            return text + " "
        return ""
    
    tag = node.tag
    if tag == 'root':
        res = ""
        for c in node.children:
            res += node_to_md(c)
        return res
    
    if tag in ('h1', 'h2'):
        text = "".join(node_to_md(c) for c in node.children).strip()
        return f"\n## {text}\n\n"
    if tag == 'h3':
        text = "".join(node_to_md(c) for c in node.children).strip()
        return f"\n### {text}\n\n"
    if tag in ('h4', 'h5', 'h6'):
        text = node_to_md_cell(node).strip()
        text = re.sub(r'\s+', ' ', text)
        return f"\n#### {text}\n\n"
    if tag == 'p':
        text = node_to_md_cell(node).strip()
        text = re.sub(r'\s+', ' ', text)
        if text:
            return f"\n{text}\n\n"
        return ""
    if tag == 'hr':
        return "\n---\n\n"
    if tag == 'table':
        return "\n" + table_to_md(node)
    
    if tag in ('div', 'tbody', 'thead', 'tr'):
        res = ""
        for c in node.children:
            res += node_to_md(c)
        return res
    
    return "".join(node_to_md(c) for c in node.children)

def clean_html_comments(html):
    return re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)

parsed_pages = []

for idx, (fname_prefix, title, url, video_url) in enumerate(URLS, 1):
    print(f"Fetching {title}...")
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    raw_html = urllib.request.urlopen(req, context=ctx).read().decode('utf-8')
    
    match = re.search(r'<div class=\"module-info-div\">(.*?)</div>\s*<footer', raw_html, re.DOTALL)
    if not match:
        print(f"  FAILED to find module-info-div for {title}")
        continue
        
    raw_content = clean_html_comments(match.group(1))
    raw_content = re.sub(r'<a id=\"last-page\".*?</a>', '', raw_content, flags=re.DOTALL)
    raw_content = re.sub(r'<div style="text-align: center; max-width: 400px;.*?</div>', '', raw_content, flags=re.DOTALL)
    raw_content = re.sub(r'<button.*?</button>', '', raw_content, flags=re.DOTALL)
    
    parser = HTMLTreeParser()
    parser.feed(raw_content)
    
    def precollect(node):
        if isinstance(node, Node):
            if node.tag == 'source':
                src = node.attrs.get('src', '')
                if src:
                    get_audio_relpath(src)
            elif node.tag == 'img':
                src = node.attrs.get('src', '')
                if src:
                    get_img_relpath(src)
            for c in node.children:
                precollect(c)
    precollect(parser.root)
    
    parsed_pages.append((idx, fname_prefix, title, parser.root, video_url))

print(f"\nCollected {len(url_to_local_audio)} unique audio URLs and {len(url_to_local_img)} image URLs.")
print("Starting concurrent downloading of audio and image files...")

with ThreadPoolExecutor(max_workers=16) as executor:
    executor.map(download_single_audio, list(url_to_local_audio.keys()))
    executor.map(download_single_img, list(url_to_local_img.keys()))

print("All audio and image downloads finished!")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>德语发音教程 (German Phonetics)</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            color: #212529;
            background-color: #f8f9fa;
            margin: 0;
            padding: 20px;
        }}
        .container {{
            max-width: 960px;
            margin: 0 auto;
            background: #ffffff;
            padding: 35px;
            border-radius: 12px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        }}
        h1 {{
            color: #1a2530;
            text-align: center;
            margin-bottom: 6px;
            border-bottom: 2px solid #e9ecef;
            padding-bottom: 12px;
        }}
        p.subtitle {{
            text-align: center;
            color: #6c757d;
            margin-bottom: 30px;
            font-size: 1.05rem;
        }}
        .toc-box {{
            background-color: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 8px;
            padding: 20px 24px;
            margin-bottom: 35px;
        }}
        .toc-title {{
            font-weight: 600;
            font-size: 1.1rem;
            margin-bottom: 12px;
            color: #1a2530;
        }}
        .toc-list {{
            list-style: none;
            padding-left: 0;
            margin: 0;
        }}
        .toc-list li {{
            margin-bottom: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .toc-list li a {{
            color: #0d6efd;
            text-decoration: none;
            font-weight: 500;
        }}
        .toc-list li a:hover {{
            text-decoration: underline;
        }}
        .toc-video-link {{
            color: #0d6efd;
            text-decoration: none;
            font-size: 0.9rem;
        }}
        .toc-video-link:hover {{
            text-decoration: underline;
        }}
        .lecture-section {{
            margin-bottom: 40px;
            padding-top: 10px;
        }}
        .lecture-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid #0d6efd;
            padding-bottom: 8px;
            margin-top: 30px;
            margin-bottom: 20px;
        }}
        .lecture-header h2 {{
            margin: 0;
            color: #1a2530;
            font-size: 1.5rem;
        }}
        .lecture-header .video-link {{
            color: #0d6efd;
            text-decoration: none;
            font-weight: 500;
            font-size: 0.95rem;
        }}
        .lecture-header .video-link:hover {{
            text-decoration: underline;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            text-align: center;
        }}
        th, td {{
            border: 1px solid #dee2e6;
            padding: 12px;
            vertical-align: middle;
        }}
        th {{
            background-color: #f1f3f5;
            font-weight: 600;
        }}
        tr:nth-child(even) {{
            background-color: #f8f9fa;
        }}
        .play-audio {{
            cursor: pointer;
            transition: transform 0.1s ease;
            vertical-align: middle;
        }}
        .play-audio:hover {{
            transform: scale(1.15);
        }}
        hr.section-divider {{
            border: 0;
            height: 1px;
            background: #dee2e6;
            margin: 40px 0;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🇩🇪 德语发音教程</h1>
        <p class="subtitle">Documents/Phonetics 学习课程与标准发音音频</p>
        
        <div class="toc-box">
            <div class="toc-title">📂 课程目录</div>
            <ul class="toc-list">
                {toc_items}
            </ul>
        </div>
        
        {content}
    </div>
</body>
</html>
"""

toc_html_items = []
sections_html = []
toc_md_items = []
sections_md = []

for idx, fname_prefix, title, root, video_url in parsed_pages:
    sec_id = f"lecture-{idx}"
    toc_html_items.append(
        f'<li><a href="#{sec_id}">{title}</a> <a class="toc-video-link" href="{video_url}" target="_blank">📺 视频教程</a></li>'
    )
    
    html_body = node_to_html(root)
    html_body = re.sub(r'<h[12][^>]*>.*?</h[12]>', '', html_body, count=1, flags=re.DOTALL)
    
    sec_html = f'''<section id="{sec_id}" class="lecture-section">
        <div class="lecture-header">
            <h2>{title}</h2>
            <a class="video-link" href="{video_url}" target="_blank">📺 观看教学视频 (Bilibili)</a>
        </div>
        {html_body}
    </section>'''
    sections_html.append(sec_html)

    # Markdown Section
    sec_anchor = f"lecture-{idx}"
    toc_md_items.append(f"{idx}. **[{title}](#{sec_anchor})** ([📺 视频教程]({video_url}))")
    
    md_body = node_to_md(root)
    md_body = re.sub(r'观看教学视频\s*打印模式\s*报错或提问\s*显示本课记忆卡片', '', md_body)
    md_body = re.sub(r'^\s*#+\s*模块\d+.*?\n+', '', md_body).strip()
    md_body = re.sub(r'^\s*#+\s*' + re.escape(title) + r'\s*\n+', '', md_body).strip()
    while md_body.startswith('---'):
        md_body = md_body[3:].strip()
    md_body = re.sub(r'\n{3,}', '\n\n', md_body).strip()
    
    sec_md = f'<a id="{sec_anchor}"></a>\n\n## {title}\n\n[📺 观看教学视频 (Bilibili)]({video_url})\n\n' + md_body
    sections_md.append(sec_md)

merged_html = HTML_TEMPLATE.format(
    toc_items="\n".join(toc_html_items),
    content="\n<hr class=\"section-divider\"/>\n".join(sections_html)
)

with open(os.path.join(BASE_DIR, "index.html"), 'w', encoding='utf-8') as f:
    f.write(merged_html)

merged_md = f"""# 🇩🇪 德语发音教程 (German Phonetics)

本教程整理自 SharpLingo 德语发音课程，包含全部讲解内容及配套音频文件。

## 📂 课程目录导航

{"\n".join(toc_md_items)}

---

""" + "\n\n---\n\n".join(sections_md) + """

---

## 🎵 音频与素材
- 所有语音音频文件均已安全存放在 [`audios/`](audios/) 目录下。
- 图像与喇叭图标存放在 [`img/`](img/) 目录下。
- 支持在 Markdown 编辑器（如 Obsidian、Typora、VS Code Preview）中直接播放音频。
"""

with open(os.path.join(BASE_DIR, "README.md"), 'w', encoding='utf-8') as f:
    f.write(merged_md)

# Clean up old separate files
old_files = [
    "01_德语字母表.html", "01_德语字母表.md",
    "02_德语发音规则（一）.html", "02_德语发音规则（一）.md",
    "03_德语发音规则（二）.html", "03_德语发音规则（二）.md",
    "04_德语发音规则（三）.html", "04_德语发音规则（三）.md"
]
for old_f in old_files:
    old_path = os.path.join(BASE_DIR, old_f)
    if os.path.exists(old_path):
        os.remove(old_path)

print("All tasks completed successfully!")
