@echo off
start "" /wait "%~dp0dist\DormWifiReconnect.exe" --stop --data-dir "%~dp0runtime"
