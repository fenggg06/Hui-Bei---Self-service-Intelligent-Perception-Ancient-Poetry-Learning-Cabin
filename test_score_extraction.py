# -*- coding: utf-8 -*-
import sys
import os

# Add the parent directory to the path to import zhuanhuan module
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import the score extraction function from zhuanhuan.py
from zhuanhuan import extract_score_from_text

def test_score_extraction():
    """Test the score extraction function with various inputs"""
    test_cases = [
        # (input_text, expected_score)
        ("得分85分，背诵较为流畅，但有几处错误。", 85),
        ("评分: 90分，整体不错", 90),
        ("获得分数100分，完美背诵！", 100),
        ("背诵不完整，得分30分", 30),
        ("100分，非常棒！", 100),
        ("评分75，有改进空间", 75),
        ("没有明确分数的文本", None),
        ("得分：85分，表现良好", 85),
        ("獲得分數92分，優秀", 92),
        ("評分60分，剛好及格", 60),
    ]
    
    print("Testing score extraction function...")
    print("=" * 50)
    
    passed = 0
    total = len(test_cases)
    
    for i, (input_text, expected) in enumerate(test_cases, 1):
        result = extract_score_from_text(input_text)
        status = "PASS" if result == expected else "FAIL"
        
        if status == "PASS":
            passed += 1
            
        print(f"Test {i}: {status}")
        print(f"  Input: {input_text}")
        print(f"  Expected: {expected}, Got: {result}")
        print()
    
    print("=" * 50)
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("All tests passed!")
    else:
        print("Some tests failed!")

if __name__ == "__main__":
    test_score_extraction()
