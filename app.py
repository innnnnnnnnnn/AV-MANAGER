#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit
import requests
from bs4 import BeautifulSoup
import json
import time
import re
import os
from pathlib import Path
from urllib.parse import urljoin
import threading
from werkzeug.utils import secure_filename
import subprocess
import platform
from typing import Optional

app = Flask(__name__)
app.config['SECRET_KEY'] = 'av_scraper_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*")

# 全局變數來追蹤爬取狀態
crawl_status = {
    'is_running': False,
    'current_file': '',
    'progress': 0,
    'total': 0,
    'errors': []
}

# 存儲最後掃描的目錄
last_scanned_directory = None

# 預設掃描目錄
DEFAULT_SCAN_DIRECTORY = "/Volumes/BTAV"  # 預設SMB掛載目錄

def get_code_from_name(name: str) -> Optional[str]:
    """從檔名提取AV番號 - 支持多段橫槓、數字開頭以及帶有前綴的格式
    範例: hhd800.com@300MIUM-1259 -> 300MIUM-1259
          hhd800.com@FC2-PPV-4836416_1 -> FC2-PPV-4836416
    """
    # 1. 處理帶有 @ 的前綴 (如 hhd800.com@)
    if '@' in name:
        name = name.split('@')[-1]
    
    # 2. 嘗試匹配帶有橫槓的格式 (支持多段橫槓與數字開頭)
    # 規則: [英數] + [橫槓 + 英數](可重複) + [橫槓 + 數字]
    # 這可以匹配 300MIUM-1259 和 FC2-PPV-4836416
    pattern = re.compile(r"([A-Za-z0-9]+(?:-[A-Za-z0-9]+)*-\d+)", re.IGNORECASE)
    match = pattern.search(name)
    if match:
        return match.group(1).upper()
    
    # 3. 如果沒有找到帶橫槓的，嘗試匹配無連字符的格式 (例如 NHDTA073)
    # 需要至少2個字母和3個數字，並自動插入連字符
    pattern_no_dash = re.compile(r"([A-Za-z]{2,})(\d{3,})", re.IGNORECASE)
    match = pattern_no_dash.search(name)
    if match and match.group(1):
        letters = match.group(1)
        numbers = match.group(2)
        return f"{letters.upper()}-{numbers}"
    
    return None

def get_base_code(name: str) -> Optional[str]:
    """從檔名提取基礎AV番號（去掉a/b/c等後綴）
    例如: nhdtb-218a.mp4 -> NHDTB-218
    """
    code = get_code_from_name(name)
    if code:
        base_code = re.sub(r'[a-z]$', '', code, flags=re.IGNORECASE)
        return base_code
    return None

@app.route('/')
def index():
    return render_template('index.html', default_directory=DEFAULT_SCAN_DIRECTORY)

# DOM節點控制系統 - 靜態文件路由
@app.route('/tmp_rovodev_pagination_styles.css')
def serve_pagination_css():
    return send_from_directory('.', 'tmp_rovodev_pagination_styles.css', mimetype='text/css')

@app.route('/tmp_rovodev_integration.js')
def serve_integration_js():
    return send_from_directory('.', 'tmp_rovodev_integration.js', mimetype='application/javascript')

# 五大性能優化系統 - 靜態文件路由
@app.route('/tmp_rovodev_data_virtualization.js')
def serve_data_virtualization():
    return send_from_directory('.', 'tmp_rovodev_data_virtualization.js', mimetype='application/javascript')

@app.route('/tmp_rovodev_lazy_loading.js')
def serve_lazy_loading():
    return send_from_directory('.', 'tmp_rovodev_lazy_loading.js', mimetype='application/javascript')

@app.route('/tmp_rovodev_data_sharding.js')
def serve_data_sharding():
    return send_from_directory('.', 'tmp_rovodev_data_sharding.js', mimetype='application/javascript')

@app.route('/tmp_rovodev_memory_management.js')
def serve_memory_management():
    return send_from_directory('.', 'tmp_rovodev_memory_management.js', mimetype='application/javascript')

@app.route('/tmp_rovodev_resource_priority.js')
def serve_resource_priority():
    return send_from_directory('.', 'tmp_rovodev_resource_priority.js', mimetype='application/javascript')

@app.route('/covers/<path:filename>')
def serve_cover(filename):
    """提供封面圖片服務 - 從用戶選擇的目錄中搜尋封面"""
    global last_scanned_directory
    
    search_paths = []
    
    # 優先使用最後掃描的目錄
    if last_scanned_directory and Path(last_scanned_directory).exists():
        search_paths.append(Path(last_scanned_directory))
    
    # 添加當前目錄作為備用
    search_paths.append(Path.cwd())
    
    for base_path in search_paths:
        if not base_path.exists():
            continue
            
        # 遞歸搜尋封面檔案
        for cover_file in base_path.rglob(filename):
            if cover_file.is_file():
                return send_from_directory(str(cover_file.parent), cover_file.name)
    
    # 如果找不到封面，返回預設的placeholder
    return send_from_directory('static', 'placeholder.jpg')

@app.route('/video/<path:av_code>')
def serve_video(av_code):
    """提供影片檔案服務 - 從用戶選擇的目錄中搜尋影片"""
    global last_scanned_directory
    
    search_paths = []
    
    # 優先使用最後掃描的目錄
    if last_scanned_directory and Path(last_scanned_directory).exists():
        search_paths.append(Path(last_scanned_directory))
    
    # 添加當前目錄作為備用
    search_paths.append(Path.cwd())
    
    video_extensions = [".mp4", ".avi", ".mkv", ".DIVX"]
    
    for base_path in search_paths:
        if not base_path.exists():
            continue
            
        # 搜尋影片檔案
        for ext in video_extensions:
            # 搜尋番號資料夾中的影片
            for video_file in base_path.rglob(f"{av_code}{ext}"):
                if video_file.is_file():
                    print(f"[DEBUG] 找到影片檔案: {video_file}")
                    return send_from_directory(str(video_file.parent), video_file.name)
            
            # 搜尋任何包含番號的影片檔案
            for video_file in base_path.rglob(f"*{av_code}*{ext}"):
                if video_file.is_file():
                    print(f"[DEBUG] 找到影片檔案: {video_file}")
                    return send_from_directory(str(video_file.parent), video_file.name)
    
    # 如果找不到影片檔案，返回404
    return "影片檔案未找到", 404

@app.route('/api/scan', methods=['POST'])
def start_scan():
    """啟動掃描和爬取"""
    global crawl_status
    
    if crawl_status['is_running']:
        return jsonify({'error': '掃描已在進行中'}), 400
    
    data = request.get_json()
    directory = data.get('directory')
    overwrite_nfo = data.get('overwrite_nfo', False)
    
    if not directory:
        return jsonify({'error': '請先選擇要掃描的目錄'}), 400
    
    # 啟動後台執行緒
    thread = threading.Thread(target=scan_and_crawl, args=(directory, overwrite_nfo))
    thread.daemon = True
    thread.start()
    
    return jsonify({'message': '掃描已啟動', 'directory': directory})

@app.route('/api/quick_load', methods=['POST'])
def start_quick_load():
    """快速載入已有封面和NFO的影片"""
    global crawl_status
    
    if crawl_status['is_running']:
        return jsonify({'error': '載入已在進行中'}), 400
    
    data = request.get_json()
    directory = data.get('directory')
    
    if not directory:
        return jsonify({'error': '請先選擇要載入的目錄'}), 400
    
    # 啟動後台執行緒
    thread = threading.Thread(target=quick_load_videos, args=(directory,))
    thread.daemon = True
    thread.start()
    
    return jsonify({'message': '快速載入已啟動', 'directory': directory})

def fetch_javcup_info(code: str) -> Optional[dict]:
    """獲取JavCup資訊"""
    global crawl_status
    
    # 在網絡請求前檢查停止狀態
    if not crawl_status['is_running']:
        return None
    
    url = f"https://javcup.com/movie/{code}"
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        r = requests.get(url, headers=headers, timeout=5)
        
        # 網絡請求後立即檢查停止狀態
        if not crawl_status['is_running']:
            return None
            
        r.raise_for_status()
    except:
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    title = ""
    if soup.title:
        title = soup.title.text.split(" - JavCup")[0].strip()

    info = {}
    info_list = soup.select_one("ul.information")
    if info_list:
        for li in info_list.find_all("li"):
            span = li.find("span")
            if span:
                # 同時處理半形冒號 ":" 和全形冒號 "："
                key = span.text.strip().rstrip(":").rstrip("：").strip()
                value = ""
                # 女優欄位：支援繁中「演出者」和日文「出演者」
                if key in ["演出者", "出演者"]:
                    models = [a.text.strip() for a in li.select("a.model")]
                    # 嘗試從 .model-item 裡的 span 抓名字
                    if not models:
                        for item in li.select(".model-item a"):
                            name_span = item.find("span")
                            if name_span and name_span.text.strip():
                                models.append(name_span.text.strip())
                    # 最後 fallback：找所有連結文字
                    if not models:
                        models = [a.text.strip() for a in li.find_all("a") if a.text.strip()]
                    value = " / ".join(models) if models else ""
                    info["演出者"] = value  # 統一存成「演出者」key
                    continue
                else:
                    raw = li.get_text(strip=True)
                    # 移除 key + 冒號（半形或全形）
                    value = raw.replace(key + ":", "").replace(key + "：", "").strip()
                info[key] = value

    genres = [t.get_text(strip=True) for t in soup.select(".chip.tag-item") if t.get_text(strip=True)]

    description = ""
    desc_p = soup.select_one(".movie-description p.description")
    if desc_p:
        description = desc_p.get_text(strip=True)

    cover_url = None
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        cover_url = og["content"]

    # 檢查是否為JavCup的預設頁面（找不到影片時的預設內容）
    if title in ["映画作品", "人気作品"] or info.get("出演者", "") == "日泉舞華":
        print(f"[DEBUG] 檢測到JavCup預設頁面，視為找不到資訊: title={title}, 出演者={info.get('出演者', '')}")
        return None  # 返回None表示找不到資訊
    
    return {
        "title": title,
        # 支援繁體中文欄位名（新）和日文欄位名（舊）
        "出演者": info.get("演出者", "") or info.get("出演者", ""),
        "片長": info.get("片長", "") or info.get("収録時間", ""),
        "發行日期": info.get("商品發售日", "") or info.get("商品発売日", ""),
        "導演": info.get("導演", "") or info.get("監督", ""),
        "製片": info.get("發行商", "") or info.get("メーカー", ""),
        "系列": info.get("系列", "") or info.get("シリーズ", ""),
        "類型": " / ".join(genres),
        "簡介": description,
        "cover_url": cover_url
    }

def create_nfo_xml_web(data: dict, code: str) -> str:
    """創建NFO XML內容 - 修復版本，找不到資訊時留空白"""
    import xml.etree.ElementTree as ET
    from xml.dom import minidom
    
    movie = ET.Element("movie")
    
    # 如果沒有數據，創建NFO並標記演員為N/A
    if not data:
        ET.SubElement(movie, "title").text = ""
        ET.SubElement(movie, "plot").text = ""
        ET.SubElement(movie, "runtime").text = ""
        ET.SubElement(movie, "premiered").text = ""
        ET.SubElement(movie, "studio").text = ""
        ET.SubElement(movie, "director").text = ""
        ET.SubElement(movie, "num").text = code
        # 添加NA演員，方便篩選
        actor = ET.SubElement(movie, "actor")
        ET.SubElement(actor, "name").text = "NA"
    else:
        # Basic movie info
        ET.SubElement(movie, "title").text = data.get("title", "")
        ET.SubElement(movie, "plot").text = data.get("簡介", "")
        ET.SubElement(movie, "runtime").text = data.get("片長", "").replace("分", "")
        ET.SubElement(movie, "premiered").text = data.get("發行日期", "")
        ET.SubElement(movie, "studio").text = data.get("製片", "")
        ET.SubElement(movie, "director").text = data.get("導演", "")
        ET.SubElement(movie, "num").text = code
        
        # Actors - 只有當有演員資訊時才添加
        actors = data.get("出演者", "").split(" / ")
        for actor_name in actors:
            if actor_name and actor_name.strip():
                actor = ET.SubElement(movie, "actor")
                ET.SubElement(actor, "name").text = actor_name.strip()
        
        # Genres - 只有當有類型資訊時才添加
        genres = data.get("類型", "").split(" / ")
        for genre_name in genres:
            if genre_name.strip():
                ET.SubElement(movie, "genre").text = genre_name.strip()
        
        # Set/Series
        if data.get("系列"):
            ET.SubElement(movie, "set").text = data["系列"]
    
    # Convert to pretty XML string
    rough_string = ET.tostring(movie, encoding='unicode')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ", encoding=None)[23:]  # Remove XML declaration

def quick_load_videos(directory):
    """快速載入已有封面和NFO的影片"""
    global crawl_status, last_scanned_directory
    
    crawl_status['is_running'] = True
    crawl_status['errors'] = []
    crawl_status['progress'] = 0
    
    try:
        socketio.emit('crawl_status', crawl_status)
        socketio.emit('crawl_info', {'message': '正在載入已有資料...'})
        
        base_path = Path(directory)
        last_scanned_directory = str(base_path)
        
        if not base_path.exists():
            error_msg = f"資料夾不存在: {base_path}"
            crawl_status['errors'].append(error_msg)
            socketio.emit('crawl_error', {'message': error_msg})
            crawl_status['is_running'] = False
            return
        
        # 影片副檔名
        video_extensions = {".mp4", ".avi", ".mkv", ".DIVX"}
        
        # 快速計算有完整資料的影片數量
        def count_complete_videos(path, depth=0):
            count = 0
            if depth > 10:
                return count
            
            # 檢查停止狀態
            if not crawl_status['is_running']:
                return count
                
            try:
                for item in path.iterdir():
                    if not crawl_status['is_running']:
                        return count
                        
                    if item.is_dir():
                        code = get_code_from_name(item.name)
                        if code:
                            # 檢查是否有NFO和封面
                            nfo_path = item / f"{code}.nfo"
                            cover_path = item / f"{code}.jpg"
                            if nfo_path.exists():
                                count += 1
                        else:
                            count += count_complete_videos(item, depth + 1)
            except (PermissionError, OSError):
                pass
            return count
        
        total_items = count_complete_videos(base_path)
        socketio.emit('crawl_info', {'message': f'發現 {total_items} 個完整影片'})
        
        if total_items == 0:
            socketio.emit('crawl_complete', {
                'message': '未找到任何完整的影片資料（需要有NFO）',
                'total': 0,
                'processed': 0
            })
            crawl_status['is_running'] = False
            return
        
        count = 0
        
        def load_complete_videos(path, depth=0):
            nonlocal count
            
            if depth > 10:
                return
            
            # 檢查停止狀態
            if not crawl_status['is_running']:
                return
            
            try:
                for item in path.iterdir():
                    if not crawl_status['is_running']:
                        return
                        
                    if item.is_dir():
                        code = get_code_from_name(item.name)
                        if code:
                            # 檢查是否有NFO和封面
                            nfo_path = item / f"{code}.nfo"
                            cover_path = item / f"{code}.jpg"
                            
                            if nfo_path.exists():
                                # 在處理每個影片前檢查停止狀態
                                if not crawl_status['is_running']:
                                    return
                                
                                count += 1
                                
                                # 讀取NFO檔案獲取資料
                                try:
                                    # 在讀取NFO前檢查停止狀態
                                    if not crawl_status['is_running']:
                                        socketio.emit('crawl_info', {'message': f'⏹️ 已停止載入 {code}'})
                                        return
                                    
                                    import xml.etree.ElementTree as ET
                                    tree = ET.parse(nfo_path)
                                    root_elem = tree.getroot()
                                    
                                    # 在XML解析後檢查停止狀態
                                    if not crawl_status['is_running']:
                                        socketio.emit('crawl_info', {'message': f'⏹️ 已停止處理 {code} NFO'})
                                        return
                                    
                                    def get_text_or_empty(element):
                                        if element is not None and element.text and element.text.strip():
                                            return element.text.strip()
                                        return ''
                                    
                                    # 獲取演員列表，過濾空白名稱
                                    actors = []
                                    for actor in root_elem.findall('actor'):
                                        # 在處理每個演員前檢查停止狀態
                                        if not crawl_status['is_running']:
                                            return
                                        name_elem = actor.find('name')
                                        if name_elem is not None and name_elem.text and name_elem.text.strip():
                                            actors.append(name_elem.text.strip())
                                    
                                    # 獲取類型列表，過濾空白類型
                                    genres = []
                                    for genre in root_elem.findall('genre'):
                                        # 在處理每個類型前檢查停止狀態
                                        if not crawl_status['is_running']:
                                            return
                                        if genre.text and genre.text.strip():
                                            genres.append(genre.text.strip())
                                    
                                    # 在準備資料前再次檢查停止狀態
                                    if not crawl_status['is_running']:
                                        socketio.emit('crawl_info', {'message': f'⏹️ 已停止準備 {code} 資料'})
                                        return
                                    
                                    # 準備發送給前端的資料
                                    video_data = {
                                        'av_code': code,
                                        'title': get_text_or_empty(root_elem.find('title')),
                                        'file_path': str(item),
                                        'has_nfo': True,
                                        'has_cover': True,
                                        'local_cover': f"/covers/{code}.jpg",
                                        'cover_url': f"/covers/{code}.jpg",
                                        '出演者': ', '.join(actors) if actors else '',
                                        '片長': get_text_or_empty(root_elem.find('runtime')),
                                        '發行日期': get_text_or_empty(root_elem.find('premiered')),
                                        '導演': get_text_or_empty(root_elem.find('director')),
                                        '製片': get_text_or_empty(root_elem.find('studio')),
                                        '系列': get_text_or_empty(root_elem.find('set')),
                                        '類型': ' / '.join(genres) if genres else '',
                                        '簡介': get_text_or_empty(root_elem.find('plot'))
                                    }
                                    
                                    # 在發送前再次檢查停止狀態
                                    if not crawl_status['is_running']:
                                        return
                                    
                                    # 發送到前端
                                    socketio.emit('crawl_success', {
                                        'message': f'✅ 已載入 {code}',
                                        'data': video_data
                                    })
                                    
                                    # 在發送進度前最後檢查停止狀態
                                    if not crawl_status['is_running']:
                                        socketio.emit('crawl_info', {'message': f'⏹️ 已停止發送進度 {code}'})
                                        return
                                    
                                    # 發送進度
                                    percentage = int((count / total_items) * 100)
                                    socketio.emit('crawl_progress', {
                                        'current': count,
                                        'total': total_items,
                                        'successful': count,
                                        'percentage': percentage,
                                        'file': code,
                                        'action': f'已載入 {code}'
                                    })
                                    
                                    # 發送進度後檢查停止狀態
                                    if not crawl_status['is_running']:
                                        socketio.emit('crawl_info', {'message': f'⏹️ 已停止載入過程'})
                                        return
                                    
                                except Exception as e:
                                    print(f"[DEBUG] 讀取NFO失敗: {code} - {e}")
                                    continue
                        else:
                            load_complete_videos(item, depth + 1)
            except (PermissionError, OSError):
                pass
        
        # 開始載入
        load_complete_videos(base_path)
        
        # 載入完成
        if crawl_status['is_running']:
            crawl_status['is_running'] = False
            socketio.emit('crawl_complete', {
                'message': f'✅ 載入完成，載入 {count} 部影片',
                'total': total_items,
                'processed': count
            })
        
    except Exception as e:
        crawl_status['is_running'] = False
        error_msg = f"載入過程發生錯誤: {str(e)}"
        crawl_status['errors'].append(error_msg)
        socketio.emit('crawl_error', {'message': error_msg})
    finally:
        crawl_status['is_running'] = False

def scan_and_crawl(directory, overwrite_nfo=False):
    """掃描目錄並爬取資料的主要函數 - 完全修復版本"""
    global crawl_status, last_scanned_directory
    
    crawl_status['is_running'] = True
    crawl_status['errors'] = []
    crawl_status['progress'] = 0
    
    try:
        socketio.emit('crawl_status', crawl_status)
        socketio.emit('crawl_info', {'message': '正在初始化掃描...'})
        
        base_path = Path(directory)
        last_scanned_directory = str(base_path)
        
        if not base_path.exists():
            error_msg = f"資料夾不存在: {base_path}"
            crawl_status['errors'].append(error_msg)
            socketio.emit('crawl_error', {'message': error_msg})
            crawl_status['is_running'] = False
            return
        
        socketio.emit('crawl_info', {'message': '開始遞歸掃描資料夾...'})
        
        # 影片副檔名
        video_extensions = {".mp4", ".avi", ".mkv", ".DIVX"}
        
        count = 0
        skip_count = 0
        total_items = 0
        
        # 遞歸計算總數
        def count_items_recursive(path, depth=0):
            count = 0
            if depth > 10:  # 防止過深的遞歸
                return count
                
            try:
                for item in path.iterdir():
                    if not crawl_status['is_running']:
                        break
                        
                    if item.is_dir():
                        code = get_code_from_name(item.name)
                        if code:
                            count += 1
                        else:
                            # 遞歸掃描子資料夾
                            count += count_items_recursive(item, depth + 1)
                    elif item.is_file() and item.suffix.lower() in video_extensions:
                        code = get_code_from_name(item.stem)
                        if code:
                            count += 1
            except (PermissionError, OSError):
                pass
            return count
        
        total_items = count_items_recursive(base_path)
        crawl_status['total'] = total_items
        socketio.emit('crawl_info', {'message': f'發現 {total_items} 個可處理項目'})
        
        if total_items == 0:
            error_msg = "未找到任何影片檔案或可處理的項目"
            crawl_status['errors'].append(error_msg)
            socketio.emit('crawl_error', {'message': error_msg})
            crawl_status['is_running'] = False
            return
        
        processed = 0  # 掃描進度（不論成功失敗）
        successful = 0  # 成功處理數（有封面+NFO）
        sent_base_codes = set()  # 追蹤已發送給前端的基礎番號，避免重複卡片
        
        # 發送初始進度
        socketio.emit('crawl_progress', {
            'current': 0,
            'total': total_items,
            'successful': 0,
            'file': '',
            'action': '開始掃描'
        })
        
        # 遞歸處理所有層級的資料夾
        def process_items_recursive(path, depth=0):
            nonlocal processed, count, skip_count, successful, sent_base_codes
            
            if depth > 10:  # 防止過深的遞歸
                return
            
            # 檢查停止狀態
            if not crawl_status['is_running']:
                return
            
            try:
                for item in path.iterdir():
                    # 在每個項目處理前都檢查停止狀態
                    if not crawl_status['is_running']:
                        return
                        
                    code = None
                    folder = None
                    
                    if item.is_dir():
                        code = get_code_from_name(item.name)
                        if code:
                            folder = item
                        else:
                            # 遞歸掃描子資料夾
                            process_items_recursive(item, depth + 1)
                            continue
                    elif item.is_file() and item.suffix.lower() in video_extensions:
                        code = get_code_from_name(item.stem)
                        if code:
                            # 創建番號資料夾
                            code_folder = path / code
                            if not code_folder.exists():
                                code_folder.mkdir()
                                socketio.emit('crawl_info', {'message': f'✓ 已建立番號資料夾: {code}'})
                            
                            # 移動影片檔案到番號資料夾
                            new_video_path = code_folder / item.name
                            if not new_video_path.exists():
                                item.rename(new_video_path)
                                socketio.emit('crawl_info', {'message': f'✓ 已移動影片到: {code}/'})
                            
                            folder = code_folder
                    
                    if not code or not folder:
                        continue
                    
                    # 記錄當前處理的檔案
                    crawl_status['current_file'] = code
                    processed += 1  # 掃描進度+1
                    
                    # 檢查檔案路徑
                    nfo_path = folder / f"{code}.nfo"
                    cover_path = folder / f"{code}.jpg"
                    
                    # 檢查封面和NFO是否存在
                    has_nfo = nfo_path.exists()
                    has_cover = cover_path.exists()
                    
                    # 檢查是否為完整影片（有影片、NFO、封面）
                    has_video = any((folder / f"{code}{ext}").exists() for ext in ['.mp4', '.avi', '.mkv', '.DIVX'])
                    
                    if not overwrite_nfo and has_cover and has_nfo and has_video:
                        socketio.emit('crawl_info', {'message': f'載入現有完整資料 → {code}'})
                        
                        # NFO已存在，直接從本地NFO讀取資料，不再重新爬取網路
                        try:
                            import xml.etree.ElementTree as ET
                            tree = ET.parse(nfo_path)
                            root_elem = tree.getroot()
                            
                            def get_text_or_empty(element):
                                if element is not None and element.text and element.text.strip():
                                    return element.text.strip()
                                return ''
                            
                            # 讀取演員列表
                            actors = []
                            for actor in root_elem.findall('actor'):
                                name_elem = actor.find('name')
                                if name_elem is not None and name_elem.text and name_elem.text.strip():
                                    name = name_elem.text.strip()
                                    if name != 'NA':  # 過濾佔位符
                                        actors.append(name)
                            
                            # 讀取類型列表
                            genres = []
                            for genre in root_elem.findall('genre'):
                                if genre.text and genre.text.strip():
                                    genres.append(genre.text.strip())
                            
                            video_data = {
                                'av_code': code,
                                'title': get_text_or_empty(root_elem.find('title')),
                                'file_path': str(folder),
                                'has_nfo': True,
                                'has_cover': True,
                                'local_cover': f"/covers/{code}.jpg",
                                'cover_url': f"/covers/{code}.jpg",
                                '出演者': ', '.join(actors) if actors else '',
                                '片長': get_text_or_empty(root_elem.find('runtime')),
                                '發行日期': get_text_or_empty(root_elem.find('premiered')),
                                '導演': get_text_or_empty(root_elem.find('director')),
                                '製片': get_text_or_empty(root_elem.find('studio')),
                                '系列': get_text_or_empty(root_elem.find('set')),
                                '類型': ' / '.join(genres) if genres else '',
                                '簡介': get_text_or_empty(root_elem.find('plot'))
                            }
                        except Exception as e:
                            print(f"[DEBUG] 讀取NFO失敗: {code} - {e}")
                            video_data = {
                                'av_code': code,
                                'title': '',
                                'file_path': str(folder),
                                'has_nfo': True,
                                'has_cover': True,
                                'local_cover': f"/covers/{code}.jpg",
                                'cover_url': f"/covers/{code}.jpg",
                                '出演者': '',
                                '片長': '',
                                '發行日期': '',
                                '導演': '',
                                '製片': '',
                                '系列': '',
                                '類型': '',
                                '簡介': ''
                            }
                        
                        socketio.emit('crawl_success', {
                            'message': f'✅ 載入完整資料 {code}',
                            'data': video_data
                        })
                        
                        # 成功處理數+1
                        successful += 1
                        
                        # 發送進度更新
                        percentage = int((processed / total_items) * 100)
                        socketio.emit('crawl_progress', {
                            'current': processed,
                            'total': total_items,
                            'successful': successful,
                            'percentage': percentage,
                            'file': code,
                            'action': f'已載入 {code}'
                        })
                        continue
                    
                    # 處理沒有封面或沒有NFO的情況
                    socketio.emit('crawl_info', {'message': f'正在處理 {code}...'})
                    
                    # 再次檢查停止狀態（在網絡請求前）
                    if not crawl_status['is_running']:
                        return
                    
                    # 獲取資訊
                    data = fetch_javcup_info(code)
                    
                    # 網絡請求後立即檢查停止狀態
                    if not crawl_status['is_running']:
                        socketio.emit('crawl_info', {'message': f'⏹️ 已停止處理 {code}'})
                        return
                    
                    # 如果 NFO 不存在或者是設定為覆寫模式
                    if not has_nfo or overwrite_nfo:
                        nfo_content = create_nfo_xml_web(data, code)
                        with open(nfo_path, "w", encoding="utf-8") as f:
                            f.write(nfo_content)
                        msg = f'✓ 已生成 {code} 的NFO檔案' if not has_nfo else f'✓ 已覆寫 {code} 的NFO檔案'
                        socketio.emit('crawl_info', {'message': msg})
                    else:
                        socketio.emit('crawl_info', {'message': f'⚠ {code} NFO已存在，跳過生成'})
                    
                    # 如果沒有封面且有封面URL，才下載封面
                    if not has_cover and data and data.get("cover_url"):
                        # 在下載前檢查停止狀態
                        if not crawl_status['is_running']:
                            socketio.emit('crawl_info', {'message': f'⏹️ 已停止下載 {code} 封面'})
                            return
                        try:
                            headers = {
                                "User-Agent": "Mozilla/5.0",
                                "Referer": f"https://javcup.com/movie/{code}"
                            }
                            r = requests.get(data["cover_url"], headers=headers, timeout=5)
                            # 下載後立即檢查停止狀態
                            if not crawl_status['is_running']:
                                socketio.emit('crawl_info', {'message': f'⏹️ 已停止處理 {code} 封面'})
                                return
                            if r.status_code == 200:
                                with open(cover_path, "wb") as f:
                                    f.write(r.content)
                                socketio.emit('crawl_info', {'message': f'✓ 已下載 {code} 封面'})
                        except:
                            socketio.emit('crawl_info', {'message': f'⚠️ {code} 封面下載失敗'})
                    elif has_cover:
                        socketio.emit('crawl_info', {'message': f'⚠ {code} 封面已存在，跳過下載'})
                    
                    # 只有首次見到該基礎番號時才發送給前端，避免重複卡片
                    base_code = get_base_code(code)
                    if base_code and base_code not in sent_base_codes:
                        sent_base_codes.add(base_code)
                        
                        # 準備發送給前端的資料
                        video_data = {
                            'av_code': base_code,
                            'title': data.get('title', '') if data else '',
                            'file_path': str(folder),
                            'has_nfo': nfo_path.exists(),
                            'has_cover': cover_path.exists(),
                            'local_cover': f"/covers/{base_code}.jpg" if cover_path.exists() else None,
                            'cover_url': f"/covers/{base_code}.jpg" if cover_path.exists() else None,
                            '出演者': data.get('出演者', '') if data else 'NA',
                            '片長': data.get('片長', '') if data else '',
                            '發行日期': data.get('發行日期', '') if data else '',
                            '導演': data.get('導演', '') if data else '',
                            '製片': data.get('製片', '') if data else '',
                            '系列': data.get('系列', '') if data else '',
                            '類型': data.get('類型', '') if data else '',
                            '簡介': data.get('簡介', '') if data else ''
                        }
                        
                        # 發送處理結果到前端
                        socketio.emit('crawl_success', {
                            'message': f'✅ 成功處理 {base_code}',
                            'data': video_data
                        })
                    
                    # 檢查是否成功獲得封面+NFO
                    final_has_nfo = nfo_path.exists()
                    final_has_cover = cover_path.exists()
                    
                    if final_has_nfo and final_has_cover:
                        successful += 1
                    
                    # 發送進度更新（掃描進度和成功處理數）
                    percentage = int((processed / total_items) * 100)
                    socketio.emit('crawl_progress', {
                        'current': processed,
                        'total': total_items,
                        'successful': successful,
                        'percentage': percentage,
                        'file': code,
                        'action': f'已處理 {code}' if final_has_nfo and final_has_cover else f'處理失敗 {code}'
                    })
                    
                    # 防ban延遲
                    time.sleep(1.2)
                    
            except (PermissionError, OSError):
                pass
        
        
        # 開始遞歸處理
        process_items_recursive(base_path)
        
        # 掃描完成
        if crawl_status['is_running']:
            crawl_status['is_running'] = False
            socketio.emit('crawl_complete', {
                'message': f'✅ 完成，共處理 {successful} 筆，跳過 {skip_count} 筆',
                'total': total_items,
                'processed': successful,  # 使用成功處理數
                'skipped': skip_count
            })
        
    except Exception as e:
        crawl_status['is_running'] = False
        error_msg = f"掃描過程發生錯誤: {str(e)}"
        crawl_status['errors'].append(error_msg)
        socketio.emit('crawl_error', {'message': error_msg})
    finally:
        crawl_status['is_running'] = False

@app.route('/api/test_path', methods=['POST'])
def test_path():
    """测试路径是否存在和可访问"""
    data = request.get_json()
    directory = data.get('directory')
    
    print(f"[DEBUG] 测试路径: {directory}")
    
    if not directory:
        return jsonify({'error': '路径为空'}), 400
    
    path = Path(directory)
    print(f"[DEBUG] Path对象: {path}")
    print(f"[DEBUG] 路径存在: {path.exists()}")
    print(f"[DEBUG] 是目录: {path.is_dir() if path.exists() else 'N/A'}")
    
    if not path.exists():
        return jsonify({'error': f'路径不存在: {path}'}), 400
    
    if not path.is_dir():
        return jsonify({'error': f'不是目录: {path}'}), 400
    
    try:
        # 尝试列出目录内容
        items = list(path.iterdir())
        print(f"[DEBUG] 目录项目数: {len(items)}")
        
        # 遞歸統計影片檔案
        video_extensions = {".mp4", ".avi", ".mkv", ".DIVX"}
        
        def count_videos_recursive(path, depth=0):
            video_count = 0
            if depth > 10:  # 防止過深的遞歸
                return video_count
                
            try:
                for item in path.iterdir():
                    if item.is_dir():
                        # 檢查是否為番號資料夾
                        code = get_code_from_name(item.name)
                        if code:
                            video_count += 1
                            print(f"[DEBUG] 发现番号目录: {item.name}")
                        else:
                            # 遞歸掃描子資料夾
                            video_count += count_videos_recursive(item, depth + 1)
                    elif item.is_file() and item.suffix.lower() in video_extensions:
                        code = get_code_from_name(item.stem)
                        if code:
                            video_count += 1
                            print(f"[DEBUG] 发现视频文件: {item.name}")
            except (PermissionError, OSError):
                pass
            return video_count
        
        total_videos = count_videos_recursive(path)
        
        return jsonify({
            'message': f'路径有效，包含 {total_videos} 個影片',
            'total_items': len(items),
            'folder_count': total_videos,  # 為了兼容前端，使用folder_count字段
            'video_files': total_videos
        })
        
    except PermissionError:
        return jsonify({'error': '权限不足，无法访问目录'}), 403
    except Exception as e:
        print(f"[DEBUG] 测试路径异常: {str(e)}")
        return jsonify({'error': f'访问目录失败: {str(e)}'}), 500

# 其他路由保持不變
@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify(crawl_status)

@app.route('/api/stop', methods=['POST'])
def stop_crawl():
    global crawl_status
    crawl_status['is_running'] = False
    socketio.emit('crawl_stopped', {'message': '爬取已停止'})
    return jsonify({'success': True, 'message': '停止指令已發送'})

# 精準優化系統路由
@app.route('/tmp_rovodev_targeted_optimization.js')
def serve_targeted_optimization():
    return send_from_directory('.', 'tmp_rovodev_targeted_optimization.js', mimetype='application/javascript')

# 分批載入系統路由
@app.route('/tmp_rovodev_batch_loading.js')
def serve_batch_loading():
    return send_from_directory('.', 'tmp_rovodev_batch_loading.js', mimetype='application/javascript')

# 智能快取系統路由
@app.route('/tmp_rovodev_smart_cache.js')
def serve_smart_cache():
    return send_from_directory('.', 'tmp_rovodev_smart_cache.js', mimetype='application/javascript')

@app.route('/tmp_rovodev_modern_video_player.css')
def serve_modern_player_css():
    return send_from_directory('.', 'tmp_rovodev_modern_video_player.css', mimetype='text/css')

@app.route('/tmp_rovodev_modern_video_player.js')
def serve_modern_player_js():
    return send_from_directory('.', 'tmp_rovodev_modern_video_player.js', mimetype='application/javascript')

@app.route('/api/open_folder', methods=['POST'])
def open_folder():
    """打開影片資料夾 - 參考main.py風格實現"""
    try:
        data = request.get_json()
        file_path = data.get('file_path')
        
        if not file_path:
            return jsonify({'error': '缺少檔案路徑參數'}), 400
        
        # 使用pathlib處理路徑，參考main.py風格
        folder_path = Path(file_path)
        
        print(f"[DEBUG] 打開資料夾: {folder_path}")
        
        # 驗證路徑
        if not folder_path.exists():
            return jsonify({'error': f'資料夾不存在: {folder_path}'}), 404
        
        if not folder_path.is_dir():
            return jsonify({'error': f'路徑不是資料夾: {folder_path}'}), 400
        
        # 簡潔的系統命令執行，參考main.py的直接風格
        system = platform.system().lower()
        
        if system == "darwin":  # macOS
            subprocess.run(["open", str(folder_path)], check=True)
        elif system == "windows":  # Windows  
            subprocess.run(["explorer", str(folder_path)], check=True)
        elif system == "linux":  # Linux
            subprocess.run(["xdg-open", str(folder_path)], check=True)
        else:
            return jsonify({'error': f'不支援的作業系統: {system}'}), 400
        
        return jsonify({
            'success': True,
            'message': f'成功打開資料夾',
            'folder_path': str(folder_path)
        })
        
    except subprocess.CalledProcessError as e:
        return jsonify({'error': f'無法打開資料夾: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'發生錯誤: {str(e)}'}), 500

@app.route('/api/get_folder_contents', methods=['POST'])
def get_folder_contents():
    """獲取資料夾內容"""
    try:
        data = request.get_json()
        folder_path = data.get('folder_path')
        
        if not folder_path:
            return jsonify({'error': '缺少資料夾路徑參數'}), 400
        
        # 使用pathlib處理路徑
        folder = Path(folder_path)
        
        if not folder.exists():
            return jsonify({'error': f'資料夾不存在: {folder_path}'}), 404
        
        if not folder.is_dir():
            return jsonify({'error': f'路徑不是資料夾: {folder_path}'}), 400
        
        # 獲取資料夾內容
        contents = []
        try:
            for item in folder.iterdir():
                item_info = {
                    'name': item.name,
                    'is_dir': item.is_dir(),
                    'size': item.stat().st_size if item.is_file() else 0,
                    'full_path': str(item)
                }
                contents.append(item_info)
            
            # 按類型和名稱排序：資料夾在前，然後按名稱排序
            contents.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
            
        except PermissionError:
            return jsonify({'error': '沒有權限讀取資料夾內容'}), 403
        
        return jsonify({
            'success': True,
            'contents': contents,
            'folder_path': str(folder)
        })
        
    except Exception as e:
        return jsonify({'error': f'獲取資料夾內容失敗: {str(e)}'}), 500

@app.route('/api/open_file', methods=['POST'])
def open_file():
    """開啟檔案 - 使用系統預設程式"""
    try:
        data = request.get_json()
        file_path = data.get('file_path')
        
        if not file_path:
            return jsonify({'error': '缺少檔案路徑參數'}), 400
        
        # 使用pathlib處理路徑
        file = Path(file_path)
        
        if not file.exists():
            return jsonify({'error': f'檔案不存在: {file_path}'}), 404
        
        if not file.is_file():
            return jsonify({'error': f'路徑不是檔案: {file_path}'}), 400
        
        # 根據作業系統使用對應命令開啟檔案
        system = platform.system().lower()
        
        try:
            if system == "darwin":  # macOS
                subprocess.run(["open", str(file)], check=True)
            elif system == "windows":  # Windows
                subprocess.run(["start", str(file)], shell=True, check=True)
            elif system == "linux":  # Linux
                subprocess.run(["xdg-open", str(file)], check=True)
            else:
                return jsonify({'error': f'不支援的作業系統: {system}'}), 400
            
            return jsonify({
                'success': True,
                'message': f'成功開啟檔案',
                'file_path': str(file)
            })
            
        except subprocess.CalledProcessError as e:
            return jsonify({'error': f'無法開啟檔案: {str(e)}'}), 500
        except Exception as e:
            return jsonify({'error': f'開啟檔案時發生錯誤: {str(e)}'}), 500
        
    except Exception as e:
        return jsonify({'error': f'處理請求失敗: {str(e)}'}), 500

@app.route('/api/delete_video', methods=['POST'])
def delete_video():
    """刪除影片資料夾"""
    try:
        data = request.get_json()
        av_code = data.get('av_code')
        file_path = data.get('file_path')
        
        print(f"[DEBUG] 收到刪除請求: {av_code}, 路徑: {file_path}")
        
        if not av_code or not file_path:
            return jsonify({'error': '缺少必要參數'}), 400
        
        # 將路徑轉換為Path對象
        folder_path = Path(file_path)
        
        # 驗證路徑是否存在
        if not folder_path.exists():
            return jsonify({'error': f'資料夾不存在: {folder_path}'}), 404
        
        # 驗證是否為目錄
        if not folder_path.is_dir():
            return jsonify({'error': f'路徑不是資料夾: {folder_path}'}), 400
        
        # 驗證資料夾名稱包含番號（安全檢查）
        if av_code.lower() not in folder_path.name.lower():
            return jsonify({'error': f'資料夾名稱與番號不匹配: {folder_path.name} vs {av_code}'}), 400
        
        print(f"[DEBUG] 開始刪除資料夾: {folder_path}")
        
        # 先嘗試關閉可能開啟的檔案，然後重試刪除
        import shutil
        import time
        import gc
        
        # 強制垃圾回收，關閉未釋放的檔案句柄
        gc.collect()
        
        # 多次重試刪除，處理SMB網路磁碟的延遲問題
        max_retries = 3
        for attempt in range(max_retries):
            try:
                shutil.rmtree(str(folder_path))
                print(f"[DEBUG] 成功刪除資料夾: {folder_path}")
                break
            except OSError as e:
                if "Resource busy" in str(e) or "smbdelete" in str(e):
                    if attempt < max_retries - 1:
                        print(f"[DEBUG] 刪除重試 {attempt + 1}/{max_retries}: 檔案被佔用，等待2秒後重試...")
                        time.sleep(2)
                        gc.collect()  # 再次嘗試釋放檔案句柄
                        continue
                    else:
                        # 最後一次嘗試：先重命名資料夾再刪除
                        print(f"[DEBUG] 最後重試：使用重命名刪除策略")
                        temp_name = folder_path.parent / f".delete_{folder_path.name}_{int(time.time())}"
                        try:
                            folder_path.rename(temp_name)
                            time.sleep(1)
                            shutil.rmtree(str(temp_name))
                            print(f"[DEBUG] 使用重命名策略成功刪除: {folder_path}")
                            break
                        except:
                            raise e
                else:
                    raise e
        else:
            raise Exception(f"多次重試後仍無法刪除資料夾，可能有檔案正在使用中")
        
        return jsonify({
            'message': f'成功刪除 {av_code} 資料夾',
            'deleted_path': str(folder_path)
        })
        
    except PermissionError:
        error_msg = f'沒有權限刪除資料夾: {folder_path}'
        print(f"[ERROR] {error_msg}")
        return jsonify({'error': error_msg}), 403
    except Exception as e:
        error_msg = f'刪除資料夾時發生錯誤: {str(e)}'
        print(f"[ERROR] {error_msg}")
        return jsonify({'error': error_msg}), 500

# 五大性能優化系統 - API支援
@app.route('/api/get_full_data', methods=['POST'])
def get_full_data():
    """獲取完整數據 - 支援懶載入系統"""
    try:
        data = request.json
        av_codes = data.get('av_codes', [])
        
        # 這裡應該從實際數據源獲取完整數據
        # 目前返回模擬數據，實際部署時需要連接真實數據
        results = []
        for av_code in av_codes:
            # 模擬完整數據
            full_data = {
                'av_code': av_code,
                'title': f'{av_code} - 完整標題',
                'file_path': f'/path/to/{av_code}.mp4',
                'local_cover': f'/covers/{av_code}.jpg',
                'has_nfo': True,
                'has_cover': True,
                '出演者': '詳細演員資訊',
                '片長': '120分鐘',
                '發行日期': '2024-01-01',
                '導演': '導演名稱',
                '製片': '製片公司',
                '系列': '影片系列',
                '類型': '動作 / 劇情',
                '簡介': '這是詳細的影片簡介內容...'
            }
            results.append(full_data)
        
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/get_detailed_data', methods=['POST'])
def get_detailed_data():
    """獲取詳細數據 - 支援批量請求"""
    try:
        data = request.json
        av_codes = data.get('av_codes', [])
        
        results = []
        for av_code in av_codes:
            # 實際實現中，這裡應該查詢數據庫或文件系統
            detailed_data = {
                'av_code': av_code,
                '出演者': f'{av_code} 的演員資訊',
                '類型': '動作 / 劇情 / 愛情',
                '簡介': f'這是 {av_code} 的詳細簡介內容，包含劇情描述和相關信息。',
                '片長': '120分鐘',
                '發行日期': '2024-01-01',
                '導演': '知名導演',
                '製片': '知名製片公司',
                '系列': 'Popular系列'
            }
            results.append(detailed_data)
        
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/get_shard_data', methods=['POST'])
def get_shard_data():
    """獲取分片數據 - 支援數據分片系統"""
    try:
        data = request.json
        shard_id = data.get('shardId')
        start_index = data.get('startIndex', 0)
        end_index = data.get('endIndex', 25)
        
        # 實際實現中，這裡應該從持久化存儲中獲取分片數據
        # 目前返回模擬數據
        shard_data = []
        for i in range(start_index, end_index):
            item = {
                'av_code': f'AV-{i:04d}',
                'title': f'影片標題 {i}',
                'file_path': f'/path/to/AV-{i:04d}.mp4',
                'local_cover': f'/covers/AV-{i:04d}.jpg',
                'has_nfo': True,
                'has_cover': True
            }
            shard_data.append(item)
        
        return jsonify(shard_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@socketio.on('connect')
def handle_connect():
    emit('connected', {'message': '已連接到伺服器'})

@socketio.on('disconnect')
def handle_disconnect():
    pass

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8888, debug=True, allow_unsafe_werkzeug=True)