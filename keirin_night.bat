@echo off
cd /d C:\Users\sames\Desktop\keirin_service
echo [%date% %time%] 夜バッチ開始 >> keirin_log.txt
python keirin_batch.py >> keirin_log.txt 2>&1
python keirin_supabase_save.py >> keirin_log.txt 2>&1
echo [%date% %time%] 夜バッチ完了 >> keirin_log.txt