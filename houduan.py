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
from datetime import datetime, timedelta
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


# 星期映射表（周一=1，周日=7）
WEEKDAY_MAP = {
    "周一": 1,
    "周二": 2,
    "周三": 3,
    "周四": 4,
    "周五": 5,
    "周六": 6,
    "周日": 7
}


# 学习计划类
class StudentPlan:
    def __init__(self):
        self.plans = {}

    def content_difficulty(self, content):
        """分析内容难度"""
        char_count = len(content)
        if char_count <= 50:
            return "简单"
        elif char_count <= 150:
            return "适中"
        else:
            return "困难"

    def estimate_time(self, content, difficulty):
        """估算所需时间"""
        char_count = len(content)
        base_time = char_count / 10
        if difficulty == "简单":
            return max(5, int(base_time * 0.8))
        elif difficulty == "适中":
            return max(10, int(base_time))
        else:
            return max(20, int(base_time * 1.5))

    def get_poem_content(self, title):
        """通过题目获取诗词内容"""
        poem = get_poem_by_title(title)
        if poem:
            return poem["content"]
        else:
            return "无法找到该标题的诗词"

    def split_poem_into_sentences(self, content):
        """将诗按句切分"""
        lines = content.split('\n')
        sentences = [line for line in lines if line.strip()]
        return sentences

    def is_valid_time_slot(self, available_time, target_date):
        """校验时间槽是否在目标日期之前且有效"""
        if not target_date:
            return True, "无目标日期时不校验时间"

        try:
            # 解析目标日期为datetime对象
            target_dt = datetime.strptime(target_date, "%Y-%m-%d")
            today = datetime.now().date()
            target_date_obj = target_dt.date()

            # 校验目标日期是否在今天之后
            if target_date_obj < today:
                return False, "目标日期不能早于今天"

            # 校验所有时间槽的星期是否在目标日期之前
            target_weekday = target_dt.weekday() + 1  # 转换为周一=1格式
            for slot in available_time:
                slot_weekday = WEEKDAY_MAP.get(slot["星期"])
                if not slot_weekday:
                    return False, f"无效的星期格式: {slot['星期']}"

                # 计算时间槽对应的实际日期（最近的该星期几）
                days_diff = (slot_weekday - today.weekday() - 1) % 7 + 1
                slot_date = today + timedelta(days=days_diff)

                # 时间槽日期不能晚于目标日期
                if slot_date > target_date_obj:
                    return False, f"时间槽{slot['星期']}晚于目标日期"

            return True, "时间校验通过"
        except ValueError:
            return False, "目标日期格式错误，请使用YYYY-MM-DD格式"
        except Exception as e:
            return False, f"日期校验错误: {str(e)}"

    def split_into_stages(self, sentences, time_slots, required_time):
        """根据时间槽时长分配诗句，确保每个阶段的内容与时间匹配"""
        stages = []
        total_sentences = len(sentences)
        total_available = sum(slot["minutes"] for slot in time_slots)

        if total_available == 0 or total_sentences == 0:
            return []

        sentence_index = 0
        for slot in time_slots:
            if sentence_index >= total_sentences:
                break

            # 按时间比例分配句子数量
            slot_ratio = slot["minutes"] / total_available
            slot_sentence_count = max(1, int(total_sentences * slot_ratio))

            # 取句子（避免越界）
            end_idx = min(sentence_index + slot_sentence_count, total_sentences)
            stage_sentences = sentences[sentence_index:end_idx]
            sentence_index = end_idx

            stages.append({
                "stage": len(stages) + 1,
                "date": slot["day"],
                "time": f"{slot['start']}-{slot['end']}",
                "duration": min(slot["minutes"], required_time),
                "task": f"背诵：{' '.join(stage_sentences)}",
                "completed": False  # 新增进度跟踪字段
            })

        # 处理剩余句子（分配到最后一个阶段）
        if sentence_index < total_sentences and stages:
            stages[-1]["task"] += " " + " ".join(sentences[sentence_index:])

        return stages

    def add_plan(self, user_id, poem_title, available_time, target_date):
        """生成学习计划"""
        # 先进行时间有效性校验
        valid, msg = self.is_valid_time_slot(available_time, target_date)
        if not valid:
            raise ValueError(msg)

        content = self.get_poem_content(poem_title)
        difficulty = self.content_difficulty(content)
        required_time = self.estimate_time(content, difficulty)
        sentences = self.split_poem_into_sentences(content)

        # 计算总可用时间和时间槽
        time_slots = []
        total_available_minutes = 0
        for info_time in available_time:
            # 时间格式校验
            try:
                start_hour, start_min = map(int, info_time['开始'].split(":"))
                end_hour, end_min = map(int, info_time["结束"].split(":"))
                if not (0 <= start_hour < 24 and 0 <= start_min < 60 and
                        0 <= end_hour < 24 and 0 <= end_min < 60):
                    raise ValueError("时间格式不正确，小时应在0-23之间，分钟应在0-59之间")
                if (end_hour * 60 + end_min) <= (start_hour * 60 + start_min):
                    raise ValueError("结束时间必须晚于开始时间")
            except ValueError as e:
                raise ValueError(f"时间格式错误: {str(e)}")

            available_minutes = (end_hour - start_hour) * 60 + (end_min - start_min)
            total_available_minutes += available_minutes
            time_slots.append({
                "day": info_time['星期'],
                "start": info_time['开始'],
                "end": info_time['结束'],
                "minutes": available_minutes
            })

        # 校验总可用时间是否足够
        if total_available_minutes < required_time:
            raise ValueError(f"可用时间不足，需要至少{required_time}分钟，实际只有{total_available_minutes}分钟")

        plans = {
            "user_id": user_id,
            "poem_title": poem_title,
            "content": content,
            "difficulty": difficulty,
            "required_time": required_time,
            "now_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "target_date": target_date,
            "schedule": []
        }

        # 生成学习计划
        if len(time_slots) > 0:
            plans["schedule"] = self.split_into_stages(sentences, time_slots, required_time)

        # 存储计划
        if user_id not in self.plans:
            self.plans[user_id] = []
        self.plans[user_id].append(plans)
        return plans

    def get_study_plan(self, user_id):
        """获取用户学习计划"""
        if user_id in self.plans:
            return self.plans[user_id]
        else:
            return []

    def update_study_plan(self, user_id, plan_index, stage_completed):
        """更新学习计划状态"""
        if user_id in self.plans and plan_index < len(self.plans[user_id]):
            plan = self.plans[user_id][plan_index]
            if 0 < stage_completed <= len(plan["schedule"]):
                plan["schedule"][stage_completed - 1]["completed"] = True
            return plan
        else:
            return None

    def modify_plan(self, user_id, plan_index, new_available_time=None, new_target_date=None, new_poem_title=None):
        """修改已有的学习计划"""
        if user_id not in self.plans or plan_index >= len(self.plans[user_id]):
            return None

        plan = self.plans[user_id][plan_index]
        sentences = self.split_poem_into_sentences(plan["content"])

        # 如果提供了新的诗词标题，则重新生成内容
        if new_poem_title:
            plan["poem_title"] = new_poem_title
            plan["content"] = self.get_poem_content(new_poem_title)
            plan["difficulty"] = self.content_difficulty(plan["content"])
            plan["required_time"] = self.estimate_time(plan["content"], plan["difficulty"])
            sentences = self.split_poem_into_sentences(plan["content"])

        # 更新目标日期
        if new_target_date:
            plan["target_date"] = new_target_date

        # 如果提供了新的时间安排，则重新分配计划
        if new_available_time:
            # 先进行时间有效性校验
            valid, msg = self.is_valid_time_slot(new_available_time, plan["target_date"])
            if not valid:
                raise ValueError(msg)

            # 清空原有计划
            plan["schedule"] = []

            # 计算总可用时间和时间槽
            time_slots = []
            total_available_minutes = 0
            for info_time in new_available_time:
                # 时间格式校验
                try:
                    start_hour, start_min = map(int, info_time['开始'].split(":"))
                    end_hour, end_min = map(int, info_time["结束"].split(":"))
                    if not (0 <= start_hour < 24 and 0 <= start_min < 60 and
                            0 <= end_hour < 24 and 0 <= end_min < 60):
                        raise ValueError("时间格式不正确，小时应在0-23之间，分钟应在0-59之间")
                    if (end_hour * 60 + end_min) <= (start_hour * 60 + start_min):
                        raise ValueError("结束时间必须晚于开始时间")
                except ValueError as e:
                    raise ValueError(f"时间格式错误: {str(e)}")

                available_minutes = (end_hour - start_hour) * 60 + (end_min - start_min)
                total_available_minutes += available_minutes
                time_slots.append({
                    "day": info_time['星期'],
                    "start": info_time['开始'],
                    "end": info_time['结束'],
                    "minutes": available_minutes
                })

            # 校验总可用时间是否足够
            if total_available_minutes < plan["required_time"]:
                raise ValueError(
                    f"可用时间不足，需要至少{plan['required_time']}分钟，实际只有{total_available_minutes}分钟")

            # 重新生成计划
            if len(time_slots) > 0:
                plan["schedule"] = self.split_into_stages(sentences, time_slots, plan["required_time"])

        plan["now_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return plan
    
    def clear_plans(self, user_id):
        """清除指定用户的所有学习计划"""
        if user_id in self.plans:
            self.plans[user_id] = []
        return True


study_plan_manager = StudentPlan()


class TaskManager:
    def __init__(self):
        self.tasks = {}  # 格式: {user_id: [task1, task2...]}

    def add_task(self, user_id, task_type, content, due_date=None, send_time=None):
        """添加新任务"""
        if user_id not in self.tasks:
            self.tasks[user_id] = []

        task = {
            "id": len(self.tasks[user_id]) + 1,
            "type": task_type,
            "content": content,
            "due_date": due_date,
            "send_time": send_time or datetime.now().isoformat(),
            "completed": False
        }

        self.tasks[user_id].append(task)
        return task

    def get_tasks(self, user_id):
        """获取用户任务列表"""
        return self.tasks.get(user_id, [])

    def mark_task_completed(self, user_id, task_id):
        """标记任务为已完成"""
        if user_id in self.tasks:
            for task in self.tasks[user_id]:
                if task["id"] == task_id:
                    task["completed"] = True
                    return task
        return None


# 初始化任务管理器
task_manager = TaskManager()


# 添加任务API
@app.route('/api/tasks/send', methods=['POST'])
def send_task():
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        task_type = data.get("type")
        content = data.get("content")
        due_date = data.get("due_date")
        send_time = data.get("send_time")

        if not all([user_id, task_type, content]):
            return jsonify({"error": "缺少必要参数"}), 400

        task = task_manager.add_task(user_id, task_type, content, due_date, send_time)
        return jsonify({
            "message": "任务发送成功",
            "task": task
        }), 200
    except Exception as e:
        return jsonify({"error": f"发送任务失败: {str(e)}"}), 500


# 获取任务列表API
@app.route('/api/tasks/<user_id>', methods=['GET'])
def get_tasks(user_id):
    try:
        tasks = task_manager.get_tasks(user_id)
        return jsonify({"tasks": tasks}), 200
    except Exception as e:
        return jsonify({"error": f"获取任务失败: {str(e)}"}), 500


# 标记任务完成API
@app.route('/api/tasks/complete', methods=['POST'])
def complete_task():
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        task_id = data.get("task_id")

        if not all([user_id, task_id]):
            return jsonify({"error": "缺少必要参数"}), 400

        task = task_manager.mark_task_completed(user_id, task_id)
        if task:
            return jsonify({
                "message": "任务已标记为完成",
                "task": task
            }), 200
        else:
            return jsonify({"error": "未找到对应的任务"}), 404
    except Exception as e:
        return jsonify({"error": f"标记任务失败: {str(e)}"}), 500

@app.route("/api/study-plan/generate", methods=["POST"])
def generate_study_plan():
    """生成学习计划"""
    try:
        data = request.get_json()
        user_id = data.get("user_id", "default_user")
        poem_title = data.get("poem_title", "")
        available_time = data.get("available_time", [])
        target_date = data.get("target_date", None)

        if not poem_title or not available_time:
            return jsonify({"error": "缺少必要参数"}), 400
        plan = study_plan_manager.add_plan(user_id, poem_title, available_time, target_date)
        return jsonify({
            "message": "学习计划生成成功",
            "plan": plan
        }), 200
    except Exception as e:
        return jsonify({"error": f"计划生成失败: {str(e)}"}), 500


@app.route('/api/study-plan/<user_id>', methods=['GET'])
def get_study_plans(user_id):
    """获取用户的学习计划"""
    try:
        plans = study_plan_manager.get_study_plan(user_id)
        return jsonify({
            "user_id": user_id,
            "plans": plans
        })
    except Exception as e:
        return jsonify({"error": f"获取学习计划时出错: {str(e)}"}), 500


@app.route('/api/study-plan/update-progress', methods=['POST'])
def update_study_progress():
    """更新学习进度"""
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        plan_index = data.get("plan_index")
        stage_completed = data.get("stage_completed")

        if not all([user_id, plan_index is not None, stage_completed is not None]):
            return jsonify({"error": "缺少必要参数"}), 400

        updated_plan = study_plan_manager.update_study_plan(user_id, plan_index, stage_completed)

        if updated_plan:
            return jsonify({
                "message": "进度更新成功",
                "plan": updated_plan
            })
        else:
            return jsonify({"error": "未找到对应的学习计划"}), 404

    except Exception as e:
        return jsonify({"error": f"更新进度时出错: {str(e)}"}), 500


@app.route('/api/study-plan/recommend', methods=['POST'])
def recommend_study_time():
    """根据用户输入推荐学习时间"""
    try:
        data = request.get_json()
        poem_title = data.get("poem_title")
        preferred_days = data.get("preferred_days", ["周一", "周三", "周五"])
        daily_hours = data.get("daily_available_hours", 2)

        if not poem_title:
            return jsonify({"error": "缺少必要参数：poem_title"}), 400

        # 分析内容并推荐时间
        content = study_plan_manager.get_poem_content(poem_title)
        difficulty = study_plan_manager.content_difficulty(content)
        required_time = study_plan_manager.estimate_time(content, difficulty)

        # 生成推荐时间表
        recommended_schedule = []
        remaining_time = required_time

        for day in preferred_days:
            if remaining_time <= 0:
                break

            allocated_time = min(remaining_time, daily_hours * 60)
            recommended_schedule.append({
                "day": day,
                "recommended_duration": allocated_time,
                "time_suggestion": f"建议学习{allocated_time}分钟"
            })
            remaining_time -= allocated_time

        # 如果仍有剩余时间，提示增加学习时间
        if remaining_time > 0:
            return jsonify({
                "content_length": len(content),
                "difficulty": difficulty,
                "total_required_time": required_time,
                "recommendation": recommended_schedule,
                "message": f"根据内容分析，建议总共需要{required_time}分钟学习时间，当前设置的时间不足，还需要{remaining_time}分钟"
            })
        else:
            return jsonify({
                "content_length": len(content),
                "difficulty": difficulty,
                "total_required_time": required_time,
                "recommendation": recommended_schedule,
                "message": f"根据内容分析，建议总共需要{required_time}分钟学习时间"
            })

    except Exception as e:
        return jsonify({"error": f"推荐学习时间时出错: {str(e)}"}), 500


@app.route('/api/study-plan/modify', methods=['POST'])
def modify_study_plan():
    """修改已有的学习计划"""
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        plan_index = data.get("plan_index")

        if not all([user_id is not None, plan_index is not None]):
            return jsonify({"error": "缺少必要参数: user_id 和 plan_index"}), 400

        # 获取可选的修改参数
        new_poem_title = data.get("new_poem_title")
        new_available_time = data.get("new_available_time")
        new_target_date = data.get("new_target_date")
        # 检查是否有提供至少一个修改参数
        if not any([new_poem_title, new_available_time, new_target_date]):
            return jsonify({"error": "请提供至少一个要修改的参数"}), 400

        modified_plan = study_plan_manager.modify_plan(
            user_id,
            plan_index,
            new_available_time,
            new_target_date,
            new_poem_title
        )

        if modified_plan:
            return jsonify({
                "message": "学习计划修改成功",
                "plan": modified_plan
            }), 200
        else:
            return jsonify({"error": "未找到对应的学习计划"}), 404

    except Exception as e:
        return jsonify({"error": f"修改计划时出错: {str(e)}"}), 500

@app.route('/api/study-plan/clear', methods=['POST'])
def clear_study_plans():
    """清除用户的所有学习计划"""
    try:
        data = request.get_json()
        user_id = data.get("user_id")

        if not user_id:
            return jsonify({"error": "缺少必要参数: user_id"}), 400

        # 只清除指定用户的学习计划，不清除背诵记录
        study_plan_manager.clear_plans(user_id)

        return jsonify({
            "message": "学习计划已成功清除"
        }), 200

    except Exception as e:
        return jsonify({"error": f"清除学习计划时出错: {str(e)}"}), 500


@app.route('/api/poem', methods=['GET'])
def get_poem():
    """获取诗词列表"""
    all_poems = []
    # 合并小学和初中的诗词
    for category in POETRY_DATABASE.values():
        for poem in category:
            all_poems.append({
                "title": poem["title"],
                "author": poem["author"],
                "dynasty": poem["dynasty"],
                "grade": poem["grade"]
            })
    return jsonify(all_poems)


@app.route('/api/poem/search', methods=['GET'])
def search_poems():
    """根据关键词检索诗词"""
    keyword = request.args.get('keyword', '').strip()
    if not keyword:
        return jsonify([])  # 空关键词返回空结果

    # 支持按标题、作者、朝代检索
    search_results = []
    for cat, poems in POETRY_DATABASE.items():
        for poem in poems:
            # 标题包含关键词（不区分大小写）
            if (re.search(keyword, poem["title"], re.IGNORECASE) or
                    # 作者包含关键词
                    re.search(keyword, poem["author"], re.IGNORECASE) or
                    # 朝代包含关键词
                    re.search(keyword, poem["dynasty"], re.IGNORECASE)):
                search_results.append({
                    "title": poem["title"],
                    "author": poem["author"],
                    "dynasty": poem["dynasty"],
                    "grade": poem["grade"]
                })

    # 去重（如果有重复诗词）
    unique_results = []
    seen_titles = set()
    for item in search_results:
        if item["title"] not in seen_titles:
            seen_titles.add(item["title"])
            unique_results.append(item)

    return jsonify(unique_results)

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
