<img width="366" height="709" alt="image" src="https://github.com/user-attachments/assets/54bae40d-ad61-4215-affd-3a4fd96e498d" /># HuiBei - Intelligent Ancient Poetry Recitation Tutoring System

## 📖 Overview
HuiBei is an intelligent educational platform based on speech recognition and AI technology, designed to help students improve their ancient Chinese poetry recitation skills. The system integrates Vosk speech recognition, DeepSeek AI scoring, intelligent study plan generation, and provides a dual-perspective learning management experience for both students and parents.

## ✨ Core Features

### Student Portal Features
- **Voice Recognition Recitation**: Real-time capture of student poetry recitation
- **AI-Powered Scoring**: Precise scoring and personalized feedback based on DeepSeek large language model
- **Poetry Database**: Comprehensive collection of ancient poems from elementary to middle school grades
- **Progress Tracking**: Visual display of recitation history and performance trends
- **Personalized Roles**: Multiple learning role options to enhance engagement
- **Font Adjustment**: Support for font size customization for optimal reading experience
- **Dark Mode**: Eye-friendly theme switching for different usage scenarios

### Parent Portal Pro Features
- **Student Learning Monitoring**: Real-time view of children's learning status and recitation records
- **Recitation Record Management**: Complete recitation history, scores, and mastery statistics
- **Intelligent Study Plans**: Automatically generate personalized study plans based on poem difficulty and student availability
- **Task Management System**: Send reminders and learning assignments to students
- **Poetry Search**: Quick search by title, author, or dynasty
- **Data Visualization**: Charts displaying learning progress, completion rates, and mastery levels
- **Multi-Time Slot Planning**: Flexible setup of multiple weekly learning time slots
- **Plan Modification**: Adjust learning goals and schedules at any time
- **Progress Tracking**: Real-time monitoring of study plan completion

## 🛠️ Technology Stack

### Backend Technologies
- **Python 3.7+**: Primary development language
- **Flask**: Web framework providing RESTful API services
- **Vosk**: Offline Chinese speech recognition engine
- **sounddevice**: Audio capture library
- **Ollama + DeepSeek-r1:7b**: Locally deployed AI model for intelligent scoring
- **Flask-CORS**: Cross-Origin Resource Sharing support

### Frontend Technologies
- **HTML5/CSS3**: Modern responsive interface design
- **JavaScript (ES6+)**: Interactive frontend logic
- **Chart.js**: Data visualization charts
- **Font Awesome 6.4.0**: Icon library
- **Google Fonts**: Chinese fonts (ZCOOL XiaoWei, Ma Shan Zheng, Noto Serif SC)

### Data Storage
- **JSON Files**: Poetry database, recitation records, and study plan persistence
- **Thread-Safe Storage**: Data protection in multi-threaded environments


## Prerequisites
- Python 3.7+
- Flask
- sounddevice
- vosk
- requests
- Chart.js (included via CDN)

## Installation
1. Clone or download this repository
2. Install required Python packages:
   ```bash
   pip install flask sounddevice vosk requests
   ```
3. Download the Vosk Chinese model and place it in the `vosk-model-cn-0.22` directory
4. Ensure Ollama is installed and running with the DeepSeek model

## Usage
1. Start the Flask server:
   ```bash
   python houduan.py
   ```
2. Open a web browser and navigate to `http://127.0.0.1:5000`
3. Select a poem from the database or enter custom text
4. Click "开始背诵" to begin speech recognition
5. Recite the poem aloud
6. Click "结束背诵" to stop recognition and get AI feedback
7. View scores in the score tracking panel
8. Use the visualization to track progress over time

## 🔌 API Documentation

### Speech Recognition Endpoints
- **GET /start**: Start speech recognition
- **GET /stop**: Stop speech recognition and return results

### Poetry Endpoints
- **GET /api/poems**: Get all poems list
- **GET /api/poems/grade/{grade}**: Get poems by grade level
- **GET /api/poem**: Get detailed poem information
- **GET /api/poem/search?keyword={keyword}**: Search poems by keyword (supports title/author/dynasty)

### AI Scoring Endpoint
- **POST /api/chat**: Submit recitation content for AI scoring and feedback
  - Parameters: `message` (recitation content), `session_id` (session ID)
  - Returns: Score (0-100) and detailed comments

### Score Management Endpoints
- **GET /api/scores**: Retrieve historical score records
- **POST /api/clear_scores**: Clear score history

### Session Management Endpoint
- **POST /api/current-poem**: Set current learning poem
  - Parameters: `title`, `author`, `dynasty`, `content`
  - Returns: `session_id` (session identifier)

### Study Plan Endpoints
- **POST /api/study-plan/generate**: Generate personalized study plan
  - Parameters: `user_id`, `poem_title`, `available_time`, `target_date`
  - Returns: Complete study plan with staged tasks

- **GET /api/study-plan/{user_id}**: Get all study plans for a user

- **POST /api/study-plan/update-progress**: Update study progress
  - Parameters: `user_id`, `plan_index`, `stage_completed`

- **POST /api/study-plan/recommend**: Recommend study time
  - Parameters: `poem_title`, `preferred_days`, `daily_available_hours`

- **POST /api/study-plan/modify**: Modify existing study plan
  - Parameters: `user_id`, `plan_index`, optional `new_poem_title`, `new_available_time`, `new_target_date`

- **POST /api/study-plan/clear**: Clear all study plans for a user
  - Parameters: `user_id`

### Task Management Endpoints
- **POST /api/tasks/send**: Send new task
  - Parameters: `user_id`, `type` (reminder/assignment), `content`, `due_date`

- **GET /api/tasks/{user_id}**: Get task list for a user

- **POST /api/tasks/complete**: Mark task as completed
  - Parameters: `user_id`, `task_id`


## File Structure
- `zhuanhuan.py`: Main Flask application with speech recognition and AI integration
- `indexcs.html`: Frontend interface
- `poetry_database.py`: Poetry database with grade-level organization
- `speech_result.txt`: Log file for recitation sessions
- `IMPLEMENTATION_SUMMARY.md`: Technical implementation details
- `todo.md`: Development task tracking

## Score Tracking
The application now includes comprehensive score tracking and visualization:
- Scores are automatically extracted from AI feedback
- Each score is stored with timestamp and feedback text
- A dedicated panel displays score history
- Interactive chart shows progress over time
- Controls to show/hide the score panel and clear history

## 🔐 Data Security
- All data stored locally to protect privacy
- Thread-safe concurrent processing
- Offline speech recognition model, no internet required

## 🚀 Performance Optimization
- Offline speech recognition for low-latency response
- Streaming AI responses for better user experience
- Asynchronous audio capture to prevent blocking
- Intelligent buffer queue management

## 🤝 Contributing
Feel free to fork this repository and submit pull requests to improve this educational tool together!

## 📄 License
This project is licensed under the MIT License

## 📞 Technical Support
If you encounter issues, please check:
1. Is Ollama service running properly?
2. Is the Vosk model path correct?
3. Is microphone permission granted?
4. Are all Python dependencies installed correctly?

<img width="427" height="844" alt="image" src="https://github.com/user-attachments/assets/b1df237a-ba5b-4519-871a-08cce3fe78d7" />
<img width="422" height="835" alt="image" src="https://github.com/user-attachments/assets/0b581e15-b07b-4ecb-95d2-d9f41d7e2dd5" />
<img width="422" height="835" alt="image" src="https://github.com/user-attachments/assets/e6399103-bbd9-4a2e-b87e-7c5ad7966889" />
<img width="420" height="812" alt="image" src="https://github.com/user-attachments/assets/123d24e8-f0c6-4812-8d4e-d49d30fbd4f1" />
<img width="420" height="812" alt="image" src="https://github.com/user-attachments/assets/bf353cd8-47a0-431e-9694-1aec74f91b0a" />
<img width="302" height="631" alt="image" src="https://github.com/user-attachments/assets/8285f349-0506-4abe-bb3d-df9504155d66" />
<img width="366" height="709" alt="image" src="https://github.com/user-attachments/assets/91835a77-3ba1-46b4-b3df-d1094dbefe50" />
<img width="366" height="709" alt="image" src="https://github.com/user-attachments/assets/16e8d8cc-8386-47d6-83c1-28083dab9df6" />
<img width="240" height="505" alt="屏幕截图 2026-06-08 195728" src="https://github.com/user-attachments/assets/61898df8-19c3-4061-8f59-ed318853c954" />















