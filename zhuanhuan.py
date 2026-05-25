# -*- coding: utf-8 -*-
import os
import sys
import json
import queue
import threading
import re
from multiprocessing.dummy import current_process

import requests
from datetime import datetime

import sounddevice as sd
from vosk import Model, KaldiRecognizer
from flask import make_response, Flask, request, jsonify
from flask_cors import CORS
import gradio as gr

# Import the poetry database
from poetry_database import POETRY_DATABASE, get_all_poems, get_poem_by_title, get_poems_by_grade

app = Flask(__name__)
CORS(app)

# 检查模型路径是否存在
import os
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vosk-model-cn-0.22", "vosk-model-cn-0.22")
if not os.path.exists(MODEL_PATH):
    print(f"模型路径 {MODEL_PATH} 不存在，请检查路径。")
    sys.exit(1)

# ===== 配置参数 =====
SAMPLE_RATE = 16000
CHUNK_SIZE = 3000
BUFFER_SIZE = 8
exit_flag = False  # 退出标志

current_poem={}
# ===== 改进的文本存储类 =====
class EnhancedTextStorage:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()  # 初始化时调用重置方法

    def reset(self):
        """重置所有存储内容"""
        with self.lock:
            self.segments = []  # 分段存储列表
            self.current_partial = ""  # 当前临时识别内容
            self.last_final = ""  # 最后一次确认内容

    def add_final_segment(self, text):
        """添加最终确认的分段"""
        with self.lock:
            clean_text = text.replace(" ", "")
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.segments.append({
                "text": clean_text,
                "time": timestamp
            })
            self.last_final = clean_text

    def update_partial(self, text):
        """更新临时识别内容"""
        with self.lock:
            self.current_partial = text.replace(" ", "")

    def get_combined_text(self):
        """合并所有分段为完整字符串"""
        with self.lock:
            return "".join([seg["text"] for seg in self.segments])

    def get_full_sequence(self):
        """获取带时间戳的完整序列"""
        with self.lock:
            return "\n".join(
                [f"[{seg['time']}] {seg['text']}"
                 for seg in self.segments]
            )


# ===== 分数存储类 =====
class ScoreStorage:
    def __init__(self):
        self.lock = threading.Lock()
        self.scores = []  # 存储分数历史

    def add_score(self, score=None, feedback="", title=None, recognized_text=None, time_str=None, **kwargs):
        """
        保存一条记录。支持关键字参数，向后兼容：
        add_score(score, feedback)  或  add_score(score=..., feedback=..., title=..., ...)
        """
        with self.lock:
            # 尝试把 score 转为 int（若能），否则保留原样
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
            # 将其它任意传入字段也保存（可选）
            for k, v in kwargs.items():
                if k not in record:
                    record[k] = v

            self.scores.append(record)

    def get_scores(self):
        """获取所有分数"""
        with self.lock:
            return self.scores.copy()

    def clear_scores(self):
        """清空分数记录"""
        with self.lock:
            self.scores.clear()

# 全局分数存储对象
score_storage = ScoreStorage()


# ===== 初始化模型 =====
model = Model(MODEL_PATH)
recognizer = KaldiRecognizer(model, SAMPLE_RATE)
recognizer.SetWords(False)

# 创建音频队列
audio_queue = queue.Queue(maxsize=BUFFER_SIZE)
text_storage = EnhancedTextStorage()  # 全局存储对象


# ===== 音频采集线程 =====
def audio_capture():
    with sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=CHUNK_SIZE,
            dtype="int16",
            channels=1,
            callback=lambda indata, *_: audio_queue.put(bytes(indata))
    ):
        print("[MIC] 麦克风已开启...")
        while not exit_flag:
            continue


# ===== 识别线程 =====
def speech_recognition():
    partial_result = ""
    while not exit_flag:
        try:
            data = audio_queue.get(timeout=0.5)
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


# ===== 修改后的控制函数 =====
def start_recognition():
    global exit_flag
    exit_flag = False
    text_storage.reset()  # 关键修改：每次启动时重置存储
    capture_thread = threading.Thread(target=audio_capture, daemon=True)
    recognition_thread = threading.Thread(target=speech_recognition, daemon=True)
    capture_thread.start()
    recognition_thread.start()
    return "语音识别已启动"


def stop_recognition():
    global exit_flag
    exit_flag = True
    sd.stop()
    try:
        combined = text_storage.get_combined_text()
        full_sequence = text_storage.get_full_sequence()

        # 保存到文件（追加模式）
        with open("speech_result.txt", "a", encoding="utf-8") as f:
            f.write(f"\n\n=== 会话记录 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            f.write(full_sequence)
        return combined
    finally:
        text_storage.reset()  # 确保清理存储


# ===== 从文本中提取分数的函数 =====
def extract_score_from_text(text):
    """从AI回复中提取分数"""
    # 查找类似 "评分: 85分" 或 "得分: 90" 或 "85分" 的模式
    score_patterns = [
        r'[评评][分數][:：]?\s*(\d+)',
        r'[得獲][分數][:：]?\s*(\d+)',
        r'(\d+)\s*[分數]',
        r'(\d+)\s*分',
        r'100\s*分?'  # 特殊处理100分
    ]
    
    for pattern in score_patterns:
        match = re.search(pattern, text)
        if match:
            try:
                score = int(match.group(1))
                # 确保分数在合理范围内
                if 0 <= score <= 100:
                    return score
            except ValueError:
                continue
    
    # 如果没有找到明确的分数，返回默认值
    return None


# ===== 保持原有API接口不变 =====
def get_response(prompt):
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
                # 处理DeepSeek模型的响应格式
                if "response" in json_data:
                    full_response += json_data.get("response", "")
                # 如果是结束标记，则停止处理
                if json_data.get("done", False):
                    break
        print(full_response)
        return full_response
    except requests.RequestException as e:
        print(f"请求 API 时出错: {e}")
        return "请求 API 时出错，请稍后再试。"


@app.route('/start', methods=['GET'])
def api_start_recognition():
    try:
        result = start_recognition()
        return jsonify({"消息": result})
    except Exception as e:
        return jsonify({"错误": f"启动语音识别时出错: {str(e)}"}), 500


@app.route('/stop', methods=['GET'])
def api_stop_recognition():
    try:
        result = stop_recognition()
        return jsonify({"结果": result})
    except Exception as e:
        return jsonify({"错误": f"停止语音识别时出错: {str(e)}"}), 500


# 新接口地址
# API_URL = "http://localhost:11434/api/generate"

from flask import make_response  # 导入 make_response 用于自定义响应


@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        message = request.form.get('message')
        title=current_poem.get('title',)
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
        headers = {
            'Content-Type': 'application/json'
        }

        print("\n=== 发送给Ollama的请求 ===")
        print(f"请求URL: {url}")
        print(f"请求头: {headers}")
        print(f"请求内容: {payload}\n")

        response = requests.post(url, headers=headers, json=payload)

        print("\n=== Ollama原始响应 ===")
        print(f"状态码: {response.status_code}")
        print(f"响应内容: {response.text}\n")

        file = response.json()
        reply = file.get('response', '')

        print("\n=== 解析后的回复内容 ===")
        print(reply)

        # 提取分数并存储
        score = extract_score_from_text(reply)
        if score is not None:
            # 保存到内存
            score_storage.add_score(score, reply)

            # 同步写入 scores.json
            data = load_scores()
            data.append({
                "title": current_poem.get("title", ""),
                "score": score,
                "feedback": reply,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            save_scores(data)

            print(f"✅ 已保存评分至 scores.json（{len(data)} 条记录）")

        # ===== 修改点：直接返回纯文本 =====
        response = make_response(reply)  # 直接返回字符串内容
        response.headers['Content-Type'] = 'text/plain; charset=utf-8'  # 设置响应头
        return response

    except Exception as e:
        print(f"\n!!! 处理过程中发生错误: {str(e)}")
        # 错误时也返回纯文本
        error_response = make_response(f"错误: {str(e)}")
        error_response.headers['Content-Type'] = 'text/plain; charset=utf-8'
        return error_response, 500


# ===== 新增API接口：获取分数历史 =====
@app.route('/api/scores', methods=['GET'])
def get_scores():
    try:
        scores = score_storage.get_scores()
        return jsonify({"scores": scores})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



# ===== 新增API接口：清空分数历史 =====
@app.route('/api/clear_scores', methods=['POST'])
def clear_scores():
    try:
        score_storage.clear_scores()
        return jsonify({"message": "分数记录已清空"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===== 新增API接口：获取所有诗词 =====
@app.route('/api/poems', methods=['GET'])
def get_all_poems_api():
    try:
        poems = get_all_poems()
        return jsonify({"poems": poems})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===== 新增API接口：根据年级获取诗词 =====
@app.route('/api/poems/grade/<grade>', methods=['GET'])
def get_poems_by_grade_api(grade):
    try:
        poems = get_poems_by_grade(grade)
        return jsonify({"poems": poems})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
import json
import threading

SCORES_FILE = "data.json"
scores_lock = threading.Lock()

# 读取
def load_scores():
    if not os.path.exists(SCORES_FILE):
        return []
    with scores_lock:
        try:
            with open(SCORES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []

# 写入
def save_scores(data):
    with scores_lock:
        with open(SCORES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


@app.route("/api/poems", methods=["GET"])
def api_poems():
    """返回所有诗，前端分页自己处理"""
    poems = get_all_poems()
    return jsonify({"poems": poems})


@app.route("/api/scores", methods=["GET"])
def api_scores():
    """返回某诗的历史评分"""
    title = request.args.get("title")
    data = load_scores()
    filtered = [x for x in data if x.get("title") == title]
    return jsonify({"title": title, "scores": filtered})


@app.route("/api/recite/add", methods=["POST"])
def api_add_recite():
    """写入一次评分记录"""
    title = request.form.get("title")
    dynamic = request.form.get("dynamic")
    writer = request.form.get("writer")
    score = request.form.get("score")
    feedback = request.form.get("feedback")


    if not (title and score):
        return jsonify({"error": "缺少字段"}), 400

    try:
        score = int(score)
    except:
        return jsonify({"error": "score必须是数字"}), 400

    data = load_scores()
    data.append({
        "title": title,
        "score": score,
        "dynamic":dynamic,
        "writer":writer,
        "feedback":feedback,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    save_scores(data)
    return jsonify({"status": "ok"})
# ====== 新增：添加单条诗歌评分记录 ======

# ====== 新增：某一首诗的历史 ======
@app.route('/api/recite/history', methods=['GET'])
def api_history():
    title = request.args.get("title")
    arr = [s for s in score_storage.get_scores() if s["title"]==title]
    return jsonify({"title":title, "history":arr})


@app.route('/api/recite/history', methods=['POST'])
def api_add_history():
    try:
        title = request.form.get("title") or request.json.get("title") if request.is_json else request.form.get("title")
        writer = request.form.get("writer") or (request.json.get("writer") if request.is_json else None)
        score = request.form.get("score") or (request.json.get("score") if request.is_json else None)
        time = request.form.get("time") or (request.json.get("time") if request.is_json else None)
        feedback = request.form.get("feedback") or (request.json.get("feedback") if request.is_json else "")

        if score is None:
            return jsonify({"error": "missing score"}), 400

        # 尝试把 score 转为 int
        try:
            score_val = int(score)
        except:
            return jsonify({"error": "score must be integer"}), 400

        # 使用实例调用，并传关键字，保证顺序不会错
        score_storage.add_score(title=title, score=score_val, feedback=feedback, time_str=time, writer=writer)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route('/api/current-poem', methods=['POST'])#将接收到的诗歌信息保存到全局变量中
def receive_current_poem():
    try:
        global current_poem
        data = request.get_json()
        current_poem = {
            "title": data.get('title'),
            "author": data.get('author'),
            "type": data.get('type'),
            "content": data.get('content')
        }
        # 处理接收到的诗歌信息

        # 可以将信息存储到全局变量或数据库中
        # current_selected_poem = data

        print(f"接收到当前诗歌: {current_poem['title']} by {current_poem['author']} ({current_poem['dynasty']})")
        return jsonify({"status": "success", "message": "诗歌信息已接收"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/convert-scores', methods=['POST'])
def convert_scores_format():
    try:
        # 读取 scores.json
        if not os.path.exists(SCORES_FILE):
            return jsonify({"error": "scores.json 文件不存在"}), 404

        with open(SCORES_FILE, "r", encoding="utf-8") as f:
            scores_data = json.load(f)

        # 构建新的 data.json 格式
        # 先读取现有的 poems 数据
        poems_data = []
        data_file = os.path.join(os.path.dirname(__file__), 'static', 'data', 'data.json')
        if os.path.exists(data_file):
            with open(data_file, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
                poems_data = existing_data.get("poems", [])

        # 按诗词标题分组评分记录
        recite_history = {}
        for score_record in scores_data:
            title = score_record["title"]
            if title not in recite_history:
                recite_history[title] = []

            # 转换记录格式
            history_record = {
                "times": len(recite_history[title]) + 1,  # 自动编号
                "date": score_record["time"].split()[0],  # 只保留日期部分
                "score": score_record["score"],
                "status": get_status_from_score(score_record["score"]),  # 根据分数确定状态
                "comment": score_record["feedback"]
            }
            recite_history[title].append(history_record)

        # 构建新的 data.json 结构
        new_data = {
            "poems": poems_data,  # 保留现有的 poems 数据
            "reciteHistory": recite_history
        }

        # 保存到 data.json
        data_file_path = os.path.join(os.path.dirname(__file__), 'static', 'data', 'data.json')
        os.makedirs(os.path.dirname(data_file_path), exist_ok=True)
        with open(data_file_path, "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)

        return jsonify({"message": "格式转换成功", "data": new_data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def get_status_from_score(score):
    """根据分数确定状态"""
    try:
        score = int(score)
        if score >= 90:
            return "已掌握"
        elif score >= 80:
            return "已完成"
        else:
            return "需复习"
    except:
        return "需复习"


if __name__ == "__main__":
    # 设置环境变量解决编码问题
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    # 设置主机名环境变量
    os.environ['HOSTNAME'] = 'localhost'
    os.environ['COMPUTERNAME'] = 'localhost'
    
    # 使用不同的方式启动服务器以避免编码问题
    import socket
    # 临时修改socket的getfqdn方法
    original_getfqdn = socket.getfqdn
    def patched_getfqdn(name=''):
        try:
            return original_getfqdn(name)
        except UnicodeDecodeError:
            return 'localhost'
    socket.getfqdn = patched_getfqdn
    
    try:
        app.run(debug=False, host='127.0.0.1', port=5000, use_reloader=False)
    except Exception as e:
        print(f"启动服务器时遇到问题: {e}")
        print("请手动启动服务器或检查系统配置")
        # 仍然启动应用，但使用更安全的配置
        app.run(debug=False, host='localhost', port=5000, use_reloader=False)
