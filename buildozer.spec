[app]
title = Trader Skill AI
package.name = traderskillai
package.domain = org.aihasanstudio
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json
version = 1.0.0
requirements = python3,flet==0.24.1,websockets,aiohttp,cryptography,certifi,idna,charset-normalizer,urllib3,requests
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,ACCESS_NETWORK_STATE,WAKE_LOCK
android.api = 33
android.minapi = 24
android.ndk = 25b
android.accept_sdk_license = True
p4a.branch = master

[buildozer]
log_level = 2
warn_on_root = 1
