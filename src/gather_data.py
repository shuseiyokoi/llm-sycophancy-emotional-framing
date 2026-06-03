from load_data import load_data
from preprocess_data import preprocess_data
from summarize_data_derived_ethnicity import summarize_data

try:
    load_data()
    preprocess_data()
    summarize_data()
except Exception as e:
    print(f"Error occurred while loading or summarizing data: {e}")
