"""
Test script for database functionality
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database.database import DatabaseManager
from datetime import datetime, timedelta
import json

def test_database():
    """Test database functionality"""
    print("Testing database functionality...")
    
    # Create database manager
    db_manager = DatabaseManager()
    
    # Test data
    test_file_path = "test_audio.wav"
    test_metrics = {
        "leq": 65.2,
        "laeq": 63.8,
        "lceq": 67.1,
        "peak_spl": 78.5,
        "kurtosis": 2.8,
        "frequency_spl": {
            "63": 55.2,
            "125": 58.7,
            "250": 62.1,
            "500": 65.3,
            "1000": 63.8,
            "2000": 59.2,
            "4000": 52.7,
            "8000": 48.3,
            "16000": 42.1
        }
    }
    
    # Save test data
    print("Saving test data...")
    result_id = db_manager.save_processing_result(test_file_path, test_metrics)
    print(f"Saved test data with ID: {result_id}")
    
    # Retrieve latest result
    print("Retrieving latest result...")
    latest_result = db_manager.get_latest_result()
    print(f"Latest result: {json.dumps(latest_result, indent=2)}")
    
    # Retrieve history results
    print("Retrieving history results...")
    history_results = db_manager.get_history_results(limit=5)
    print(f"History results count: {len(history_results)}")
    
    print("Database test completed successfully!")

if __name__ == "__main__":
    test_database()