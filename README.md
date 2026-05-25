# Poetry Recitation Assistant

## Overview
The Poetry Recitation Assistant is an educational tool designed to help students practice and improve their Chinese poetry recitation skills. The application uses speech recognition to capture student recitations and leverages AI (DeepSeek) to provide feedback and scoring.

## Features
- Speech recognition for Chinese poetry recitation
- AI-powered feedback and scoring
- Score tracking and visualization
- Poetry database with grade-level organization
- Real-time recitation analysis

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
   python zhuanhuan.py
   ```
2. Open a web browser and navigate to `http://127.0.0.1:5000`
3. Select a poem from the database or enter custom text
4. Click "开始背诵" to begin speech recognition
5. Recite the poem aloud
6. Click "结束背诵" to stop recognition and get AI feedback
7. View scores in the score tracking panel
8. Use the visualization to track progress over time

## API Endpoints
- `GET /start`: Start speech recognition
- `GET /stop`: Stop speech recognition
- `POST /api/chat`: Get AI feedback for recitation
- `GET /api/scores`: Retrieve score history
- `POST /api/clear_scores`: Clear score history
- `GET /api/poems`: Get all poems
- `GET /api/poems/grade/<grade>`: Get poems by grade level

## File Structure
- `zhuanhuan.py`: Main Flask application with speech recognition and AI integration
- `index.html`: Frontend interface
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

## Contributing
Feel free to fork this repository and submit pull requests with improvements or bug fixes.

## License
This project is licensed under the MIT License.
