using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;

namespace ValheimCodexBridge
{
    public sealed class BridgeEngine
    {
        readonly IGameAdapter adapter;
        readonly BridgeSettings settings;
        readonly Action<string> log;
        readonly MainThreadDispatcher dispatcher = new MainThreadDispatcher();
        readonly ControlState inputs = new ControlState();
        readonly List<ChatEvent> chat = new List<ChatEvent>();
        readonly List<object> tools;
        readonly Queue<string> recentSpeech = new Queue<string>();
        readonly string session = Guid.NewGuid().ToString("N");
        readonly object safety = new object();
        long expiry, lastFrame, chatId;
        double lastSpeech = double.NegativeInfinity;
        volatile bool paused = true;
        string snapshot = "{}";
        public BridgeEngine(IGameAdapter adapter, BridgeSettings settings, Action<string> log)
        {
            this.adapter = adapter; this.settings = settings; this.log = log;
            if (settings.MaxActionMs < 1 || settings.MaxActionMs > 1500) throw new ArgumentException("Invalid maximum lease");
            using (var reader = new StreamReader(typeof(BridgeEngine).Assembly.GetManifestResourceStream("ValheimCodexBridge.Core.game-tools.json")))
                tools = (List<object>)MiniJson.Parse(reader.ReadToEnd());
        }
        public object Tools => tools;
        public object RenewTravel() => dispatcher.Invoke(() => {
            lock(safety) {
                if(paused || !IsReady() || !adapter.GameplayReady) return Json.Obj("ok",false);
                adapter.RenewTravel(); return Json.Obj("ok",true);
            }
        });
        public bool Paused => paused;
        public bool CombatEnabled => settings.CombatEnabled;
        public int MaxActionMs => settings.MaxActionMs;
        public string PauseReason { get; private set; } = "Local resume required";
        public string Health => snapshot;
        public void Stop(string reason)
        {
            lock (safety)
            {
                paused = true; PauseReason = reason;
                dispatcher.CancelPending();
            }
            log("stop requested: " + reason);
            // Inputs are applied only on the next Unity tick; pause prevents re-acquisition.
        }
        public void ResumeLocal()
        {
            // Never offered as an MCP tool. Only local operator / verified owner path.
            lock (safety) { dispatcher.CancelPending(); paused = false; PauseReason = null; }
            log("local resume requested");
        }
        public void Tick()
        {
            try
            {
                var now = MainThreadDispatcher.Now;
                if (lastFrame != 0 && now - lastFrame > MainThreadDispatcher.Ms(2000)) Stop("main-thread heartbeat gap");
                lastFrame = now;
                lock (safety)
                {
                    if (!IsReady()) { if (!paused) Stop("player/world not ready"); inputs.Clear(); }
                    if (paused || now >= expiry)
                    {
                        if (inputs.Held) log(paused ? "all held controls released" : "watchdog: input lease expired");
                        inputs.Clear();
                    }
                    adapter.Apply(inputs);
                }
                dispatcher.Pump();
                lock (safety) { if (paused) inputs.Clear(); adapter.Apply(inputs); }
                snapshot = Json.Write(Json.Obj("ok", true, "session_id", session, "ready", IsReady(),
                    "reason", ReadinessReason(), "pause_reason", PauseReason, "paused", paused, "world_id", adapter.WorldId,
                    "character_name", adapter.CharacterName, "combat_enabled", settings.CombatEnabled,
                    "chat_limit", Math.Min(settings.ChatLimit, adapter.ChatLimit), "max_action_ms", settings.MaxActionMs,
                    "held", inputs.Held || adapter.HasHeldInput, "main_thread_utc", DateTime.UtcNow.ToString("O")));
            }
            catch (Exception ex)
            {
                Stop("adapter exception"); inputs.Clear();
                try { adapter.Apply(inputs); } catch { }
                snapshot = Json.Write(Json.Obj("ok",false,"ready",false,"paused",true,"reason","adapter exception"));
                log("adapter exception: " + ex.GetType().Name);
            }
        }
        bool IsReady() => adapter.Ready && adapter.CharacterName == settings.ExpectedCharacter &&
            adapter.WorldId == settings.ExpectedWorld && settings.ExpectedWorld != "configure-your-world";
        string ReadinessReason() => adapter.Reason ?? (adapter.CharacterName != settings.ExpectedCharacter ? "Configured character does not match" :
            settings.ExpectedWorld == "configure-your-world" ? "Configure the observed world_id before resuming" :
            adapter.WorldId != settings.ExpectedWorld ? "Configured world does not match" : null);
        public void ReceiveChat(string sender, string stableId, bool verified, string channel, string text, string timestamp = null)
        {
            // Adapter must call only for messages really delivered to the client on main thread.
            if (text == null || text.Length > 4096) return;
            // Never file another world's dialogue under the configured world's memories.
            if (adapter.WorldId != settings.ExpectedWorld || adapter.CharacterName != settings.ExpectedCharacter) return;
            var evt = new ChatEvent { EventId = ++chatId, Timestamp = timestamp ?? DateTime.UtcNow.ToString("O"),
                Sender = sender, SenderId = stableId, IdentityVerified = verified, Channel = channel, Text = text };
            chat.Add(evt); if (chat.Count > 500) chat.RemoveAt(0);
            log("incoming chat event " + evt.EventId); // contents are stored by service, not unbounded logs
            if (verified && stableId != null && settings.Owners.Contains(stableId))
            {
                switch (text.Trim().ToLowerInvariant())
                {
                    case "!codex stop": case "!codex pause": Stop("verified owner"); break;
                    case "!codex resume": ResumeLocal(); break;
                }
            }
        }
        public object Call(string name, Dictionary<string, object> args)
        {
            Validate(name, args);
            if (name == "health") return MiniJson.Parse(Health);
            if (name == "stop") { Stop("MCP emergency stop"); return Json.Obj("ok", true, "paused", true, "release", "next Unity tick"); }
            return dispatcher.Invoke(() => Execute(name, args));
        }
        object Execute(string name, Dictionary<string, object> a)
        {
            if (name == "get_chat")
            {
                long after = (long)Number(a, "after_event_id", 0); int limit = (int)Number(a, "limit", 50);
                var events = chat.Where(c => c.EventId > after).Take(limit).ToList();
                return Json.Obj("session_id", session, "events", events.Select(c => c.ToJson()).ToArray(),
                    "cursor", events.Count == 0 ? Math.Min(after, chatId) : events.Last().EventId,
                    "dropped", chat.Count > 0 && after < chat[0].EventId - 1);
            }
            if (name == "get_status" && adapter.WorldId != null && adapter.WorldId == settings.ExpectedWorld && adapter.CharacterName == settings.ExpectedCharacter)
                return adapter.Status(); // Own status remains readable during death/menu pause.
            if (!IsReady()) throw new InvalidOperationException("Verified game adapter, character, and world required: " + adapter.Reason);
            if (name == "observe_player_view") return adapter.Observe();
            if (name == "get_inventory") return adapter.InventoryAction(name, a);
            lock (safety)
            {
                if (paused) throw new InvalidOperationException("Emergency pause is latched; local resume required");
                if (name == "send_chat")
                {
                    string text = (string)a["text"], channel = a.ContainsKey("type") ? (string)a["type"] : "normal";
                    if (!settings.ChatEnabled) throw new InvalidOperationException("Chat disabled");
                    if (text.Length > Math.Min(settings.ChatLimit, adapter.ChatLimit) || text.Any(char.IsControl) || text.TrimStart().StartsWith("/"))
                        throw new ArgumentException("Invalid chat text");
                    double now = MainThreadDispatcher.Now / (double)Stopwatch.Frequency;
                    string normalized = new string(text.ToLowerInvariant().Where(char.IsLetterOrDigit).ToArray());
                    if (now - lastSpeech < settings.ChatCooldownSeconds || recentSpeech.Any(s => Similar(s, normalized)))
                        throw new InvalidOperationException("Chat cooldown or near-duplicate suppression");
                    adapter.SendChat(text, channel); lastSpeech = now;
                    recentSpeech.Enqueue(normalized); if (recentSpeech.Count > 12) recentSpeech.Dequeue();
                    log("outgoing chat submitted to game");
                    return Json.Obj("ok", true);
                }
                if (!settings.CombatEnabled && (name == "primary_attack" || name == "secondary_attack" || name == "block"))
                    throw new InvalidOperationException("Combat disabled until movement/chat/memory acceptance checks pass");
                if (name == "motor")
                {
                    // Replace a desired velocity atomically: never Apply a cleared
                    // state between consecutive local perception results.
                    if (!adapter.GameplayReady || !adapter.MotorReady((int)Number(a,"frame_id",0)))
                    { inputs.Clear(); adapter.Apply(inputs); return Json.Obj("ok",false,"error","Motor image is stale or gameplay unavailable"); }
                    bool block = (bool)a["block"];
                    string button = (string)a["button"];
                    if (!settings.CombatEnabled && (block || button == "primary_attack"))
                        throw new InvalidOperationException("Combat disabled");
                    int lease = (int)Number(a,"duration_ms",0);
                    if (lease > settings.MaxActionMs) throw new ArgumentException("Lease exceeds configured maximum");
                    adapter.CancelTravel("local motor");
                    inputs.Forward=(float)Number(a,"forward",0); inputs.Strafe=(float)Number(a,"strafe",0);
                    inputs.YawRate=(float)Number(a,"yaw_rate",0); inputs.PitchRate=(float)Number(a,"pitch_rate",0);
                    inputs.Sprint=(bool)a["sprint"]; inputs.Block=block; inputs.Motor=true;
                    expiry=MainThreadDispatcher.Now+MainThreadDispatcher.Ms(lease); inputs.Deadline=expiry;
                    if(button != "none")
                    {
                        if(button != "jump" && !adapter.PrecisionReady((int)Number(a,"frame_id",0)))
                        { inputs.Clear(); adapter.Apply(inputs); return Json.Obj("ok",false,"error","Refresh aim before precise motor action"); }
                        var effect=adapter.Pulse(button,0);
                        if(effect is Dictionary<string,object> result && result.TryGetValue("ok",out var ok) && ok is bool value && !value)
                        { inputs.Clear(); adapter.Apply(inputs); return result; }
                    }
                    return Json.Obj("ok",true,"duration_ms",lease);
                }
                if (name != "travel_to" && name != "stride" && name != "approach_interact") adapter.CancelTravel("replaced by " + name);
                inputs.Clear(); // each short action replaces the previous lease
                if (name == "open_map" || name == "close_map" || name == "map_zoom")
                { adapter.Apply(inputs); return adapter.MapAction(name,a); }
                if (name == "open_inventory" || name == "close_inventory" || name == "inventory_move" || name == "inventory_use" ||
                    name == "select_recipe" || name == "craft_selected" || name == "cancel_crafting")
                {
                    adapter.Apply(inputs); // opening a panel must first release movement/block
                    var result = adapter.InventoryAction(name, a);
                    log("inventory action: " + name);
                    return result;
                }
                if (!adapter.GameplayReady)
                    return Json.Obj("ok", false, "error", "Close the inventory or map before moving, looking, fighting, or using the hotbar");
                if (name == "travel_to" || name == "stride" || name == "approach_interact" || name == "halt")
                { adapter.Apply(inputs); return adapter.TravelAction(name,a); }
                if (name == "move")
                { inputs.Forward = (float)Number(a,"forward",0); inputs.Strafe = (float)Number(a,"strafe",0); inputs.Sprint = a.ContainsKey("sprint") && (bool)a["sprint"]; }
                else if (name == "block") inputs.Block = true;
                else if (name == "look") adapter.Look((float)Number(a,"delta_yaw",0),(float)Number(a,"delta_pitch",0));
                else if (name == "aim_at") adapter.Aim((float)Number(a,"x",0.5), (float)Number(a,"y",0.5), a.ContainsKey("ground") && (bool)a["ground"],(int)Number(a,"frame_id",0));
                else
                {
                    if ((name=="interact" || name=="primary_attack" || name=="secondary_attack") && !adapter.PrecisionReady((int)Number(a,"frame_id",0)))
                        return Json.Obj("ok",false,"error","Stopped travel. Your body or view moved since that image; observe and aim again before a precise action.");
                    var effect = adapter.Pulse(name, (int)Number(a,"slot",0));
                    if (effect is Dictionary<string,object> result && result.TryGetValue("ok", out var ok) && ok is bool value && !value) return result;
                }
                int duration = (int)Number(a,"duration_ms",1);
                if (duration > settings.MaxActionMs) { inputs.Clear(); throw new ArgumentException("Lease exceeds configured maximum"); }
                expiry = MainThreadDispatcher.Now + MainThreadDispatcher.Ms(duration);
                inputs.Deadline = expiry;
                log("action: " + name + " lease_ms=" + duration);
                return Json.Obj("ok",true,"duration_ms",duration);
            }
        }
        static bool Similar(string a, string b)
        {
            if (a == b) return true;
            if (Math.Abs(a.Length-b.Length) > Math.Max(a.Length,b.Length)/5) return false;
            int[] prev = Enumerable.Range(0,b.Length+1).ToArray();
            for (int i=1;i<=a.Length;i++) { int[] row = new int[b.Length+1]; row[0]=i;
                for(int j=1;j<=b.Length;j++) row[j]=Math.Min(Math.Min(row[j-1]+1,prev[j]+1),prev[j-1]+(a[i-1]==b[j-1]?0:1)); prev=row; }
            return prev[b.Length] <= Math.Max(a.Length,b.Length)*0.15;
        }
        static double Number(Dictionary<string,object> a, string key, double fallback) => a.TryGetValue(key,out var v) ? Convert.ToDouble(v) : fallback;
        void Validate(string name, Dictionary<string,object> args)
        {
            var def = tools.Cast<Dictionary<string,object>>().FirstOrDefault(t => (string)t["name"] == name);
            if (def == null) throw new ArgumentException("Unknown tool");
            var schema = (Dictionary<string,object>)def["inputSchema"];
            var props = (Dictionary<string,object>)schema["properties"];
            foreach(var required in (List<object>)schema["required"]) if (!args.ContainsKey((string)required)) throw new ArgumentException("Missing " + required);
            foreach(var kv in args)
            {
                if(!props.ContainsKey(kv.Key)) throw new ArgumentException("Unexpected argument: " + kv.Key);
                var p=(Dictionary<string,object>)props[kv.Key]; string t=(string)p["type"];
                if(t=="boolean" && !(kv.Value is bool)) throw new ArgumentException("Boolean required");
                if(t=="string")
                {
                    if(!(kv.Value is string str)) throw new ArgumentException("String required");
                    if(p.ContainsKey("maxLength") && str.Length>Convert.ToInt32(p["maxLength"])) throw new ArgumentException("String too long");
                    if(p.ContainsKey("minLength") && str.Length<Convert.ToInt32(p["minLength"])) throw new ArgumentException("String too short");
                    if(p.ContainsKey("enum") && !((List<object>)p["enum"]).Contains(str)) throw new ArgumentException("Invalid choice");
                }
                if(t=="number" || t=="integer")
                {
                    if(!(kv.Value is double) && !(kv.Value is int) && !(kv.Value is long)) throw new ArgumentException("Number required");
                    double v=Convert.ToDouble(kv.Value);
                    if(double.IsNaN(v)||double.IsInfinity(v)||v<Convert.ToDouble(p["minimum"])||v>Convert.ToDouble(p["maximum"])||(t=="integer"&&Math.Truncate(v)!=v)) throw new ArgumentException("Number out of range");
                }
            }
        }
    }
    public sealed class ImageResult
    {
        public readonly byte[] Png;
        public readonly object Metadata;
        public ImageResult(byte[] png,object metadata=null) { if(png == null || png.Length < 8 || png.Length > 8000000) throw new ArgumentException("Invalid image"); Png=png;Metadata=metadata; }
    }
}
