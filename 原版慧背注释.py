#coding: utf-8
from idlelib.iomenu import encoding
import pandas as pd
import sounddevice as sd#是python中一个简洁高效的音频库
import queue#线程安全队列模块
from vosk import Model, KaldiRecognizer#一个开源的离线语音识别库
import threading#多线程编程模块
import os#与操作系统进行交互
import sys#与解释器进行交互
from datetime import datetime#处理日期和时间的模块
import requests#最流行的HTTP客户端库
import json#处理JSON数据的模块
from flask import make_response
from flask import Flask, request, jsonify#轻量级Web框架
from flask_cors import CORS#Flask框架的跨域资源共享扩展，用于解决前后端分离架构中常见的“跨域请求被浏览器拦截”问题
import matplotlib.pyplot as plt
import plotly.express as px
import gradio as gr
plt.rcParams['font.sans-serif'] = ['SimHei']
plt.rcParams['axes.unicode_minus'] = False
app = Flask(__name__)#创建Flask应用,__name__它表示当前模块为应用入口
CORS(app)#允许跨域请求

# 检查模型路径是否存在
MODEL_PATH = r"..\yvyingzhuanhuan\vosk-model-cn-0.22\vosk-model-cn-0.22"
if not os.path.exists(MODEL_PATH):#如果路径不存在，则返回错误信息
    print(f"模型路径 {MODEL_PATH} 不存在，请检查路径。")
    sys.exit(1)#退出程序，（）中的数字表示退出码，默认为0，表示正常退出，错误码为1表示程序异常退出。

try:#
    # ===== 配置参数 =====
    SAMPLE_RATE = 16000#vosk强制采样率
    CHUNK_SIZE = 3000#每次读取音频数据块的大小，单位为字节
    BUFFER_SIZE = 8#音频缓冲区大小，单位为秒，累计8块数据后批量识别，降低CPU占用
    exit_flag = False  # 退出标志


    # ===== 改进的文本存储类 =====
    class EnhancedTextStorage:#线程安全的增强型文本存储类
        def __init__(self):#初始化存储结构
            self.lock = threading.Lock()#创建线程锁
            self.reset()  # 初始化时调用重置方法

        def reset(self):#重置所有存储内容
            """重置所有存储内容"""
            with self.lock:
                self.segments = []  # 分段存储列表，初始化空列表
                self.current_partial = ""  # 当前临时识别内容，初始为空
                self.last_final = ""  # 最后一次确认内容，初始为空

        def add_final_segment(self, text):#添加最终确认分段
            """添加最终确认的分段"""
            with self.lock:
                clean_text = text.replace(" ", "")#去除空格
                timestamp = datetime.now().strftime("%H:%M:%S")#获取当前时间并格式化为指定字符串，添加时间戳，
                #时间戳就是给识别结果打上时间标签。谁，什么适合，干了什么事，方便后续识别错误后的排查
                #将识别到的结果和时间戳打包成字典
                self.segments.append({
                    "text": clean_text,
                    "time": timestamp
                })
                self.last_final = clean_text#保存最后一次确认内容

        def update_partial(self, text):#更新实时临时识别内容
            """更新临时识别内容"""
            with self.lock:
                self.current_partial = text.replace(" ", "")#去除空格

        def get_combined_text(self):#合并所有分段为完整字符串
            """合并所有分段为完整字符串"""
            with self.lock:
                return "".join([seg["text"] for seg in self.segments])
            # 将所有分段内容合并为一个字符串并返回，""的作用无缝衔接，不添加额外字符

        def get_full_sequence(self):#获取带时间戳的完整序列
            """获取带时间戳的完整序列"""
            with self.lock:
                return "\n".join(
                    [f"[{seg['time']}] {seg['text']}"
                     for seg in self.segments]
                )
                # 将所有分段内容格式化为带时间戳的格式并合并为一个字符串，一列一列的并返回
        def get_structured_data(self):
            """获取结构化数据"""
            with self.lock:
                if not self.segments:
                    return pd.DataFrame()
                df=pd.DataFrame(self.segments)
                df["time"]=pd.to_datetime(df["time"],format="%H:%M:%S")#解析为事件对象
                df["timestamp_str"]=df["time"].dt.strftime(" %H:%M:%S")#保留原始字符串格式
                # 计算时间间隔
                df["duration_seconds"]=df["time"].diff().dt.total_seconds()#计算时间间隔，返回秒数
                df["duration_seconds"]=df["duration_seconds"].fillna(0)#将空值填充为0
                df["cumlative_duration"]=df["duration_seconds"].cumsum()#计算累计时间间隔，返回秒数
                df=df[["timestamp_str","text","duration_seconds","cumlative_duration"]]
                df.columns=["时间戳","识别结果","时间间隔","累计时间间隔"]
                return df

        @staticmethod
        def generate_table(df,save_path="识别结果表格.xlsx"):
            """生成表格"""
            if not isinstance(df, pd.DataFrame):
                return {"error": "输入必须是 pandas DataFrame"}
            if df.empty:
                return {"error":"无识别数据，无法生成表格"}
            if save_path.endswith(".xlsx"):
                df.to_excel(save_path,index=False,encoding="utf-8")
            elif save_path.endswith(".csv"):
                df.to_csv(save_path,index=False,encoding="utf-8-sig")
            print(f"📊 表格已保存至：{save_path}")
            table_json=df.to_dict("records")
            return{"表格数据":table_json,"保存路径":save_path}


    # ===== 初始化模型 =====
    model = Model(MODEL_PATH)#在指定路径加载预训练的中文语音识别模型
    recognizer = KaldiRecognizer(model, SAMPLE_RATE)
    # 创建KaldiRecognizer对象，用于进行语音识别，modrl为模型对象，SAMPLE_RATE为采样率
    recognizer.SetWords(False)#配置识别格式，False时只给纯文本，True时返回带词的json格式

    # 创建音频队列
    audio_queue = queue.Queue(maxsize=BUFFER_SIZE)
    # 创建音频队列对象，用于存储音频数据。maxsize为队列最大长度，BUFFER_SIZE为8，表示最多缓存8块数据。
    #queue.Queue()类创建一个有限容量的队列
    text_storage = EnhancedTextStorage()  # 全局存储对象
    #创建之前定义的EnhancedTextStorage()对象，用于存储识别结果，作为全局唯一的存储对象

    # ===== 音频采集线程 =====
    def audio_capture():#基于sounddevice库实现音频采集
        with sd.RawInputStream(#with sd.RawInputStream自动管理音频，实现麦克风的开启和关闭
                samplerate=SAMPLE_RATE,#采样率，这里的采样率必须和VOSK模型一致
                blocksize=CHUNK_SIZE,#每次抓取的音频数据块大小
                dtype="int16",#音频数据的格式，这里使用16位整数
                channels=1,#单声道，vosk仅支持单声道，使用双声道会识别错乱
                callback=lambda indata, *_: audio_queue.put(bytes(indata))
                #自动处理回调函数，将音频数据写入队列，*_表示忽略后面所有多余的参数，
                #audio_queue.put(bytes(indata)表示函数的返回值，将indata转换成字节并存入audio_queue队列
        ):
            print("🎤 麦克风已开启...")
            while not exit_flag:
                continue#循环，等待音频数据，如果队列为空，则进入下一次循环，等待音频数据


    # ===== 识别线程 =====
    def speech_recognition():#vosk实时语音识别的核心处理线程
        partial_result = ""#初始化临时结果变量
        while not exit_flag:#如果没收到退出信号就一直工作
            try:
                data = audio_queue.get(timeout=0.5)
                # 从队列中取出一个音频数据块，如果队列为空，则等待0.5秒
                if recognizer.AcceptWaveform(data):#尝试将数据块传递给vosk进行识别，如果识别成功，则获取识别结果
                    result = json.loads(recognizer.Result())#将结果转换成字典，json.loads()将json字符串转换成字典
                    text = result.get("text", "")#获取识别结果
                    if text:#如果识别结果不为空，则处理结果
                        print(f"\n✅ 最终识别结果：{text}")
                        text_storage.add_final_segment(text)#把结果存到全局存储（带时间戳）
                else:
                    partial = json.loads(recognizer.PartialResult())
                    # 获取临时结果
                    new_partial = partial.get("partial", "")
                    # 判断临时结果是否变化
                    if new_partial != partial_result:
                        partial_result = new_partial
                        print(f"⏳ 实时识别：{partial_result.ljust(40)}", end="\r", flush=True)
                        #ljust方法将字符串填充到指定长度，填充的字符为空格，填充后的字符串居左对齐,flush=True表示刷新缓冲区，将数据写入文件
                        text_storage.update_partial(new_partial)
            except queue.Empty:
                continue
                # 队列为空时，进入下一次循环，等待音频数据


    # ===== 修改后的控制函数 =====
    def start_recognition():#开始识别
        global exit_flag#声明全局变量
        exit_flag = False#设置退出开关，False表示为不退出
        text_storage.reset()  # 关键修改：每次启动时重置存储，清空“历史记录”
        capture_thread = threading.Thread(target=audio_capture, daemon=True)
        # 创建音频采集线程，指定线程要执行audio_capture()函数，daemon=True表示该线程为守护线程，主线程退出时，该线程也会退出
        recognition_thread = threading.Thread(target=speech_recognition, daemon=True)
        # 创建识别线程，指定线程要执行speech_recognition()函数，daemon=True表示该线程为守护线程，主线程退出时，该线程也会退出
        capture_thread.start()
        # 启动音频采集线程
        recognition_thread.start()
        # 启动识别线程
        return "语音识别已启动"


    def stop_recognition():#停止识别
        global exit_flag
        exit_flag = True
        sd.stop()#强制关闭音频流
        try:
            combined = text_storage.get_combined_text()#拿完整纯文本
            full_sequence = text_storage.get_full_sequence()#拿完整带时间戳的文本

            # 保存到文件（追加模式）
            with open("speech_result.txt", "a", encoding="utf-8") as f:
                #“a”表示追加模式，如果文件不存在，则创建文件，如果文件存在，则追加内容
                #encoding="utf-8"表示保存文件时使用utf-8编码，否则中文可能会乱码
                f.write(f"\n\n=== 会话记录 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                #datetime.now()获取当前时间，strftime()将时间格式化为字符串
                f.write(full_sequence)
                structured_df=text_storage.get_structured_data()
                if not structured_df.empty:
                    table_result = text_storage.generate_table(structured_df, f"识别表格_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
                    print("表格生成结果",table_result)  # 可选：输出表格生成结果信息
            return combined
        finally:
            text_storage.reset()  # 确保清理存储


    def generate_charts(df, save_dir="charts"):
        """
        生成可视化图表（柱状图+时间线图）
        :param df: 结构化DataFrame
        :param save_dir: 图表保存目录
        :return: 图表保存路径列表
        """
        if df.empty:
            return {"error": "无识别数据，无法生成图表"}

        # 创建保存目录
        os.makedirs(save_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        chart_paths = []

        # 1. 柱状图：每段识别文本的时长分布（看哪段说的久）
        fig1, ax1 = plt.subplots(figsize=(10, 6))
        bars = ax1.bar(range(len(df)), df["与上一段间隔（秒）"], color='#1f77b4', alpha=0.7)
        ax1.set_xlabel("识别段落序号", fontsize=12)
        ax1.set_ylabel("时长（秒）", fontsize=12)
        ax1.set_title(f"语音识别段落时长分布（{timestamp}）", fontsize=14, pad=20)
        ax1.set_xticks(range(len(df)))
        ax1.set_xticklabels([f"第{i + 1}段" for i in range(len(df))], rotation=45)

        # 在柱子上标注具体时长
        for i, bar in enumerate(bars):
            height = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width() / 2., height + 0.05,
                     f"{height:.1f}s", ha='center', va='bottom', fontsize=10)

        plt.tight_layout()
        bar_path = os.path.join(save_dir, f"时长分布柱状图_{timestamp}.png")
        plt.savefig(bar_path, dpi=300, bbox_inches='tight')
        plt.close()
        chart_paths.append(bar_path)

        # 2. 时间线图：识别流程的时间轴（看识别的时间顺序和累计时长）
        fig2 = px.line(df, x="时间戳", y="累计时长（秒）",
                       text="识别文本", title=f"语音识别时间线（{timestamp}）",
                       labels={"累计时长（秒）": "累计时长（秒）", "时间戳": "识别时间"},
                       hover_data={"识别文本": True, "与上一段间隔（秒）": ":,.1f"})
        fig2.update_traces(mode="markers+lines", marker=dict(size=8, color='#ff7f0e'))
        fig2.update_layout(xaxis_title="识别时间", yaxis_title="累计时长（秒）",
                           width=1000, height=600, font=dict(size=12))

        # 保存为HTML（支持交互，前端可直接嵌入）
        timeline_path = os.path.join(save_dir, f"识别时间线图_{timestamp}.html")
        fig2.write_html(timeline_path)
        chart_paths.append(timeline_path)

        print(f"📈 图表已保存至：{save_dir}")
        return {"图表保存路径": chart_paths}



    # ===== 保持原有API接口不变 =====
    def get_response(prompt):
        API_URL = "http://localhost:11434/api/generate"
        headers = {"Content-Type": "application/json"}
        # 创建请求头, 指定请求头为JSON格式，必须设置这个头，否则会返回错误
        xs = False#定义一个布尔变量，类似于一个开关
        data = {"model": "deepseek-r1:7b", "prompt": prompt, "stream": True}
        # 创建请求数据，包含模型名称、提示语、是否流式返回结果等信息
        try:
            response = requests.post(API_URL, headers=headers, json=data, stream=True)
            # 发送POST请求，并设置stream=True，表示返回结果是流式数据
            response.raise_for_status()
            #校验请求状态，如果状态码不是200，则抛出错误
            full_response = ""#创建一个变量，用于存储完整的响应结果
            for line in response.iter_lines():#逐行读取流式相应
                if line:#目的就是跳出空行
                    json_data = json.loads(line.decode("utf-8"))
                    #解析JSON数据，json.loads()将JSON字符串转换成字典,line.decode("utf-8")将字节数据转换成字符串
                    if json_data.get("response") == "</think>":#判断是否是</think>标签
                        xs = False
                    if json_data.get("response") == "</think>":
                        xs = True
                        continue
                    if xs:#拼接相应片段
                        full_response += json_data.get("response", "")
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
    def api_stop_recognition():#停止识别
        try:
            result = stop_recognition()
            return jsonify({"结果": result})
        except Exception as e:
            return jsonify({"错误": f"停止语音识别时出错: {str(e)}"}), 500
        #{str(e)}会显示异常的详细信息，方便调试   ，500表示服务器内部错误


    # 新接口地址
    # API_URL = "http://localhost:11434/api/generate"

    from flask import make_response  # 导入 make_response 用于自定义响应


    @app.route('/api/chat', methods=['POST'])
    def chat():
        try:
            #获取前端传递的用户消息
            message = request.form.get('message')
            #配置DeepSeek API信息
            url = "https://api.deepseek.com/chat/completions"#https://api.deepseek.com/chat/completions
            #构造请求体（发给deepseek的参数）
            payload = json.dumps({
                "messages": [
                    {
                        "content": "请牢记你是一个辅助中小学生进行古诗词背诵的背诵助手...",  # 系统提示
                        "role": "system"
                    },
                    {
                        "content": message,
                        "role": "user"
                    }
                ],
                "model": "deepseek-chat",#使用deepseek模型
                "frequency_penalty": 0,#重复惩罚（0=无惩罚，当值越高就越避免重复内容）
                "max_tokens": 4096,#模型最大输出
                "presence_penalty": 0,#存在惩罚（0=无惩罚，当值越高则越鼓励新内容）
                "response_format": {
                    "type": "text"
                },
                "stop": None,#停止词，当内容包含这些词时，模型将停止生成内容，None表示没有停止词
                "stream": False,#关闭流式响应
                "stream_options": None,#流式选项，None表示不使用流式响应
                "temperature": 1,#温度（0~2，值越高回复越随机，1=默认中等随机性）
                "top_p": 1,# 核采样（0~1，值越低越聚焦核心内容，1=默认不限制）
                "tools": None,#工具调用，None表示不使用工具调用
                "tool_choice": "none",#工具选择，none表示不使用工具调用
                "logprobs": False, # 是否返回 token 概率（False=不返回，节省带宽）
                "top_logprobs": None # 顶部 token 概率（False 时无需设置）
            })
            #创建请求头
            headers = {
                'Content-Type': 'application/json', # 告诉 DeepSeek 服务：请求体是 JSON 格式
                'Accept': 'application/json', # 告诉 DeepSeek 服务：客户端接收 JSON 格式响应
                'Authorization': 'Bearer sk-61aa143593534d1ca02a11e40b64b361' #密钥sk-61aa143593534d1ca02a11e40b64b361
            }
            #打印调试信息
            print("\n=== 发送给DeepSeek的请求 ===")
            print(f"请求URL: {url}")
            print(f"请求头: {headers}")
            print(f"请求内容: {payload}\n")
            #调用DeepSeek API（发送Post请求）
            response = requests.request("POST", url, headers=headers, data=payload)
            #打印 DeepSeek 的原始响应
            print("\n=== DeepSeek原始响应 ===")
            print(f"状态码: {response.status_code}")
            print(f"响应内容: {response.text}\n")
            #解析响应
            file = response.json()
            reply = file['choices'][0]['message']['content']

            print("\n=== 解析后的回复内容 ===")
            print(reply)

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

    if __name__ == "__main__":
        sys.stdout.reconfigure(encoding='utf-8')
        # 启动 Flask 应用
        # 显式设置与前端一致的IP和端口（127.0.0.1:5000）
        app.run(debug=True, host='127.0.0.1', port=5000)
        #debug = True 允许在代码中修改代码并自动重新加载服务器
        # host='127.0.0.1' 指定 IP 地址，默认为 0.0.0.0，表示所有可用的 IP 地址
        # port=5000 监听的端口号，默认为 5000
except Exception as e:
    print(f"初始化时出现错误: {e}")