# -*- coding: utf-8 -*-
import sys
import os

# Add the parent directory to the path to import zhuanhuan module
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import the score storage class from zhuanhuan.py
from zhuanhuan import ScoreStorage


def test_score_storage():
    """Test the score storage functionality"""
    print("Testing score storage functionality...")
    print("=" * 50)

    # Create a new score storage instance
    storage = ScoreStorage()

    # Test adding scores
    print("Adding test scores...")
    storage.add_score(85, "背诵较为流畅，但有几处错误。")
    storage.add_score(90, "整体不错，节奏感很好。")
    storage.add_score(100, "完美背诵！")
    storage.add_score(75, "有改进空间，需要多练习。")
    print("Scores added successfully.")
    print()

    # Test retrieving scores
    print("Retrieving scores...")
    scores = storage.get_scores()
    print(f"Retrieved {len(scores)} scores:")
    for i, score_data in enumerate(scores, 1):
        print(f"  {i}. Score: {score_data['score']}, Feedback: {score_data['feedback']}, Time: {score_data['time']}")
    print()

    # Test clearing scores
    print("Clearing scores...")
    storage.clear_scores()
    scores = storage.get_scores()
    print(f"Scores after clearing: {len(scores)}")
    print()

    if len(scores) == 0:
        print("Score storage test passed!")
    else:
        print("Score storage test failed!")


if __name__ == "__main__":
    test_score_storage()
