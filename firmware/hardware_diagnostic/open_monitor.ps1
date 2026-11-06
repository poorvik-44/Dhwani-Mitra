$env:IDF_PATH = 'C:\esp\v6.1\esp-idf'
$env:IDF_TOOLS_PATH = 'C:\Espressif\tools'
$env:IDF_PYTHON_ENV_PATH = 'C:\Espressif\tools\python\v6.1\venv'
$env:ESP_IDF_VERSION = '6.1'
$env:PATH = 'C:\Espressif\tools\cmake\4.0.3\bin;C:\Espressif\tools\ninja\1.12.1;C:\Espressif\tools\python\v6.1\venv\Scripts;' + $env:PATH
Set-Location 'C:\Users\poorv\Documents\Codex\2026-11-05\we\dhwani mitra\firmware\hardware_diagnostic'
& 'C:\Espressif\tools\python\v6.1\venv\Scripts\python.exe' 'C:\esp\v6.1\esp-idf\tools\idf.py' -p COM7 monitor
