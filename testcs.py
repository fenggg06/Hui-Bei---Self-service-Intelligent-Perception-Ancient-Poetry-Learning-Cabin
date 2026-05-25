import re
from datetime import datetime, timedelta
from flask import request, jsonify, Flask
from flask_cors import CORS
from poetry_database import POETRY_DATABASE, get_poem_by_title

app = Flask(__name__)
CORS(app)  # 允许跨域请求

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


@app.route('/api/poems', methods=['GET'])
def get_poems():
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


@app.route('/api/poems/search', methods=['GET'])
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
    app.run(debug=True, port=5000)