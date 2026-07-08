"""
File management for WebApps Link Manager.

功能说明：
- scan_webapps(): 扫描 webapps/ 目录下所有 HTML 文件，生成项目列表
- upload_file(): 保存上传的 HTML 文件到 webapps/ 目录（支持版本管理）
- extract_zip(): 解压 ZIP 文件到 webapps/ 子目录，支持 UTF-8/GBK/CP437 编码
- delete_file(): 删除文件（需校验上传者 IP）
- can_delete(): 检查用户是否有权限删除文件

版本管理：
- 上传同名文件时：旧内容存档到 versions/ 目录，新内容写入原路径
- 版本访问：通过 /versions/<filename>/<version> 访问历史版本

文件 Key 规则：
- 根目录文件：file:example.html
- 子目录文件：file:子目录名/index.html

权限控制：
- 普通用户：只能删除自己 IP 上传的文件
- 管理员：可删除所有文件
"""
import os
import re
import sys
import zipfile
import shutil
from pathlib import Path


def safe_filename(raw_name: str) -> str:
    """
    Sanitize a filename to prevent path traversal attacks.
    - Returns only the basename (no directory components)
    - Rejects any path components containing '..'
    - Strips dangerous characters
    """
    # Reject if '..' anywhere in the raw name (before and after basename)
    if '..' in raw_name:
        return ''
    # Get just the basename (removes directory components)
    name = os.path.basename(raw_name)
    # Reject empty result or suspicious names
    if not name or name.startswith('.'):
        return ''
    # Accept only alphanumeric, Chinese chars, spaces, dashes, underscores, dots, parens
    safe = re.sub(r'[^\w\s一-鿿.\-()（）]', '', name)
    return safe.strip()
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# Add server directory to path for imports
_server_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(_server_dir))

from config import WEBAPPS_DIR, VERSIONS_DIR
import metadata


def to_pinyin(text: str) -> str:
    """Convert Chinese characters to pinyin (first letter of pinyin for each character)."""
    # Simple pinyin mapping for common Chinese characters
    pinyin_map = {
        # A
        '啊': 'a', '爱': 'ai',
        # B
        '吧': 'ba', '百': 'bai', '班': 'ban', '棒': 'bang', '保': 'bao', '北': 'bei', '本': 'ben', '比': 'bi', '边': 'bian', '标': 'biao', '别': 'bie', '宾': 'bin', '病': 'bing', '波': 'bo', '不': 'bu',
        # C
        '菜': 'cai', '参': 'can', '藏': 'cang', '测': 'ce', '层': 'ceng', '查': 'cha', '产': 'chan', '常': 'chang', '超': 'chao', '车': 'che', '陈': 'chen', '成': 'cheng', '吃': 'chi', '出': 'chu', '创': 'chuang', '春': 'chun', '词': 'ci', '从': 'cong', '错': 'cuo',
        # D
        '大': 'da', '带': 'dai', '单': 'dan', '当': 'dang', '道': 'dao', '得': 'de', '等': 'deng', '底': 'di', '点': 'dian', '店': 'dian', '调': 'diao', '顶': 'ding', '订': 'ding', '东': 'dong', '动': 'dong', '读': 'du', '段': 'duan', '对': 'dui', '多': 'duo',
        # E
        '额': 'e', '儿': 'er',
        # F
        '发': 'fa', '反': 'fan', '方': 'fang', '放': 'fang', '飞': 'fei', '费': 'fei', '分': 'fen', '风': 'feng', '服': 'fu', '负': 'fu', '附': 'fu', '复': 'fu',
        # G
        '改': 'gai', '干': 'gan', '感': 'gan', '高': 'gao', '告': 'gao', '个': 'ge', '给': 'gei', '根': 'gen', '工': 'gong', '共': 'gong', '关': 'guan', '管': 'guan', '光': 'guang', '广': 'guang', '贵': 'gui', '国': 'guo', '过': 'guo',
        # H
        '还': 'hai', '害': 'hai', '汉': 'han', '号': 'hao', '好': 'hao', '喝': 'he', '和': 'he', '黑': 'hei', '很': 'hen', '红': 'hong', '后': 'hou', '呼': 'hu', '湖': 'hu', '虎': 'hu', '护': 'hu', '花': 'hua', '化': 'hua', '划': 'hua', '话': 'hua', '环': 'huan', '换': 'huan', '黄': 'huang', '回': 'hui', '汇': 'hui', '火': 'huo',
        # J
        '机': 'ji', '级': 'ji', '极': 'ji', '集': 'ji', '济': 'ji', '继': 'ji', '计': 'ji', '记': 'ji', '季': 'ji', '继': 'ji', '加': 'jia', '家': 'jia', '价': 'jia', '架': 'jia', '尖': 'jian', '检': 'jian', '减': 'jian', '见': 'jian', '建': 'jian', '键': 'jian', '江': 'jiang', '讲': 'jiang', '交': 'jiao', '角': 'jiao', '脚': 'jiao', '教': 'jiao', '街': 'jie', '节': 'jie', '杰': 'jie', '解': 'jie', '今': 'jin', '金': 'jin', '仅': 'jin', '紧': 'jin', '锦': 'jin', '尽': 'jin', '进': 'jin', '近': 'jin', '晋': 'jin', '京': 'jing', '经': 'jing', '精': 'jing', '景': 'jing', '警': 'jing', '静': 'jing', '九': 'jiu', '酒': 'jiu', '久': 'jiu', '旧': 'jiu', '就': 'jiu', '聚': 'ju', '巨': 'ju', '具': 'ju', '剧': 'ju', '据': 'ju', '距': 'ju', '聚': 'ju', '决': 'jue', '觉': 'jue',
        # K
        '开': 'kai', '看': 'kan', '考': 'kao', '靠': 'kao', '科': 'ke', '可': 'ke', '克': 'ke', '刻': 'ke', '客': 'ke', '课': 'ke', '空': 'kong', '口': 'kou', '苦': 'ku', '快': 'kuai', '款': 'kuan', '矿': 'kuang', '亏': 'kui', '况': 'kuang', '亏': 'kui',
        # L
        '拉': 'la', '来': 'lai', '蓝': 'lan', '浪': 'lang', '老': 'lao', '乐': 'le', '雷': 'lei', '累': 'lei', '类': 'lei', '冷': 'leng', '离': 'li', '里': 'li', '理': 'li', '礼': 'li', '历': 'li', '立': 'li', '利': 'li', '例': 'li', '连': 'lian', '联': 'lian', '恋': 'lian', '练': 'lian', '凉': 'liang', '两': 'liang', '亮': 'liang', '量': 'liang', '辽': 'liao', '了': 'liao', '料': 'liao', '列': 'lie', '林': 'lin', '临': 'lin', '邻': 'lin', '领': 'ling', '另': 'ling', '留': 'liu', '流': 'liu', '六': 'liu', '龙': 'long', '楼': 'lou', '露': 'lu', '路': 'lu', '旅': 'lv', '绿': 'lv', '虑': 'lv', '律': 'lv', '论': 'lun', '罗': 'luo', '洛': 'luo',
        # M
        '妈': 'ma', '马': 'ma', '吗': 'ma', '买': 'mai', '卖': 'mai', '满': 'man', '慢': 'man', '忙': 'mang', '毛': 'mao', '冒': 'mao', '么': 'me', '没': 'mei', '每': 'mei', '美': 'mei', '妹': 'mei', '门': 'men', '们': 'men', '梦': 'meng', '米': 'mi', '面': 'mian', '民': 'min', '明': 'ming', '名': 'ming', '命': 'ming', '模': 'mo', '末': 'mo', '某': 'mou', '母': 'mu', '目': 'mu', '幕': 'mu',
        # N
        '拿': 'na', '哪': 'na', '那': 'na', '娜': 'na', '纳': 'na', '呢': 'ne', '内': 'nei', '能': 'neng', '你': 'ni', '年': 'nian', '念': 'nian', '娘': 'niang', '您': 'nin', '宁': 'ning', '牛': 'niu', '农': 'nong', '弄': 'nong', '努': 'nu', '女': 'nv', '暖': 'nuan',
        # O
        '欧': 'ou',
        # P
        '怕': 'pa', '拍': 'pai', '排': 'pai', '派': 'pai', '盘': 'pan', '判': 'pan', '旁': 'pang', '跑': 'pao', '配': 'pei', '朋': 'peng', '皮': 'pi', '片': 'pian', '票': 'piao', '漂': 'piao', '品': 'pin', '平': 'ping', '评': 'ping', '苹': 'ping', '凭': 'ping', '破': 'po', '迫': 'po', '普': 'pu', '拍': 'pai',
        # Q
        '七': 'qi', '期': 'qi', '其': 'qi', '奇': 'qi', '骑': 'qi', '起': 'qi', '气': 'qi', '汽': 'qi', '器': 'qi', '企': 'qi', '期': 'qi', '棋': 'qi', '旗': 'qi', '强': 'qiang', '墙': 'qiang', '抢': 'qiang', '桥': 'qiao', '巧': 'qiao', '青': 'qing', '轻': 'qing', '清': 'qing', '晴': 'qing', '情': 'qing', '请': 'qing', '秋': 'qiu', '求': 'qiu', '球': 'qiu', '区': 'qu', '曲': 'qu', '去': 'qu', '全': 'quan', '权': 'quan', '泉': 'quan', '却': 'que', '群': 'qun',
        # R
        '然': 'ran', '让': 'rang', '绕': 'rao', '热': 're', '人': 'ren', '认': 'ren', '日': 'ri', '容': 'rong', '肉': 'rou', '如': 'ru', '入': 'ru', '软': 'ruan', '锐': 'rui', '润': 'run', '若': 'ruo',
        # S
        '撒': 'sa', '赛': 'sai', '三': 'san', '色': 'se', '森': 'sen', '杀': 'sha', '沙': 'sha', '山': 'shan', '上': 'shang', '尚': 'shang', '商': 'shang', '少': 'shao', '社': 'she', '身': 'shen', '深': 'shen', '什': 'shen', '生': 'sheng', '声': 'sheng', '师': 'shi', '十': 'shi', '时': 'shi', '实': 'shi', '食': 'shi', '始': 'shi', '使': 'shi', '世': 'shi', '市': 'shi', '示': 'shi', '式': 'shi', '试': 'shi', '事': 'shi', '是': 'shi', '室': 'shi', '视': 'shi', '收': 'shou', '手': 'shou', '首': 'shou', '受': 'shou', '书': 'shu', '术': 'shu', '树': 'shu', '坚': 'shu', '数': 'shu', '双': 'shuang', '水': 'shui', '顺': 'shun', '思': 'si', '死': 'si', '四': 'si', '似': 'si', '松': 'song', '送': 'song', '诉': 'su', '速': 'su', '算': 'suan', '虽': 'sui', '岁': 'sui', '碎': 'sui', '孙': 'sun', '所': 'suo',
        # T
        '他': 'ta', '她': 'ta', '它': 'ta', '台': 'tai', '太': 'tai', '态': 'tai', '谈': 'tan', '探': 'tan', '汤': 'tang', '糖': 'tang', '提': 'ti', '题': 'ti', '体': 'ti', '天': 'tian', '田': 'tian', '条': 'tiao', '铁': 'tie', '听': 'ting', '停': 'ting', '通': 'tong', '同': 'tong', '统': 'tong', '痛': 'tong', '投': 'tou', '头': 'tou', '图': 'tu', '团': 'tuan', '推': 'tui', '腿': 'tui', '脱': 'tuo', '外': 'wai', '弯': 'wan', '完': 'wan', '玩': 'wan', '晚': 'wan', '万': 'wan', '王': 'wang', '往': 'wang', '网': 'wang', '望': 'wang', '危': 'wei', '位': 'wei', '文': 'wen', '问': 'wen', '我': 'wo', '卧': 'wo', '屋': 'wu', '五': 'wu', '午': 'wu', '物': 'wu', '务': 'wu',
        # X
        '西': 'xi', '吸': 'xi', '希': 'xi', '息': 'xi', '稀': 'xi', '习': 'xi', '洗': 'xi', '系': 'xi', '戏': 'xi', '细': 'xi', '夏': 'xia', '先': 'xian', '鲜': 'xian', '现': 'xian', '线': 'xian', '相': 'xiang', '想': 'xiang', '向': 'xiang', '象': 'xiang', '像': 'xiang', '小': 'xiao', '笑': 'xiao', '效': 'xiao', '校': 'xiao', '些': 'xie', '写': 'xie', '谢': 'xie', '新': 'xin', '心': 'xin', '信': 'xin', '星': 'xing', '行': 'xing', '形': 'xing', '醒': 'xing', '姓': 'xing', '休': 'xiu', '修': 'xiu', '秀': 'xiu', '需': 'xu', '须': 'xu', '虚': 'xu', '许': 'xu', '学': 'xue', '雪': 'xue', '血': 'xue',
        # Y
        '压': 'ya', '牙': 'ya', '亚': 'ya', '呀': 'ya', '烟': 'yan', '研': 'yan', '言': 'yan', '岩': 'yan', '演': 'yan', '眼': 'yan', '演': 'yan', '阳': 'yang', '养': 'yang', '样': 'yang', '药': 'yao', '要': 'yao', '爷': 'ye', '也': 'ye', '业': 'ye', '夜': 'ye', '叶': 'ye', '页': 'ye', '一': 'yi', '医': 'yi', '衣': 'yi', '依': 'yi', '易': 'yi', '已': 'yi', '以': 'yi', '意': 'yi', '义': 'yi', '艺': 'yi', '忆': 'yi', '议': 'yi', '译': 'yi', '异': 'yi', '因': 'yin', '音': 'yin', '银': 'yin', '引': 'yin', '印': 'yin', '英': 'ying', '应': 'ying', '影': 'ying', '映': 'ying', '硬': 'ying', '用': 'yong', '勇': 'yong', '涌': 'yong', '永': 'yong', '您': 'nin', '优': 'you', '由': 'you', '油': 'you', '游': 'you', '友': 'you', '有': 'you', '又': 'you', '右': 'you', '于': 'yu', '与': 'yu', '雨': 'yu', '语': 'yu', '元': 'yuan', '原': 'yuan', '园': 'yuan', '圆': 'yuan', '远': 'yuan', '院': 'yuan', '愿': 'yuan', '月': 'yue', '约': 'yue', '越': 'yue', '云': 'yun', '运': 'yun',
        # Z
        '杂': 'za', '在': 'zai', '再': 'zai', '早': 'zao', '怎': 'zen', '曾': 'zeng', '扎': 'zha', '炸': 'zha', '站': 'zhan', '张': 'zhang', '长': 'zhang', '掌': 'zhang', '找': 'zhao', '照': 'zhao', '者': 'zhe', '这': 'zhe', '真': 'zhen', '诊': 'zhen', '阵': 'zhen', '正': 'zheng', '政': 'zheng', '证': 'zheng', '争': 'zheng', '睁': 'zheng', '整': 'zheng', '知': 'zhi', '之': 'zhi', '只': 'zhi', '纸': 'zhi', '指': 'zhi', '至': 'zhi', '治': 'zhi', '中': 'zhong', '终': 'zhong', '钟': 'zhong', '重': 'zhong', '周': 'zhou', '洲': 'zhou', '主': 'zhu', '注': 'zhu', '住': 'zhu', '祝': 'zhu', '驻': 'zhu', '抓': 'zhua', '专': 'zhuan', '转': 'zhuan', '装': 'zhuang', '准': 'zhun', '资': 'zi', '子': 'zi', '字': 'zi', '自': 'zi', '走': 'zou', '租': 'zu', '足': 'zu', '组': 'zu', '祖': 'zu', '最': 'zui', '昨': 'zuo', '左': 'zuo', '作': 'zuo', '做': 'zuo', '坐': 'zuo', '座': 'zuo',
    }

    result = []
    for char in text:
        if '\u4e00' <= char <= '\u9fff':  # Chinese character
            pinyin = pinyin_map.get(char, '')
            if pinyin:
                result.append(pinyin)
            else:
                result.append(char)  # Keep unknown chars
        elif char.isalnum() or char in ('-', '_'):
            result.append(char)
        else:
            result.append('_')  # Replace special chars with underscore

    return ''.join(result)


def get_local_ip() -> str:
    """Return the most likely LAN IP, skipping docker/vpn/virtual interfaces."""
    import re
    import subprocess
    try:
        result = subprocess.run(['ifconfig'], capture_output=True, text=True).stdout
        for line in result.split('\n'):
            m = re.search(r'inet\s+((?:\d{1,3}\.){3}\d{1,3})', line)
            if not m:
                continue
            ip = m.group(1)
            # Skip loopback and VPN interfaces (198.18.x.x, 198.19.x.x are GlobalProtect)
            if ip in ('127.0.0.1', '198.18.0.1') or ip.startswith('198.18.') or ip.startswith('198.19.'):
                continue
            return ip
    except Exception:
        pass
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def get_product_line(rel_path: str) -> str:
    """Extract product line from file path (first folder name)."""
    parts = rel_path.split("/")
    if len(parts) > 1:
        folder = parts[0]
        # Map folder names to product lines
        mapping = {
            "AI医生": "康老板AI医生",
            "AI健康": "康老板健康",
            "AI商城": "康老板商城",
            "康店": "康店代理商",
            "康管家": "康管家",
            "旅途管家": "旅途管家",
            "老板云": "老板云",
            "老板帮": "老板帮",
            "幸福绩效": "幸福绩效",
            "飞联天下": "飞联天下",
            "创业天使": "创业天使",
            "会议系统": "会议系统",
            "加速中心": "加速中心",
            "数智化": "数智化",
            "自搭云": "自搭云",
            "企座": "企座",
        }
        return mapping.get(folder, "")
    return ""


def extract_html_title_description(html_content: bytes) -> Tuple[str, str]:
    """Extract title and description from HTML content."""
    try:
        content = html_content.decode('utf-8', errors='ignore')
    except:
        return "", ""

    # Extract title
    title_match = re.search(r'<title[^>]*>([^<]+)</title>', content, re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else ""

    # Extract description from meta tag
    desc_match = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', content, re.IGNORECASE)
    if not desc_match:
        desc_match = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']', content, re.IGNORECASE)
    description = desc_match.group(1).strip() if desc_match else ""

    # Fallback: get first h1 as title
    if not title:
        h1_match = re.search(r'<h1[^>]*>([^<]+)</h1>', content, re.IGNORECASE)
        title = h1_match.group(1).strip() if h1_match else ""

    return title, description


def detect_product_line(title: str, description: str) -> str:
    """Auto-detect product line from title and description text."""
    text = (title + " " + description).lower()

    # Product line keywords mapping
    keywords = {
        "康老板AI医生": ["ai医生", "ai健康", "人工智能医生", "智能医生"],
        "康老板健康": ["健康管理", "健康监测", "健康档案", "健康报告"],
        "康老板商城": ["商城", "商品", "购物", "订单", "支付"],
        "康店代理商": ["康店", "代理商", "代理", "经销商"],
        "康管家": ["康管家", "管家服务", "企业服务"],
        "旅途管家": ["旅途管家", "旅程管理", "出行管理"],
        "老板云": ["老板云", "老板中心", "企业管理云"],
        "老板帮": ["老板帮", "帮办", "商务帮"],
        "幸福绩效": ["幸福绩效", "绩效考核", "绩效管理", "kpi"],
        "飞联天下": ["飞联天下", "飞联", "联盟", "联合"],
        "创业天使": ["创业天使", "创业", "孵化", "创业扶持"],
        "会议系统": ["会议系统", "视频会议", "云会议", "远程会议", "会议管理"],
        "加速中心": ["加速中心", "加速", "赋能", "能力提升"],
        "数智化": ["数智化", "数字化", "数字化转型", "数智"],
        "自搭云": ["自搭云", "私有化", "自建", "本地部署"],
        "企座": ["企座", "客服系统", "呼叫中心", "客服中心"],
    }

    # Find the first matching product line
    for product_line, words in keywords.items():
        for word in words:
            if word in text:
                return product_line

    return ""


def scan_webapps() -> List[Dict[str, Any]]:
    """
    Scan ~/webapps/ for HTML files.
    - Root level: all .html files become projects
    - First-level folders: only index.html files become projects
    - Deeper nested files are ignored
    """
    files = []
    if not WEBAPPS_DIR.exists():
        return files

    # Get all items in webapps root
    for item in WEBAPPS_DIR.iterdir():
        # Skip hidden files/directories
        if item.name.startswith("."):
            continue

        if item.is_file() and item.name.lower().endswith(".html"):
            # Root level HTML file
            key = f"file:{item.name}"
            meta = metadata.get_file_meta(key) or {}

            # Skip sub-files
            if meta.get("parent_key"):
                continue

            title = meta.get("title") or item.name
            desc = meta.get("description") or ""
            uploader_ip = meta.get("uploader_ip")
            product_line = meta.get("product_line")

            # Auto-detect product line if not set
            if not product_line:
                try:
                    content = item.read_bytes()
                    html_title, html_desc = extract_html_title_description(content)
                    product_line = detect_product_line(html_title or title, html_desc or desc)
                except:
                    product_line = ""

            has_password = bool(meta.get("password"))
            versions_info = metadata.get_versions(key)
            current_version = versions_info.get("current_version", "V1")
            files.append({
                "key": key,
                "path": item.name,
                "title": title,
                "description": desc,
                "uploader_ip": uploader_ip,
                "upload_time": meta.get("upload_time"),
                "init_upload_time": (
                    meta.get("init_upload_time")
                    or (
                        min(
                            (v.get("upload_time") for v in meta.get("versions", {}).values() if v.get("upload_time")),
                            default=None
                        )
                    )
                    or meta.get("upload_time")
                ),
                "isDir": False,
                "url": f"/protected/{item.name}" if has_password else f"/files/{item.name}",
                "productLine": product_line,
                "hasPassword": has_password,
                "currentVersion": current_version,
            })

        elif item.is_dir():
            # First-level folder: only look for index.html
            index_file = item / "index.html"
            if index_file.exists():
                rel_path = index_file.relative_to(WEBAPPS_DIR)
                key = f"file:{rel_path.as_posix()}"
                meta = metadata.get_file_meta(key) or {}

                # Skip if marked as sub-file
                if meta.get("parent_key"):
                    continue

                # Extract metadata from index.html if not already set
                if not meta.get("title") or not meta.get("upload_time"):
                    try:
                        content = index_file.read_bytes()
                        title = extract_html_title_description(content)[0] or "index.html"
                        updates = {}
                        if not meta.get("title"):
                            updates["title"] = title
                            meta["title"] = title
                        if not meta.get("upload_time"):
                            import time
                            updates["upload_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
                            meta["upload_time"] = updates["upload_time"]
                        if updates:
                            # NOTE: previously this used a buggy one-liner that could
                            # wipe metadata.json down to a single entry when `key`
                            # wasn't yet present. touch_file_meta only updates the
                            # given key's fields and is a no-op if the key is absent
                            # (a fresh scan-time entry with no upload record yet is
                            # fine to leave unset here; it gets created properly on
                            # actual upload).
                            metadata.touch_file_meta(key, **updates)
                    except Exception:
                        pass

                title = meta.get("title") or "index.html"
                desc = meta.get("description") or ""
                uploader_ip = meta.get("uploader_ip")
                product_line = meta.get("product_line")

                # Auto-detect product line if not set - try from path first, then from HTML content
                if not product_line:
                    product_line = get_product_line(rel_path.as_posix())
                if not product_line:
                    try:
                        content = index_file.read_bytes()
                        html_title, html_desc = extract_html_title_description(content)
                        product_line = detect_product_line(html_title or title, html_desc or desc)
                    except:
                        pass

                has_password = bool(meta.get("password"))
                versions_info = metadata.get_versions(key)
                current_version = versions_info.get("current_version", "V1")
                files.append({
                    "key": key,
                    "path": rel_path.as_posix(),
                    "title": title,
                    "description": desc,
                    "uploader_ip": uploader_ip,
                    "upload_time": meta.get("upload_time"),
                    "init_upload_time": (
                        meta.get("init_upload_time")
                        or (
                            min(
                                (v.get("upload_time") for v in meta.get("versions", {}).values() if v.get("upload_time")),
                                default=None
                            )
                        )
                        or meta.get("upload_time")
                    ),
                    "isDir": False,
                    "url": f"/protected/{rel_path.as_posix()}" if has_password else f"/files/{rel_path.as_posix()}",
                    "productLine": product_line,
                    "hasPassword": has_password,
                    "currentVersion": current_version,
                })

    return sorted(files, key=lambda x: x["path"])


def upload_file(file_data: bytes, filename: str, uploader_ip: str) -> Tuple[bool, str, str]:
    """
    Save an uploaded HTML file to webapps directory.
    If the file already exists, archive the old content as a new version and
    save the new content to the original path.
    Returns (success, message, key)
    """
    if not filename.lower().endswith(".html"):
        return False, "只支持 HTML 文件", ""

    try:
        # Safe filename - prevent path traversal
        safe = safe_filename(filename)
        if not safe:
            return False, "无效的文件名", ""
        if not safe.lower().endswith(".html"):
            return False, "只支持 HTML 文件", ""
        dest_path = WEBAPPS_DIR / safe
        key = f"file:{safe}"

        # Check if file already exists (new version scenario)
        if dest_path.exists():
            # Archive old content as previous version
            old_content = dest_path.read_bytes()
            old_meta = metadata.get_file_meta(key)
            prev_version = old_meta.get("current_version", "V1") if old_meta else "V1"
            # Save old content to versions directory with version suffix
            version_filename = f"{safe}__{prev_version}"
            version_path = VERSIONS_DIR / version_filename
            version_path.write_bytes(old_content)
            # Add new version to metadata
            metadata.add_version(key, uploader_ip)

        # Write new content to original path
        dest_path.write_bytes(file_data)
        rel_path = dest_path.relative_to(WEBAPPS_DIR)
        key = f"file:{rel_path.as_posix()}"

        # Extract title and description from HTML content
        title, description = extract_html_title_description(file_data)

        # Use filename as title if no title found in HTML
        if not title:
            title = safe

        # Auto-detect product line from title and description
        product_line = detect_product_line(title, description)

        # Check if metadata already exists (new version vs new file)
        existing_meta = metadata.get_file_meta(key)
        if existing_meta:
            # Update existing metadata — upload_time tracks latest version upload
            # init_upload_time is preserved (first creation time)
            metadata.touch_file_meta(
                key,
                upload_time=datetime.now().isoformat(),
                uploader_ip=uploader_ip,
            )
        else:
            # Save new metadata
            metadata.set_file_meta(
                key=key,
                title=title,
                uploader_ip=uploader_ip,
                description=description,
                original_name=filename,
                product_line=product_line,
            )

        # Get current version number for success message
        versions_info = metadata.get_versions(key)
        current_v = versions_info.get("current_version", "V1")
        if dest_path.exists() and existing_meta:
            return True, f"已更新为 {current_v} 版本", key
        return True, f"已上传 {safe}", key
    except Exception as e:
        return False, f"上传失败: {str(e)}", ""


def _scan_zip_raw_names(zip_bytes: bytes) -> List[Tuple[str, bytes]]:
    """
    Scan a ZIP file's raw local file headers to recover (corrected_name,
    raw_name_bytes) pairs, trying UTF-8/GBK/CP437 in turn. Needed because
    zipfile's own decoding can garble non-ASCII (e.g. Chinese) filenames
    depending on which encoding flag the producing tool used.
    """
    import struct
    entries = []
    pos = 0
    while pos < len(zip_bytes) - 30:
        sig = struct.unpack('<I', zip_bytes[pos:pos + 4])[0]
        if sig != 0x04034b50:
            pos += 1
            continue
        try:
            fname_len = struct.unpack('<H', zip_bytes[pos + 26:pos + 28])[0]
            extra_len = struct.unpack('<H', zip_bytes[pos + 28:pos + 30])[0]
        except struct.error:
            pos += 1
            continue
        fname_start = pos + 30
        if fname_start + fname_len > len(zip_bytes):
            break
        fname_bytes = zip_bytes[fname_start:fname_start + fname_len]
        corrected = None
        for enc in ['utf-8', 'gbk', 'cp437']:
            try:
                corrected = fname_bytes.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if corrected is None:
            corrected = fname_bytes.decode('latin-1', errors='replace')
        entries.append((corrected, fname_bytes))
        pos = fname_start + fname_len + extra_len
    return entries


def _build_zip_name_mapping(zip_data: bytes) -> Dict[str, str]:
    """
    Build a mapping from "corrected" (properly decoded) entry names to the
    raw name zipfile.ZipFile actually uses internally, so callers can read
    entries by their human-readable (correct) name via zf.read(mapping[name]).
    Shared by extract_zip() (first upload) and extract_zip_for_version()
    (version update) so both handle Chinese/non-ASCII filenames identically.
    """
    import io
    with zipfile.ZipFile(io.BytesIO(zip_data), "r") as zf:
        zip_names = [info.filename for info in zf.infolist()]

    name_mapping: Dict[str, str] = {}
    for corrected_name, raw_bytes in _scan_zip_raw_names(zip_data):
        for zip_name in zip_names:
            for enc in ['utf-8', 'gbk', 'cp437', 'latin-1']:
                try:
                    if zip_name.encode(enc) == raw_bytes:
                        name_mapping[corrected_name] = zip_name
                        break
                except UnicodeEncodeError:
                    continue
            else:
                continue
            break
    return name_mapping


def extract_zip(zip_data: bytes, uploader_ip: str) -> Tuple[bool, str, List[str]]:
    """
    Extract a ZIP file to webapps directory.
    Returns (success, message, list of extracted keys - one key per ZIP project)
    """
    import io

    try:
        # Build mapping from corrected (properly decoded) names to zipfile's
        # own (possibly garbled) internal names.
        name_mapping = _build_zip_name_mapping(zip_data)

        # Now name_mapping has correct_utf8_name -> zipfile_garbled_name
        # Build the list of all corrected names
        all_names = [k for k in name_mapping.keys() if not k.endswith('/') and not k.startswith('__MACOSX/')]

        if not all_names:
            return False, "ZIP 文件为空", []

        # Check for index.html - either at root or in subfolder
        has_root_index = 'index.html' in all_names
        has_subfolder_index = any(n.endswith('/index.html') for n in all_names)

        # If neither exists, error
        if not has_root_index and not has_subfolder_index:
            return False, "未找到可运行的 index.html 文件", []

        # Determine base folder
        if has_root_index and not has_subfolder_index:
            from datetime import datetime
            base_folder = f"uploaded_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            base_prefix = ''
        else:
            first_file = next((n for n in all_names if not n.startswith('__MACOSX/') and '/' in n), '')
            base_folder = first_file.split('/')[0] if first_file else f"uploaded_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            base_prefix = base_folder + '/'

        extract_to = WEBAPPS_DIR / base_folder
        extract_to.mkdir(parents=True, exist_ok=True)

        # Extract files
        main_html_key = None

        with zipfile.ZipFile(io.BytesIO(zip_data), "r") as zf:
            for corrected_name in all_names:
                zipfile_name = name_mapping.get(corrected_name)
                if not zipfile_name:
                    continue

                clean = corrected_name.lstrip('/')

                # Strip base folder prefix if present
                if base_prefix and clean.startswith(base_prefix):
                    rel_path = clean[len(base_prefix):]
                elif not base_prefix:
                    rel_path = clean
                else:
                    rel_path = clean

                if not rel_path:
                    continue

                file_path = extract_to / rel_path
                # Zip Slip protection: ensure resolved path stays within extract_to
                try:
                    resolved = file_path.resolve()
                    if not str(resolved).startswith(str(extract_to.resolve())):
                        continue  # skip files that would escape extraction dir
                except (OSError, ValueError):
                    continue

                file_path.parent.mkdir(parents=True, exist_ok=True)

                try:
                    content = zf.read(zipfile_name)
                    file_path.write_bytes(content)
                except Exception as e:
                    pass

                # If this is index.html, set metadata
                if rel_path == 'index.html' or clean.endswith('/index.html'):
                    try:
                        content = file_path.read_bytes()
                        title, description = extract_html_title_description(content)
                        product_line = detect_product_line(title, description)
                        rel_path_key = file_path.relative_to(WEBAPPS_DIR)
                        key = f"file:{rel_path_key.as_posix()}"
                        metadata.set_file_meta(
                            key=key,
                            title=title or "index.html",
                            uploader_ip=uploader_ip,
                            description=description,
                            original_name="index.html",
                            product_line=product_line,
                        )
                        main_html_key = key
                    except:
                        pass

        if not main_html_key:
            for f in extract_to.rglob('index.html'):
                try:
                    content = f.read_bytes()
                    title, description = extract_html_title_description(content)
                    product_line = detect_product_line(title, description)
                    rel_path_key = f.relative_to(WEBAPPS_DIR)
                    key = f"file:{rel_path_key.as_posix()}"
                    metadata.set_file_meta(
                        key=key,
                        title=title or "index.html",
                        uploader_ip=uploader_ip,
                        description=description,
                        original_name="index.html",
                        product_line=product_line,
                    )
                    main_html_key = key
                    break
                except:
                    continue

        if not main_html_key:
            import shutil
            if extract_to.exists():
                shutil.rmtree(extract_to)
            return False, "未找到可运行的 index.html 文件", []

        return True, f"已解压到 {base_folder}/", [main_html_key]

    except zipfile.BadZipFile:
        return False, "无效的 ZIP 文件", []
    except Exception as e:
        return False, f"解压失败: {str(e)}", []


def extract_zip_for_version(zip_data: bytes, target_filename: str, uploader_ip: str) -> Tuple[bool, str, str]:
    """
    Extract a ZIP file and update an existing project as a new version.

    Unlike the old implementation (which only handled the single index.html
    entry, silently dropping every other file in the ZIP and never archiving
    them), this now operates on the WHOLE project directory:
      - For multi-file projects (target_filename like "somedir/index.html"),
        the entire project directory is archived as a .zip snapshot BEFORE
        being cleared and replaced with the full contents of the new ZIP.
        This means resource updates/additions/removals in the new ZIP all
        take effect, and the historical version can be fully restored later
        (images/CSS/JS included, not just the HTML).
      - For single-file root projects (target_filename like "example.html",
        no directory), behavior is unchanged: only the main HTML entry from
        the ZIP is used to overwrite the single file, archived the legacy
        (single-file) way for backward compatibility.

    Returns (success, message, key)
    """
    try:
        name_mapping = _build_zip_name_mapping(zip_data)
        all_names = [k for k in name_mapping.keys()
                     if not k.endswith('/') and not k.startswith('__MACOSX/')]
        if not all_names:
            return False, "ZIP 包内没有文件", ""

        # Locate the main HTML entry (prefer index.html, else first .html)
        main_entry = None
        for name in all_names:
            if name.lower() == 'index.html' or name.lower().endswith('/index.html'):
                main_entry = name
                break
        if not main_entry:
            for name in all_names:
                if name.lower().endswith('.html'):
                    main_entry = name
                    break
        if not main_entry:
            return False, "未找到 index.html 文件", ""

        key = f"file:{target_filename}"
        rel_path = Path(target_filename)
        is_multi_file_project = len(rel_path.parts) > 1

        with zipfile.ZipFile(__import__("io").BytesIO(zip_data)) as zf:
            main_content = zf.read(name_mapping[main_entry])
            title, description = extract_html_title_description(main_content)

            if is_multi_file_project:
                # ── Multi-file project: replace the ENTIRE project directory ──
                project_dir = (WEBAPPS_DIR / rel_path).parent
                success, msg = _replace_project_directory(
                    project_dir, key, zf, name_mapping, all_names, main_entry, uploader_ip
                )
                if not success:
                    return False, msg, ""
            else:
                # ── Single-file root project: unchanged legacy behavior ──
                current_path = WEBAPPS_DIR / target_filename
                if current_path.exists():
                    old_content = current_path.read_bytes()
                    old_meta = metadata.get_file_meta(key)
                    prev_version = old_meta.get("current_version", "V1") if old_meta else "V1"
                    _archive_path(target_filename, prev_version).write_bytes(old_content)
                    metadata.add_version(key, uploader_ip)
                current_path.write_bytes(main_content)

        # Update metadata (title/description autofill; preserve existing values)
        existing_meta = metadata.get_file_meta(key)
        if existing_meta:
            updates = {
                "upload_time": datetime.now().isoformat(),
                "uploader_ip": uploader_ip,
            }
            if not existing_meta.get("title") or title:
                updates["title"] = title or target_filename
            if not existing_meta.get("description"):
                updates["description"] = description or ""
            metadata.touch_file_meta(key, **updates)
        else:
            product_line = detect_product_line(title or target_filename, description or "")
            metadata.set_file_meta(
                key=key,
                title=title or target_filename,
                uploader_ip=uploader_ip,
                description=description or "",
                original_name=target_filename,
                product_line=product_line,
            )

        versions_info = metadata.get_versions(key)
        current_v = versions_info.get("current_version", "V1")
        return True, f"已更新为 {current_v} 版本", key

    except zipfile.BadZipFile:
        return False, "无效的 ZIP 文件", ""
    except Exception as e:
        return False, f"解压失败: {str(e)}", ""


def _replace_project_directory(project_dir: Path, key: str, zf: "zipfile.ZipFile",
                                name_mapping: Dict[str, str], all_names: List[str],
                                main_entry: str, uploader_ip: str) -> Tuple[bool, str]:
    """
    Archive the current project directory as a full .zip snapshot (if it
    exists), then clear it and write the ENTIRE contents of the new ZIP in
    its place. Used by extract_zip_for_version() for multi-file projects.

    The new ZIP's internal structure is stripped of its own base folder
    prefix (if any) the same way extract_zip() does for first-time uploads,
    so both entry points produce identically-shaped project directories.
    """
    filename = str(project_dir.relative_to(WEBAPPS_DIR).as_posix()) + "/index.html"

    # Archive the CURRENT directory content before touching anything, so a
    # failure partway through extraction never leaves us without a backup.
    if project_dir.exists() and any(project_dir.iterdir()):
        old_meta = metadata.get_file_meta(key)
        prev_version = old_meta.get("current_version", "V1") if old_meta else "V1"
        try:
            _zip_directory_to(project_dir, _archive_dir_path(filename, prev_version))
        except OSError as e:
            return False, f"归档旧版本失败: {e}"
        metadata.add_version(key, uploader_ip)

    # Determine the new ZIP's base-folder prefix to strip, mirroring
    # extract_zip()'s logic: if index.html sits inside a subfolder, that
    # subfolder is the "project root" and gets stripped; if index.html is at
    # the ZIP's own root, there's no prefix to strip.
    if '/' in main_entry:
        base_prefix = main_entry.rsplit('/', 1)[0] + '/'
    else:
        base_prefix = ''

    # Clear the existing directory contents (we already archived them above)
    # before writing the new ZIP's files, so removed/renamed files in the new
    # version don't linger as stale leftovers from the old version.
    if project_dir.exists():
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    for corrected_name in all_names:
        zipfile_name = name_mapping.get(corrected_name)
        if not zipfile_name:
            continue
        clean = corrected_name.lstrip('/')
        if base_prefix and clean.startswith(base_prefix):
            entry_rel_path = clean[len(base_prefix):]
        elif base_prefix:
            # Entry outside the detected base folder (e.g. stray root files)
            # — skip to avoid writing outside the project directory.
            continue
        else:
            entry_rel_path = clean
        if not entry_rel_path:
            continue

        file_path = project_dir / entry_rel_path
        try:
            resolved = file_path.resolve()
            if not str(resolved).startswith(str(project_dir.resolve())):
                continue  # Zip Slip protection
        except (OSError, ValueError):
            continue

        file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            file_path.write_bytes(zf.read(zipfile_name))
        except (KeyError, OSError):
            continue

    return True, "ok"


def _delete_all_archives(rel_path: str) -> None:
    """
    Remove every historical version archive belonging to a project,
    covering both the new full-directory zip format and the legacy
    single-file format. Best-effort: ignores individual file errors so a
    stray permission issue on one archive doesn't abort the whole delete.
    """
    stem = _archive_stem(rel_path)
    if not VERSIONS_DIR.exists():
        return
    for vf in VERSIONS_DIR.iterdir():
        if vf.is_file() and vf.name.startswith(stem + "__"):
            try:
                vf.unlink()
            except OSError:
                pass


def delete_file(key: str, request_ip: str) -> Tuple[bool, str]:
    """
    Delete a project if the request IP matches the uploader IP.

    For multi-file (directory) projects, the ENTIRE project directory is
    removed (not just index.html) so images/CSS/JS/sub-pages never linger
    as orphaned files with no way to clean them up. Single-file root
    projects keep the original behavior of deleting just that one file.
    All historical version archives for the project are removed as well.

    Returns (success, message)
    """
    if not key.startswith("file:"):
        return False, "无效的文件key"

    rel_path_str = key[5:]  # Remove "file:" prefix
    file_path = WEBAPPS_DIR / rel_path_str

    if not file_path.exists():
        return False, "文件不存在"

    # Check IP permission
    meta = metadata.get_file_meta(key)
    if not meta:
        # File exists on disk but no metadata - treat as no permission
        return False, "无权删除此文件"

    if meta.get("uploader_ip") != request_ip:
        return False, "无权删除：只能删除自己上传的文件"

    try:
        rel_path = Path(rel_path_str)
        is_multi_file_project = len(rel_path.parts) > 1

        if is_multi_file_project:
            # Remove the whole project directory, not just index.html, so
            # other resources (images/CSS/JS/sub-pages) don't get orphaned
            # on disk with metadata gone and no way to clean them up.
            project_dir = file_path.parent
            shutil.rmtree(project_dir, ignore_errors=True)
        else:
            file_path.unlink()
            # Remove now-empty parent directories, if any (kept for
            # single-file projects that might sit in a stray empty folder).
            parent = file_path.parent
            while parent != WEBAPPS_DIR:
                if not any(parent.iterdir()):
                    parent.rmdir()
                parent = parent.parent

        # Remove all historical version archives (new + legacy formats)
        _delete_all_archives(rel_path_str)

        # Remove metadata
        metadata.remove_file_meta(key)

        return True, "已删除"
    except Exception as e:
        return False, f"删除失败: {str(e)}"


def can_delete(key: str, request_ip: str) -> bool:
    """Check if a user can delete a file based on IP. Empty uploader_ip means file was set up by admin."""
    meta = metadata.get_file_meta(key)
    if not meta:
        return False
    stored_ip = meta.get("uploader_ip", "")
    # Empty uploader_ip means no IP restriction (admin-managed file)
    if not stored_ip:
        return True
    return stored_ip == request_ip


def update_file_version(key: str, file_data: bytes, uploader_ip: str) -> Tuple[bool, str, str]:
    """
    Update an EXISTING project with new single-HTML content as a new version.

    Unlike upload_file(), this preserves the project's real (possibly nested)
    path derived from its key, so subdirectory projects (e.g.
    file:uploaded_x/index.html) are updated in place instead of being written
    to the webapps root.

    For multi-file (directory) projects, uploading via this single-HTML entry
    point means the user's new version has ONLY that one file — so the whole
    project directory is archived as a full-directory zip snapshot first
    (preserving all prior images/CSS/JS for later restore), then the
    directory is cleared and replaced with just the new index.html. This
    mirrors extract_zip_for_version()'s directory-replacement semantics and
    avoids silently leaving stale resources from the previous (multi-file)
    version lying around next to a now-unrelated single HTML file.

    Returns (success, message, key).
    """
    if not key.startswith("file:"):
        return False, "无效的文件key", ""

    rel_path_str = key[5:]

    # Reject path traversal and ensure the resolved target stays inside WEBAPPS_DIR
    if ".." in rel_path_str:
        return False, "无效的文件路径", ""
    dest_path = (WEBAPPS_DIR / rel_path_str)
    try:
        resolved = dest_path.resolve()
        resolved.relative_to(WEBAPPS_DIR.resolve())
    except (ValueError, OSError):
        return False, "无效的文件路径", ""

    # Version update targets an existing project only
    if not dest_path.exists():
        return False, "文件不存在", ""

    try:
        rel_path = Path(rel_path_str)
        is_multi_file_project = len(rel_path.parts) > 1
        old_meta = metadata.get_file_meta(key)
        prev_version = old_meta.get("current_version", "V1") if old_meta else "V1"

        if is_multi_file_project:
            # Archive the WHOLE current project directory (not just
            # index.html) so other resources aren't silently lost.
            project_dir = dest_path.parent
            if project_dir.exists() and any(project_dir.iterdir()):
                _zip_directory_to(project_dir, _archive_dir_path(rel_path_str, prev_version))
            metadata.add_version(key, uploader_ip)
            # Clear the directory (old resources are safely archived above)
            # and write back only the new single HTML file.
            shutil.rmtree(project_dir, ignore_errors=True)
            project_dir.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(file_data)
        else:
            # Single-file root project — unchanged legacy behavior.
            old_content = dest_path.read_bytes()
            _archive_path(rel_path_str, prev_version).write_bytes(old_content)
            metadata.add_version(key, uploader_ip)
            dest_path.write_bytes(file_data)

        # Refresh metadata (preserve title/description/password/product_line)
        title, description = extract_html_title_description(file_data)
        current_meta = metadata.get_file_meta(key)
        if current_meta is not None:
            updates = {
                "upload_time": datetime.now().isoformat(),
                "uploader_ip": uploader_ip,
            }
            if not current_meta.get("title") and title:
                updates["title"] = title
            metadata.touch_file_meta(key, **updates)

        versions_info = metadata.get_versions(key)
        current_v = versions_info.get("current_version", "V1")
        return True, f"已更新为 {current_v} 版本", key
    except Exception as e:
        return False, f"版本更新失败: {str(e)}", ""


# ── Historical Version File Management ────────────────────────────────────────

def _archive_stem(filename: str) -> str:
    """
    Flatten a (possibly nested) relative filename into a safe, slash-free stem
    used for storing historical version archives in VERSIONS_DIR.

    e.g. "uploaded_x/index.html" -> "uploaded_x_index.html"
         "AIOPC_V3.3-.html"      -> "AIOPC_V3.3-.html"  (unchanged for root files,
                                    so existing archives stay compatible)
    """
    return filename.replace("/", "_")


def _archive_path(filename: str, version: str) -> Path:
    """Return the VERSIONS_DIR path for a given file/version archive
    (legacy single-file format — one HTML file only)."""
    return VERSIONS_DIR / f"{_archive_stem(filename)}__{version}"


def _archive_dir_path(filename: str, version: str) -> Path:
    """
    Return the VERSIONS_DIR path for a directory-project archive: a .zip
    snapshot of the ENTIRE project folder (index.html + all images/CSS/JS/
    sub-pages), used for multi-file ZIP-uploaded projects so version
    upgrades never silently drop or leave stale any non-index.html resource.
    """
    return VERSIONS_DIR / f"{_archive_stem(filename)}__{version}.zip"


def _zip_directory_to(src_dir: Path, zip_path: Path) -> None:
    """Zip up the entire contents of src_dir (relative paths preserved,
    only regular files) into zip_path."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(src_dir.rglob("*")):
            if file_path.is_file():
                zf.write(file_path, file_path.relative_to(src_dir).as_posix())


def is_directory_version(filename: str, version: str) -> bool:
    """Check whether a historical version was archived as a full-directory
    zip snapshot (new format) rather than a single-file archive (legacy)."""
    return _archive_dir_path(filename, version).exists()


def get_version_content(filename: str, version: str) -> Optional[bytes]:
    """
    Get the main HTML content of a historical version.
    Supports both:
      - the new full-directory zip archive format (multi-file projects):
        extracts the index.html entry from the snapshot
      - the legacy single-file archive format (root .html projects, and any
        pre-fix multi-file archives that only ever stored the main HTML)
    Returns bytes if found, None if not found.
    """
    # New format: directory zip snapshot -> extract its index.html
    dir_zip = _archive_dir_path(filename, version)
    if dir_zip.exists():
        try:
            with zipfile.ZipFile(dir_zip) as zf:
                basename = Path(filename).name
                if basename in zf.namelist():
                    return zf.read(basename)
                for name in zf.namelist():
                    if '/' not in name and name.lower().endswith('.html'):
                        return zf.read(name)
        except (zipfile.BadZipFile, KeyError, OSError):
            pass

    # Legacy single-file format
    version_path = _archive_path(filename, version)
    if version_path.exists():
        return version_path.read_bytes()

    legacy_path = VERSIONS_DIR / f"{filename}__{version}"
    if legacy_path.exists():
        return legacy_path.read_bytes()

    stem = _archive_stem(filename)
    for vf in VERSIONS_DIR.iterdir():
        if vf.is_file() and vf.name.startswith(stem) and vf.name.endswith(f"__{version}"):
            return vf.read_bytes()

    return None


def get_version_subresource(filename: str, version: str, subpath: str) -> Optional[bytes]:
    """
    Get a sub-resource (image/CSS/JS/sub-page) from a historical
    full-directory version archive.

    Returns None if:
      - the requested version wasn't archived in the new directory format
        (legacy single-file archives never had sub-resources to begin with,
        so there is nothing to serve — this is expected, not an error), or
      - the subpath doesn't exist within the archive.
    """
    if not subpath or '..' in subpath:
        return None
    dir_zip = _archive_dir_path(filename, version)
    if not dir_zip.exists():
        return None
    try:
        with zipfile.ZipFile(dir_zip) as zf:
            try:
                return zf.read(subpath)
            except KeyError:
                return None
    except (zipfile.BadZipFile, OSError):
        return None


def get_current_content(filename: str) -> Optional[bytes]:
    """Get the content of the current (latest) version of a file."""
    file_path = WEBAPPS_DIR / filename
    if file_path.exists():
        return file_path.read_bytes()
    return None


def restore_version_file(key: str, version: str, request_ip: str) -> Tuple[bool, str]:
    """
    Restore a historical version as the current version.

    For multi-file (directory) projects whose target version was archived
    in the new full-directory format, this restores the ENTIRE directory
    snapshot (all images/CSS/JS/sub-pages), not just index.html — so the
    restored project is fully self-consistent instead of mixing an old
    index.html with newer leftover resources.

    Returns (success, message).
    """
    if not can_delete(key, request_ip):
        return False, "无权恢复此版本"

    filename = key[5:] if key.startswith("file:") else key
    rel_path = Path(filename)
    is_multi_file_project = len(rel_path.parts) > 1
    project_dir = (WEBAPPS_DIR / rel_path).parent if is_multi_file_project else None

    current_meta = metadata.get_file_meta(key)
    if not current_meta:
        return False, "文件不存在"
    current_v = current_meta.get("current_version", "V1")

    if is_multi_file_project and is_directory_version(filename, version):
        # ── Full-directory restore ──
        # Archive the CURRENT directory before overwriting it.
        if project_dir.exists() and any(project_dir.iterdir()):
            try:
                _zip_directory_to(project_dir, _archive_dir_path(filename, current_v))
            except OSError as e:
                return False, f"归档当前版本失败: {e}"

        dir_zip = _archive_dir_path(filename, version)
        try:
            shutil.rmtree(project_dir, ignore_errors=True)
            project_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(dir_zip) as zf:
                zf.extractall(project_dir)
        except (zipfile.BadZipFile, OSError) as e:
            return False, f"恢复版本失败: {e}"

        ok, msg = metadata.restore_version(key, version)
        if not ok:
            return False, msg
        return True, f"已恢复为 {version} 版本"

    # ── Legacy single-file restore (root projects, or old archives that
    #    predate the directory-format fix) ──
    content = get_version_content(filename, version)

    current_content = get_current_content(filename)
    if current_content:
        _archive_path(filename, current_v).write_bytes(current_content)

    ok, msg = metadata.restore_version(key, version)
    if not ok:
        return False, msg

    if content is not None:
        file_path = WEBAPPS_DIR / filename
        file_path.write_bytes(content)

    return True, f"已恢复为 {version} 版本"


def delete_version_file(key: str, version: str, request_ip: str) -> Tuple[bool, str]:
    """
    Delete a historical version's archive (new directory-zip format or
    legacy single-file format, whichever exists).
    Returns (success, message).
    """
    # Check permission
    if not can_delete(key, request_ip):
        return False, "无权删除此版本"

    # Get filename from key
    filename = key[5:] if key.startswith("file:") else key

    # New format: full-directory zip snapshot
    dir_zip = _archive_dir_path(filename, version)
    if dir_zip.exists():
        try:
            dir_zip.unlink()
        except OSError as e:
            return False, f"删除版本文件失败: {str(e)}"
        return metadata.delete_version(key, version)

    # Legacy format: flattened single-file archive
    version_path = _archive_path(filename, version)

    # Fall back to legacy raw-name archive, then prefix match
    if not version_path.exists():
        legacy_path = VERSIONS_DIR / f"{filename}__{version}"
        if legacy_path.exists():
            version_path = legacy_path
        else:
            stem = _archive_stem(filename)
            for vf in VERSIONS_DIR.iterdir():
                if vf.is_file() and vf.name.startswith(stem) and vf.name.endswith(f"__{version}"):
                    version_path = vf
                    break

    if not version_path.exists():
        # No physical file, but remove from metadata
        return metadata.delete_version(key, version)

    try:
        version_path.unlink()
    except Exception as e:
        return False, f"删除版本文件失败: {str(e)}"

    # Remove from metadata
    return metadata.delete_version(key, version)
