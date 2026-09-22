using System;
using System.Collections.Generic;
using System.IO;
using BepInEx;

namespace ValheimCodexBridge
{
    [BepInPlugin("local.valheim.codex.bridge", "ValheimCodexBridge", "0.1.0")]
    public sealed class Plugin : BaseUnityPlugin
    {
        BridgeEngine engine;
        HttpServer server;
        GameAdapter adapter;
        PlayerViewCapture frames;
        bool originalBackground;
        bool backgroundChanged;
        void Awake()
        {
            try
            {
                var home = Environment.GetEnvironmentVariable("VALHEIM_CODEX_HOME") ??
                    Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Library/Application Support/ValheimCodex");
                var settings = (Dictionary<string,object>)MiniJson.Parse(File.ReadAllText(Path.Combine(home,"settings.json")));
                var trust = (Dictionary<string,object>)MiniJson.Parse(File.ReadAllText(Path.Combine(home,"trusted-players.json")));
                var config = new BridgeSettings {
                    Port=Convert.ToInt32(settings["bridge_port"]), MaxActionMs=Convert.ToInt32(settings["max_action_ms"]),
                    CombatEnabled=(bool)settings["combat_enabled"], ChatEnabled=(bool)settings["chat_enabled"],
                    ChatLimit=Convert.ToInt32(settings["maximum_message_length"]),
                    ChatCooldownSeconds=Convert.ToDouble(settings["min_seconds_between_messages"]),
                    ExpectedCharacter=(string)settings["character_name"], ExpectedWorld=(string)settings["world_id"] };
                foreach(var id in (List<object>)trust["owners"]) config.Owners.Add((string)id);
                AssemblyProbe.Write(Path.Combine(home,"api-inspection.json"));
                InstalledBindings.Verify();
                frames = gameObject.AddComponent<PlayerViewCapture>();
                frames.RecordingRequestPath=Path.Combine(home,"run/view-recording-until");
                adapter = new GameAdapter(frames, message => Logger.LogInfo(message));
                engine = new BridgeEngine(adapter, config, message => Logger.LogInfo(message));
                adapter.Attach(engine);
                originalBackground = UnityEngine.Application.runInBackground;
                UnityEngine.Application.runInBackground = true;
                backgroundChanged = true;
                frames.CanCapture = () => adapter.Ready;
                frames.OnFailure = message => { Logger.LogError(message); engine.Stop("frame capture failure"); };
                engine.Tick();
                server = new HttpServer(engine, config.Port, File.ReadAllText(Path.Combine(home,"bridge.token")).Trim(), message => Logger.LogInfo(message));
                server.Start();
                Logger.LogInfo("Bridge listening on 127.0.0.1; awaiting exact character/world configuration and local resume");
            }
            catch(Exception ex) { Logger.LogError("Bridge startup failed: " + ex.GetType().Name + ": " + ex.Message); server?.Dispose(); adapter?.Dispose(); if(frames) Destroy(frames); RestoreBackground(); engine = null; }
        }
        void Update()
        {
            if(engine == null) return;
            if(ZInput.GetKeyDown(UnityEngine.KeyCode.F8)) engine.Stop("local F8 emergency stop");
            adapter.DrainChat();
            engine.Tick();
        }
        void OnApplicationFocus(bool focused) { if(!focused) { engine?.Stop("game lost focus"); engine?.Tick(); } }
        void OnApplicationPause(bool value) { if(value) engine?.Stop("game paused"); }
        void RestoreBackground() { if(backgroundChanged) { UnityEngine.Application.runInBackground = originalBackground; backgroundChanged = false; } }
        void OnDestroy() { engine?.Stop("plugin unload"); adapter?.Dispose(); server?.Dispose(); if(frames) Destroy(frames); RestoreBackground(); }
    }
}
