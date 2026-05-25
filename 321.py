# -*- coding: utf-8 -*-
import os
import sys
import json
import queue
import threading
import re
import requests
from datetime import datetime

import sounddevice as sd
from vosk import Model, KaldiRecognizer
from flask import make_response, Flask, request, jsonify
from flask_cors import CORS
import gradio as gr
import uuid

# Import the poetry database
from poetry_database import POETRY_DATABASE, get_all_poems, get_poem_by_title, get_poems_by_grade

app = Flask(__name__)# 创建 Flask 应用
CORS(app)# 允许跨域请求

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vosk-model-cn-0.22", "vosk-model-cn-0.22")
if not os.path.exists(MODEL_PATH):
    print(f"模型路径 {MODEL_PATH} 不存在，请检查路径。")
    sys.exit(1)

SAMPLE_RATE = 16000
CHUNK_SIZE = 1024
BUFFER_SIZE = 16
exit_flag = False
current_session_id = None
session_poem_map = {}
session_start_time = None
# === 新增：语音识别接口 ===
@app.route('/start', methods=['GET'])#启动语音识别
def api_start_recognition():
    try:
        result = start_recognition()
        return jsonify({"消息": result})
    except Exception as e:
        return jsonify({"错误": f"启动语音识别时出错: {str(e)}"}), 500


@app.route('/stop', methods=['GET'])#停止语音识别
def api_stop_recognition():
    try:
        result = stop_recognition()
        return jsonify({"结果": result})
    except Exception as e:
        return jsonify({"错误": f"停止语音识别时出错: {str(e)}"}), 500
# ===== 改进的文本存储类 =====
class EnhancedTextStorage:#用于安全存储和处理语音识别的结果
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()#初始化时创建一个线程锁（为了确保多线程安全）并重置存储的内容

    def reset(self):#重置存储
        with self.lock:
            self.segments = []
            self.current_partial = ""
            self.last_final = ""

    def add_final_segment(self, text):#添加一个完整的识别结果
        with self.lock:
            clean_text = text.replace(" ", "")#清除文本中的空格
            timestamp = datetime.now().strftime("%H:%M:%S")#添加时间戳
            self.segments.append({
                "text": clean_text,
                "time": timestamp
            })
            self.last_final = clean_text

    def update_partial(self, text):
        with self.lock:
            self.current_partial = text.replace(" ", "")

    def get_combined_text(self):#将识别到的文本组合成一个字符串
        with self.lock:
            return "".join([seg["text"] for seg in self.segments])

    def get_full_sequence(self):#获取带时间戳的完整序列
        with self.lock:
            return "\n".join(
                [f"[{seg['time']}] {seg['text']}"
                 for seg in self.segments]
            )

# ===== 分数存储类 =====
class ScoreStorage:
    def __init__(self):
        self.lock = threading.Lock()
        self.scores = []

    def add_score(self, score=None, feedback="", title=None, recognized_text=None, time_str=None, **kwargs):
        with self.lock:
            try:
                score_value = int(score) if score is not None else None
            except Exception:
                score_value = score

            timestamp = time_str if time_str else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            record = {
                "title": title,
                "score": score_value,
                "feedback": feedback or "",
                "recognized_text": recognized_text or "",
                "time": timestamp
            }
            for k, v in kwargs.items():
                if k not in record:
                    record[k] = v
            self.scores.append(record)

    def get_scores(self):#获取分数
        with self.lock:
            return self.scores.copy()

    def clear_scores(self):#清空分数
        with self.lock:
            self.scores.clear()


score_storage = ScoreStorage()#创建分数存储对象

# === 新增部分 === 保存结果到 data.json ===
def save_recite_result(name, author, poem_type, score, status, comment=""):
    DATA_FILE = os.path.join("static", "data", "data.json")
    # 若不存在则创建
    if not os.path.exists(DATA_FILE):
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        data = {"poems": [], "reciteHistory": {}}
    else:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = {"poems": [], "reciteHistory": {}}

    poems = data.get("poems", [])
    recite_history = data.get("reciteHistory", {})
    today = datetime.now().strftime("%Y-%m-%d")#获取当前时间，转换成年月日的格式

    # 查找诗是否存在
    poem = next((p for p in poems if p["name"] == name), None)#遍历poems列表，如果找到同名的poem则更新
    if poem:
        poem["times"] += 1#添加次数
        poem["lastDate"] = today#更新时间
        poem["score"] = score#添加分数
        poem["status"] = status#添加状态
        poem["statusClass"] = get_status_class(status)#添加状态样式
        poem["icon"] = get_status_icon(status)#添加图标
    else:
        poem = {
            "name": name,
            "author": author,
            "type": poem_type,
            "times": 1,
            "lastDate": today,
            "score": score,
            "status": status,
            "statusClass": get_status_class(status),
            "icon": get_status_icon(status)
        }
        poems.append(poem)#添加新的poem

    # 更新历史
    history_entry = {
        "times": poem["times"],
        "date": today,
        "score": score,
        "status": status,
        "comment": comment
    }
    if name not in recite_history:
        recite_history[name] = []
    recite_history[name].append(history_entry)

    # 写回文件
    data["poems"] = poems
    data["reciteHistory"] = recite_history
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)#indent 缩进两个空格

def get_status_class(status):
    if status == "已掌握":
        return "bg-green-100 text-green-800"
    elif status == "需复习":
        return "bg-yellow-100 text-yellow-800"
    else:
        return "bg-gray-100 text-gray-800"

def get_status_icon(status):
    if status == "已掌握":
        return "fa-check-circle"
    elif status == "需复习":
        return "fa-redo"
    else:
        return "fa-question-circle"

# === 语音识别相关 ===
model = Model(MODEL_PATH)#创建模型对象
recognizer = KaldiRecognizer(model, SAMPLE_RATE)#创建识别器对象
recognizer.SetWords(False)#关闭返回结果中的单词
audio_queue = queue.Queue(maxsize=BUFFER_SIZE)#创建队列对象
text_storage = EnhancedTextStorage()#创建文本存储对象

def audio_capture():
    with sd.RawInputStream(
            samplerate=SAMPLE_RATE,#采样率
            blocksize=CHUNK_SIZE,#块大小
            dtype="int16",#数据类型
            channels=1,#通道数
            callback=lambda indata, *_: audio_queue.put(bytes(indata))
    ):
        print("[MIC] 麦克风已开启...")
        while not exit_flag:
            continue

def speech_recognition():#语音识别
    partial_result = ""
    while not exit_flag:
        try:
            data = audio_queue.get(timeout=0.1)#设置超时时间，避免阻塞
            if recognizer.AcceptWaveform(data):
                result = json.loads(recognizer.Result())
                text = result.get("text", "")
                if text:
                    print(f"\n✅ 最终识别结果：{text}")
                    text_storage.add_final_segment(text)
            else:
                partial = json.loads(recognizer.PartialResult())
                new_partial = partial.get("partial", "")
                if new_partial != partial_result:
                    partial_result = new_partial
                    print(f"⏳ 实时识别：{partial_result.ljust(40)}", end="\r", flush=True)
                    text_storage.update_partial(new_partial)
        except queue.Empty:
            continue

recognition_threads = []

def start_recognition():
    """
    启动语音识别。每次启动都会清空旧缓存，并记录开始时间。
    """
    global exit_flag, recognition_threads, session_start_time
    exit_flag = True
    for t in recognition_threads:
        if t.is_alive():
            t.join(timeout=1.0)
    recognition_threads.clear()

    # 启动新识别
    exit_flag = False
    text_storage.reset()
    session_start_time = datetime.now()  # ✅ 记录新会话起始时间

    audio_thread = threading.Thread(target=audio_capture, daemon=True)
    recog_thread = threading.Thread(target=speech_recognition, daemon=True)
    audio_thread.start()
    recog_thread.start()
    recognition_threads.extend([audio_thread, recog_thread])

    print(f"[识别开始] {session_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    return "语音识别已启动"

def stop_recognition():
    global exit_flag, recognition_threads
    exit_flag = True
    sd.stop()

    # 等待线程完全退出
    for t in recognition_threads:
        if t.is_alive():
            t.join(timeout=1.0)
    recognition_threads.clear()

    try:#保存结果到speech_result.txt文件中
        combined = text_storage.get_combined_text()
        full_sequence = text_storage.get_full_sequence()
        with open("speech_result.txt", "a", encoding="utf-8") as f:
            f.write(f"\n\n=== 会话记录 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            f.write(full_sequence)
        return combined
    finally:
        text_storage.reset()

def extract_score_from_text(text):#从AI回复中提取分数
    score_patterns = [
        r'[评評][分數][:：]?\s*(\d+)',
        r'[得獲][分數][:：]?\s*(\d+)',
        r'(\d+)\s*[分數]',
        r'(\d+)\s*分',
        r'100\s*分?'
    ]
    for pattern in score_patterns:
        match = re.search(pattern, text)
        if match:
            try:
                score = int(match.group(1))
                if 0 <= score <= 100:
                    return score
            except ValueError:
                continue
    return None

def get_response(prompt):#调用本地 LLM API（ Ollama 部署的 deepseek-r1:7b 模型）获取流式回复
    API_URL = "http://localhost:11434/api/generate"
    headers = {"Content-Type": "application/json"}
    data = {"model": "deepseek-r1:7b", "prompt": prompt, "stream": True}
    try:
        response = requests.post(API_URL, headers=headers, json=data, stream=True)
        response.raise_for_status()
        full_response = ""
        for line in response.iter_lines():
            if line:
                json_data = json.loads(line.decode("utf-8"))
                if "response" in json_data:
                    full_response += json_data.get("response", "")
                if json_data.get("done", False):
                    break
        print(full_response)
        return full_response
    except requests.RequestException as e:
        print(f"请求 API 时出错: {e}")
        return "请求 API 时出错，请稍后再试。"

current_poem = {}


@app.route('/api/chat', methods=['POST'])#接收POST请求
def chat():
    try:
        message = request.form.get('message')
        session_id = request.form.get('session_id')

        # 获取该会话对应的诗歌信息
        poem_info = session_poem_map.get(session_id) if session_id else current_poem

        if not poem_info:
            return make_response("错误: 未找到诗歌信息"), 500

        title = poem_info.get('title', '')
        author = poem_info.get('author', '未知作者')
        dynasty = poem_info.get('dynasty', '未知朝代')

        url = "http://localhost:11434/api/generate"
        payload = {
            "model": "deepseek-r1:7b",
            "prompt": f"你是一个严格的古诗词背诵评分助手。请按以下标准评分："
                      f"1.标点符号不计入评分要求"
                      f"2. 背诵内容完全符合背诵篇目且内容顺序正确、流畅背诵：100分"
                      f"3. 完全正确但有错别字：60-90分"
                      f"4. 没有全文背诵、有遗漏：0-59分"
                      f"5. 背诵内容错误超过三分之一：0-59分"
                      f"6. 出现与背诵的此篇诗词无关的内容：0-59分"
                      f"请直接给出评分和简短评语，格式：得分XX分，评语...\n\n用户背诵诗歌为：{title}用户背诵内容: {message}",
            "stream": False
        }
        headers = {'Content-Type': 'application/json'}

        response = requests.post(url, headers=headers, json=payload)
        file = response.json()
        reply = file.get('response', '')
        print("=== 评分回复 ===")
        print(reply)

        score = extract_score_from_text(reply)
        if score is not None:
            score_storage.add_score(score, reply)
            print(f"提取到分数: {score}")

            # 保存到 data.json
            poem_name = title
            author = poem_info.get('author', '未知作者')
            poem_type = dynasty
            poem_name = poem_name.replace('《', '').replace('》', '')
            status = "已掌握" if score >= 90 else "需复习"
            save_recite_result(poem_name, author, poem_type, score, status, reply)

        response = make_response(reply)
        response.headers['Content-Type'] = 'text/plain; charset=utf-8'
        return response

    except Exception as e:
        error_response = make_response(f"错误: {str(e)}")
        error_response.headers['Content-Type'] = 'text/plain; charset=utf-8'
        return error_response, 500

@app.route('/api/scores', methods=['GET'])#获取分数
def get_scores():
    try:
        return jsonify({"scores": score_storage.get_scores()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/clear_scores', methods=['POST'])#清空分数
def clear_scores():
    try:
        score_storage.clear_scores()
        return jsonify({"message": "分数记录已清空"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/poems', methods=['GET'])#获取所有诗歌
def get_all_poems_api():
    try:
        return jsonify({"poems": get_all_poems()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/poems/grade/<grade>', methods=['GET'])#获取指定年级的诗歌
def get_poems_by_grade_api(grade):
    try:
        return jsonify({"poems": get_poems_by_grade(grade)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/current-poem', methods=['POST'])#接收当前诗歌
def receive_current_poem():
    try:
        global current_poem, current_session_id
        data = request.get_json()

        # 为每次诗歌选择创建新的会话ID
        current_session_id = str(uuid.uuid4())
        current_poem = {
            "title": data.get('title'),
            "author": data.get('author'),
            "dynasty": data.get('dynasty'),
            "content": data.get('content')
        }

        # 将当前会话ID与诗歌信息关联
        session_poem_map[current_session_id] = current_poem.copy()

        print(f"创建新会话 {current_session_id}: {current_poem['title']} by {current_poem['author']}")
        return jsonify({"status": "success", "message": "诗歌信息已接收", "session_id": current_session_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
if __name__ == "__main__":
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    os.environ['HOSTNAME'] = 'localhost'
    os.environ['COMPUTERNAME'] = 'localhost'
    import socket
    original_getfqdn = socket.getfqdn#错误处理

    def patched_getfqdn(name=''):#错误处理补丁
        try:
            return original_getfqdn(name)
        except UnicodeDecodeError:
            return 'localhost'

    socket.getfqdn = patched_getfqdn
    try:
        app.run(debug=False, host='127.0.0.1', port=5000, use_reloader=False)
    except Exception as e:
        print(f"启动服务器时遇到问题: {e}")
        app.run(debug=False, host='localhost', port=5000, use_reloader=False)
