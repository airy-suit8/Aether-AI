@echo off
echo Starting RAG Chatbot Server...
cd backend
"%LOCALAPPDATA%\Programs\Python\Python314\Scripts\uvicorn.exe" main:app --reload
pause
