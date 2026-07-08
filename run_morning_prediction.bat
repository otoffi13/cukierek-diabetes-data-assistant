@echo off
cd /d C:\Users\grosz\Documents\agent_cukierek

python .\src\process_zip_exports.py
python .\src\build_sensitivity_index.py
python .\src\daily_prediction_message.py