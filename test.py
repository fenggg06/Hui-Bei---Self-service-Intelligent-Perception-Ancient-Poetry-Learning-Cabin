from datetime import datetime
from flask import request, jsonify, Flask
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # 允许跨域请求


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
        """通过题目获取诗词内容 - 简单模拟"""
        # 实际应用中这里应该连接数据库或调用诗词API
        poem_dict = {
            "静夜思": "床前明月光，疑是地上霜。\n举头望明月，低头思故乡。",
            "春晓": "春眠不觉晓，处处闻啼鸟。\n夜来风雨声，花落知多少。",
            "登鹳雀楼": "白日依山尽，黄河入海流。\n欲穷千里目，更上一层楼。",
            "咏鹅": "鹅，鹅，鹅，曲项向天歌。\n白毛浮绿水，红掌拨清波。"
        }
        return poem_dict.get(title, "这是一首示例诗词。\n内容需要用户自行补充。\n请根据实际情况替换。")

    def split_poem_into_sentences(self, content):
        """将诗按句切分"""
        # 简单按行分割
        lines = content.split('\n')
        sentences = [line for line in lines if line.strip()]
        return sentences

    def add_plan(self, user_id, poem_title, available_time, target_date):
        """生成学习计划"""
        content = self.get_poem_content(poem_title)
        difficulty = self.content_difficulty(content)
        required_time = self.estimate_time(content, difficulty)
        sentences = self.split_poem_into_sentences(content)

        # 计算总可用时间
        time_slots = []
        total_available_minutes = 0
        for info_time in available_time:
            start_hour, start_min = map(int, info_time['开始'].split(":"))
            end_hour, end_min = map(int, info_time["结束"].split(":"))
            available_minutes = (end_hour - start_hour) * 60 + (end_min - start_min)
            total_available_minutes += available_minutes
            time_slots.append({
                "day": info_time['星期'],
                "start": info_time['开始'],
                "end": info_time['结束'],
                "minutes": available_minutes
            })

        plans = {
            "user_id": user_id,
            "content": content,
            "difficulty": difficulty,
            "required_time": required_time,
            "now_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "target_date": target_date,
            "schedule": []
        }

        # 如果有目标日期，则计算计划
        if target_date and len(time_slots) > 0:
            # 按天数分配任务
            stages = min(len(time_slots), max(1, len(sentences)))
            per_stage = max(1, len(sentences) // stages) if stages > 0 else 1

            for i in range(stages):
                if i < len(time_slots):
                    slot = time_slots[i]
                    start_idx = i * per_stage
                    end_idx = min((i + 1) * per_stage, len(sentences))
                    stage_sentences = sentences[start_idx:end_idx]

                    if stage_sentences:  # 确保有内容才添加
                        plans["schedule"].append({
                            "stage": i + 1,
                            "date": slot["day"],
                            "time": f"{slot['start']}-{slot['end']}",
                            "duration": min(slot["minutes"], required_time),
                            "task": f"背诵：{' '.join(stage_sentences)}"
                        })
        else:
            # 按时间槽分配任务
            if len(time_slots) > 0:
                per_slot = max(1, len(sentences) // len(time_slots))
                for i, slot in enumerate(time_slots):
                    start_idx = i * per_slot
                    end_idx = min((i + 1) * per_slot, len(sentences))
                    slot_sentences = sentences[start_idx:end_idx]

                    if slot_sentences:
                        plans["schedule"].append({
                            "stage": len(plans["schedule"]) + 1,
                            "date": slot["day"],
                            "time": f"{slot['start']}-{slot['end']}",
                            "duration": required_time // len(time_slots) if len(time_slots) > 0 else required_time,
                            "task": f"背诵: {' '.join(slot_sentences)}"
                        })

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
            if stage_completed <= len(plan["schedule"]):
                plan["schedule"][stage_completed - 1]["completed"] = True
            return plan
        else:
            return None

    def modify_plan(self, user_id, plan_index, new_available_time=None, new_target_date=None, new_poem_title=None):
        """修改已有的学习计划"""
        if user_id not in self.plans or plan_index >= len(self.plans[user_id]):
            return None

        plan = self.plans[user_id][plan_index]

        # 如果提供了新的诗词标题，则重新生成内容
        if new_poem_title:
            plan["content"] = self.get_poem_content(new_poem_title)
            plan["difficulty"] = self.content_difficulty(plan["content"])
            plan["required_time"] = self.estimate_time(plan["content"], plan["difficulty"])
            sentences = self.split_poem_into_sentences(plan["content"])
        else:
            sentences = self.split_poem_into_sentences(plan["content"])

        # 更新目标日期
        if new_target_date:
            plan["target_date"] = new_target_date

        # 如果提供了新的时间安排，则重新分配计划
        if new_available_time:
            # 清空原有计划
            plan["schedule"] = []

            # 计算总可用时间
            time_slots = []
            total_available_minutes = 0
            for info_time in new_available_time:
                start_hour, start_min = map(int, info_time['开始'].split(":"))
                end_hour, end_min = map(int, info_time["结束"].split(":"))
                available_minutes = (end_hour - start_hour) * 60 + (end_min - start_min)
                total_available_minutes += available_minutes
                time_slots.append({
                    "day": info_time['星期'],
                    "start": info_time['开始'],
                    "end": info_time['结束'],
                    "minutes": available_minutes
                })

            # 重新生成计划
            if plan["target_date"] and len(time_slots) > 0:
                # 按天数分配任务
                stages = min(len(time_slots), max(1, len(sentences)))
                per_stage = max(1, len(sentences) // stages) if stages > 0 else 1

                for i in range(stages):
                    if i < len(time_slots):
                        slot = time_slots[i]
                        start_idx = i * per_stage
                        end_idx = min((i + 1) * per_stage, len(sentences))
                        stage_sentences = sentences[start_idx:end_idx]

                        if stage_sentences:  # 确保有内容才添加
                            plan["schedule"].append({
                                "stage": i + 1,
                                "date": slot["day"],
                                "time": f"{slot['start']}-{slot['end']}",
                                "duration": min(slot["minutes"], plan["required_time"]),
                                "task": f"背诵：{' '.join(stage_sentences)}"
                            })
            else:
                # 按时间槽分配任务
                if len(time_slots) > 0:
                    per_slot = max(1, len(sentences) // len(time_slots))
                    for i, slot in enumerate(time_slots):
                        start_idx = i * per_slot
                        end_idx = min((i + 1) * per_slot, len(sentences))
                        slot_sentences = sentences[start_idx:end_idx]

                        if slot_sentences:
                            plan["schedule"].append({
                                "stage": len(plan["schedule"]) + 1,
                                "date": slot["day"],
                                "time": f"{slot['start']}-{slot['end']}",
                                "duration": plan["required_time"] // len(time_slots) if len(time_slots) > 0 else plan[
                                    "required_time"],
                                "task": f"背诵: {' '.join(slot_sentences)}"
                            })

        plan["now_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return plan


study_plan_manager = StudentPlan()


@app.route("/api/study-plan/generate", methods=["POST"])
def generate_study_plan():
    """生成学习计划"""
    try:
        data = request.get_json()
        user_id = data.get("user_id", "default_user")
        poem_title = data.get("poem_title", "")  # 修复字段名
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
    """
    更新学习进度
    请求参数:
    {
        "user_id": "用户ID",
        "plan_index": 0,
        "stage_completed": 1
    }
    """
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
    """
    根据用户输入推荐学习时间
    请求参数:
    {
        "poem_title": "要背诵的诗词标题",
        "preferred_days": ["周一", "周三", "周五"],
        "daily_available_hours": 2
    }
    """
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
    """
    修改已有的学习计划
    请求参数:
    {
        "user_id": "用户ID",
        "plan_index": 0,  # 要修改的计划索引
        "new_poem_title": "新的诗词标题(可选)",
        "new_available_time": [  # 新的时间安排(可选)
            {
                "星期": "周一",
                "开始": "09:00",
                "结束": "10:00"
            }
        ],
        "new_target_date": "2023-12-31"(可选)
    }
    """
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


if __name__ == "__main__":
    app.run(debug=True, port=5000)
