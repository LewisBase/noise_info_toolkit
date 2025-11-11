"""
Utility functions for background tasks
"""
import json
import pandas as pd
from typing import Dict, Any

def dataframe_to_dict(df: pd.DataFrame) -> dict:
    """Convert DataFrame to dictionary"""
    if df is None or df.empty:
        return {}
    
    # Convert DataFrame to dictionary
    result = {}
    for column in df.columns:
        result[column] = df[column].tolist()
    return result

def serialize_processing_results(file_path: str, results: Dict[str, Any]) -> str:
    """Serialize processing results to JSON string"""
    # Convert DataFrames to dictionaries
    frequency_spl = dataframe_to_dict(results.get("frequency_spl"))
    frequency_kurtosis = dataframe_to_dict(results.get("frequency_kurtosis"))
    
    serializable_results = {
        "file_path": file_path,
        "sampling_rate": results.get("sampling_rate"),
        "duration": results.get("duration"),
        "channels": results.get("channels"),
        "leq": float(results.get("leq")) if results.get("leq") is not None else None,
        "laeq": float(results.get("laeq")) if results.get("laeq") is not None else None,
        "lceq": float(results.get("lceq")) if results.get("lceq") is not None else None,
        "peak_spl": float(results.get("peak_spl")) if results.get("peak_spl") is not None else None,
        "peak_aspl": float(results.get("peak_aspl")) if results.get("peak_aspl") is not None else None,
        "peak_cspl": float(results.get("peak_cspl")) if results.get("peak_cspl") is not None else None,
        "total_kurtosis": float(results.get("total_kurtosis")) if results.get("total_kurtosis") is not None else None,
        "a_weighted_kurtosis": float(results.get("a_weighted_kurtosis")) if results.get("a_weighted_kurtosis") is not None else None,
        "c_weighted_kurtosis": float(results.get("c_weighted_kurtosis")) if results.get("c_weighted_kurtosis") is not None else None,
        "frequency_spl": frequency_spl,
        "frequency_kurtosis": frequency_kurtosis
    }
    
    return json.dumps(serializable_results, ensure_ascii=False, indent=2)