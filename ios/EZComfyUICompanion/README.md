# EZ ComfyUI Companion for iOS

This is a lightweight iOS wrapper for the existing EZ ComfyUI Showcase web app.

## What it does

- Opens the existing web UI in a native `WKWebView`.
- Keeps cookies and login state in the default iOS website data store.
- Provides native back, forward, reload, and server URL settings controls.
- Allows `http://` URLs for local or LAN development during the first wrapper phase.

## Default server

The default URL is configured in `EZComfyUICompanion/Info.plist`:

```xml
<key>EZComfyUIServerURL</key>
<string>https://imdjj.cn:1313/comfy/</string>
```

You can also change the server from the in-app settings button.

## Build

Open `EZComfyUICompanion.xcodeproj` in Xcode and run the `EZComfyUICompanion` scheme on an iPhone or iPad simulator.

For device testing, set a real development team and make sure the configured server is reachable from the device. The default `https://imdjj.cn:1313/comfy/` address is suitable for a real iPhone; use a LAN address only for local development.
