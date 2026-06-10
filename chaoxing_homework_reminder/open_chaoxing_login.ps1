$ErrorActionPreference = "Stop"
$loginUrl = "https://passport2.chaoxing.com/login"
Start-Process $loginUrl
Write-Host "Opened Chaoxing login page. Please log in manually in the browser. This script does not read or save your password."
