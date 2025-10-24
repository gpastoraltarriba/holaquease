import subprocess
import webbrowser
import time

# Ejecutar Uvicorn (ajusta según tu estructura de carpetas)
subprocess.Popen(["uvicorn", "main:app", "--reload"])

# Esperar un poco para que arranque el servidor
time.sleep(2)

# Abrir en Chrome
chrome_path = "C:/Program Files/Google/Chrome/Application/chrome.exe %s"
webbrowser.get(chrome_path).open("http://127.0.0.1:8000")