using System;
using System.Collections.Concurrent;
using System.Linq;
using HarmonyLib;
using Splatform;
using UnityEngine;

namespace ValheimCodexBridge
{
    internal sealed class GameAdapter : IGameAdapter, IDisposable
    {
        static GameAdapter current;
        readonly Harmony harmony = new Harmony("local.valheim.codex.bridge.input");
        readonly PlayerViewCapture frames;
        readonly Action<string> log;
        readonly InventoryController inventory = new InventoryController();
        readonly MapController map = new MapController();
        readonly TravelIntent travel = new TravelIntent();
        readonly InteractionIntent approach = new InteractionIntent();
        Vector3 approachPoint;
        long travelStepped;
        int travelFrame;
        BridgeEngine engine;
        readonly ControlState held = new ControlState();
        readonly ConcurrentQueue<(string World, string Name, string Id, string Channel, string Text, string Time)> messages =
            new ConcurrentQueue<(string, string, string, string, string, string)>();
        Player controlled;
        string edge;
        long edgeDeadline;
        bool ownInput, injectingLook, releasing;
        readonly DamageReflex reflex = new DamageReflex();
        long motionDeadline;
        int motionId;
        Vector3 motionStart;
        object motion = Json.Obj("sequence", 0);
        Vector3 measuredPosition;
        int measuredFrame=-1;
        long measuredAt;
        double movedMeters,movingSeconds,idleSeconds,speed;
        bool measuredActive;
        int motorStepped=-1;
        float motorYaw, motorPitch;
        void MeasureMotion(bool active)
        {
            if(measuredFrame==Time.frameCount)return;
            measuredFrame=Time.frameCount;
            var p=Player.m_localPlayer;
            if(!p){measuredAt=0;return;}
            long now=MainThreadDispatcher.Now;var pos=p.transform.position;
            if(measuredAt!=0 && active && measuredActive)
            {
                double dt=(now-measuredAt)/(double)System.Diagnostics.Stopwatch.Frequency;
                double distance=Vector3.ProjectOnPlane(pos-measuredPosition,Vector3.up).magnitude;
                if(dt>0 && dt<.5)
                {
                    speed=speed*.8+distance/dt*.2;movedMeters+=distance;
                    if(speed>.35)movingSeconds+=dt;else idleSeconds+=dt;
                }
            }
            else speed=0;
            measuredAt=now;measuredPosition=pos;measuredActive=active;
        }
        object interaction;
        Vector3? aimedGround;
        long aimedAt;
        readonly System.Collections.Generic.Dictionary<int, (string Text, long Time)> combatText = new System.Collections.Generic.Dictionary<int, (string, long)>();
        void ReadCombatText()
        {
            long now = MainThreadDispatcher.Now;
            foreach (var key in combatText.Where(x => now-x.Value.Time > MainThreadDispatcher.Ms(15000)).Select(x=>x.Key).ToArray()) combatText.Remove(key);
            if (!GameplayReady || !DamageText.instance || Hud.IsUserHidden()) return;
            // Already-rendered HUD text, never scene entities or collision queries.
            foreach (var field in DamageText.instance.GetComponentsInChildren<TMPro.TMP_Text>())
            {
                var pos = field.transform.position;
                if (!field.isActiveAndEnabled || field.color.a < .1f || pos.x < 0 || pos.y < 0 || pos.x > Screen.width || pos.y > Screen.height) continue;
                int id = field.GetInstanceID();
                if (!combatText.ContainsKey(id) && combatText.Count < 24) combatText[id] = (Plain(field.text), now);
            }
        }
        static string Plain(string text) => System.Text.RegularExpressions.Regex.Replace(text ?? "", "<[^>]*>", "");
        string HoverText => Hud.instance && Hud.instance.m_hoverName ? Plain(Hud.instance.m_hoverName.text) : "";
        void TrackMotion(ControlState state, bool active)
        {
            var p = Player.m_localPlayer;
            if (!p) { motionDeadline = 0; return; }
            if (motionDeadline != 0 && (!active || state.Deadline != motionDeadline || MainThreadDispatcher.Now >= motionDeadline))
            {
                var delta = p.transform.position - motionStart; delta.y = 0;
                motion = Json.Obj("sequence", ++motionId, "distance_m", delta.magnitude, "blocked", delta.magnitude < 0.25f);
                motionDeadline = 0;
            }
            if (active && state.Deadline > MainThreadDispatcher.Now && state.Deadline != motionDeadline && (state.Forward != 0 || state.Strafe != 0))
            { motionStart = p.transform.position; motionDeadline = state.Deadline; }
        }

        public GameAdapter(PlayerViewCapture frames, Action<string> log)
        { this.frames = frames; this.log = log; }
        public void Attach(BridgeEngine value)
        {
            InstalledBindings.Verify(); engine = value; current = this;
            try
            {
                var controls = new[] { typeof(Vector3), typeof(bool), typeof(bool), typeof(bool), typeof(bool), typeof(bool),
                    typeof(bool), typeof(bool), typeof(bool), typeof(bool), typeof(bool), typeof(bool) };
                Patch(InstalledBindings.Required(typeof(Player), "SetControls", controls), nameof(ControlsPrefix));
                Patch(InstalledBindings.Required(typeof(Player), "SetMouseLook", new[] { typeof(Vector2) }), nameof(LookPrefix));
                // This overload runs AFTER Chat's asynchronous permission/filtering check.
                Patch(InstalledBindings.Required(typeof(Terminal), "AddString", new[] { typeof(PlatformUserID), typeof(string), typeof(Talker.Type), typeof(bool) }),
                    nameof(ChatDelivered), postfix: true);
            }
            catch { harmony.UnpatchSelf(); current = null; throw; }
            log("Valheim 1.0.15 bindings attached; relayed chat identity unverified; controls paused");
        }
        void Patch(System.Reflection.MethodInfo method, string hook, bool postfix = false)
        {
            var patch = new HarmonyMethod(typeof(GameAdapter), hook);
            harmony.Patch(method, prefix: postfix ? null : patch, postfix: postfix ? patch : null);
        }
        public string WorldId => Player.m_localPlayer && ZNet.World != null ? "world:" + ZNet.World.m_uid : null;
        public string CharacterName => Player.m_localPlayer ? Player.m_localPlayer.GetPlayerName() : null;
        public int ChatLimit => Chat.instance && Chat.instance.m_input && Chat.instance.m_input.characterLimit > 0
            ? Math.Min(160, Chat.instance.m_input.characterLimit) : 160;
        public bool Ready => Reason == null;
        public bool HasHeldInput => ownInput && held.Held && held.Deadline>MainThreadDispatcher.Now;
        public bool GameplayReady => Ready && !inventory.Owned && !InventoryGui.IsVisible() && !map.Owned && !Minimap.IsOpen();
        public string Reason
        {
            get
            {
                var p = Player.m_localPlayer;
                if (!p || ZNet.World == null || !ZNet.instance) return "Local character/world not loaded";
                if (!p.GetComponent<ZNetView>() || !p.GetComponent<ZNetView>().IsOwner()) return "Local character is not owned by this client";
                if (!Application.isFocused) return "Game is not focused";
                if (p.IsDead()) return "Character is dead";
                if (p.GetDoodadController() != null) return "Vehicle controls require manual handling in this version";
                if (!Hud.instance || !GameCamera.instance || GameCamera.InFreeFly()) return "Player camera/HUD unavailable";
                bool inputAllowed = (bool)InstalledBindings.TakeInput.Invoke(p, null);
                // Same TakeInput blockers as the reviewed Player implementation,
                // except for an inventory panel opened by this bridge itself.
                if (!inputAllowed && (inventory.Owned || map.Owned))
                    inputAllowed = (!Chat.instance || !Chat.instance.HasFocus()) && !Console.IsVisible() && !TextInput.IsVisible() &&
                        !StoreGui.IsVisible() && !Menu.IsVisible() && (!TextViewer.instance || !TextViewer.instance.IsVisible()) &&
                        (!Minimap.IsOpen() || map.Owned) && !PlayerCustomizaton.IsBarberGuiVisible() && !Hud.instance.m_buildUi.SearchFieldFocused &&
                        !p.InCutscene() && !p.IsTeleporting() && (!InventoryGui.IsVisible() || (inventory.Owned && inventory.PanelSafe));
                if (!inputAllowed || Hud.InRadial() || Hud.IsPieceSelectionVisible() || PlayerController.HasInputDelay)
                    return "Game input blocked by menu, loading, teleport, or cutscene";
                return null;
            }
        }
        void RequireReady() { if (!Ready) throw new InvalidOperationException(Reason); }
        static string ItemName(ItemDrop.ItemData item) => item == null ? null : Localization.instance.Localize(item.m_shared.m_name);
        public object Status()
        {
            var p = Player.m_localPlayer;
            if (!p) throw new InvalidOperationException("Local character not loaded");
            return Json.Obj("health", p.GetHealth(), "max_health", p.GetMaxHealth(), "stamina", p.GetStamina(), "max_stamina", p.GetMaxStamina(),
                "eitr", p.GetEitr(), "max_eitr", p.GetMaxEitr(), "right_hand", ItemName(p.RightItem), "left_hand", ItemName(p.LeftItem),
                "food", p.GetFoods().Select(f => Json.Obj("name", ItemName(f.m_item), "remaining_seconds", f.m_time)).ToArray(),
                "encumbered", p.IsEncumbered(), "crouching", p.IsCrouching(), "blocking", p.IsBlocking(), "swimming", p.IsSwimming(),
                "dead", p.IsDead(), "biome", p.GetCurrentBiome().ToString(), "world_id", WorldId, "character_name", CharacterName,
                "vision_source", "actual rendered game framebuffer, including HUD", "frame_age_ms", frames.AgeMs,
                "inventory", inventory.Snapshot(), "hover_text", GameplayReady ? HoverText : "", "last_interaction", interaction,
                "map",map.Snapshot(),
                "locomotion",Json.Obj("speed_mps",Math.Round(speed,2),"distance_m",Math.Round(movedMeters,2),
                    "moving_seconds",Math.Round(movingSeconds,2),"idle_seconds",Math.Round(idleSeconds,2),"walk_toggle",p.GetWalk(),
                    "camera_yaw",GameCamera.instance ? GameCamera.instance.transform.eulerAngles.y : 0,
                    "frame_ms",Math.Round(Time.smoothDeltaTime*1000,2)),
                "travel",travel.Snapshot(),
                "approach_interaction",approach.Snapshot(),
                "aim_estimate",aimedGround.HasValue && MainThreadDispatcher.Now-aimedAt < MainThreadDispatcher.Ms(30000) ?
                    Json.Obj("approximate",true,"ground_distance_m",Vector2.Distance(new Vector2(p.transform.position.x,p.transform.position.z),new Vector2(aimedGround.Value.x,aimedGround.Value.z)),"age_seconds",(MainThreadDispatcher.Now-aimedAt)/(double)System.Diagnostics.Stopwatch.Frequency) : null,
                "movement", motion, "damage_reflex", Json.Obj("blocking", reflex.Deadline > MainThreadDispatcher.Now, "triggers", reflex.Triggers),
                "recent_combat_text", combatText.Values.Select(x=>Json.Obj("text",x.Text,"age_seconds",(MainThreadDispatcher.Now-x.Time)/(double)System.Diagnostics.Stopwatch.Frequency)).ToArray(),
                "supplies", p.GetInventory().GetAllItems().GroupBy(i => ItemName(i)).Select(g => Json.Obj("name", g.Key, "count", g.Sum(i => i.m_stack))).ToArray(),
                "remote_chat_identity", "observed platform ID; unauthenticated relay; no privileged commands");
        }
        public ImageResult Observe() { RequireReady(); return frames.Latest(); }
        public void Apply(ControlState state)
        {
            inventory.Tick(engine);
            map.Tick(engine);
            ReadCombatText();
            bool active = engine != null && !engine.Paused && GameplayReady;
            MeasureMotion(active);
            TrackMotion(state, active);
            var local = Player.m_localPlayer;
            bool defending = reflex.Step(local ? local.GetHealth() : 0, local ? local.GetStamina() : 0,
                active && engine.CombatEnabled && local && !local.IsSwimming(), MainThreadDispatcher.Now, local ? local.GetMaxHealth() : 0);
            if (!active || controlled != Player.m_localPlayer) { Release(); if (!active) return; }
            controlled = Player.m_localPlayer; ownInput = true;
            held.Forward = state.Forward; held.Strafe = state.Strafe;
            held.Sprint = state.Sprint; held.Block = state.Block; held.Deadline = state.Deadline;
            if(state.Motor && state.Deadline>MainThreadDispatcher.Now && motorStepped!=Time.frameCount)
            {
                motorStepped=Time.frameCount;
                float dt=Mathf.Min(Time.unscaledDeltaTime,.05f);
                motorYaw=Mathf.MoveTowards(motorYaw,state.YawRate,600*dt);
                motorPitch=Mathf.MoveTowards(motorPitch,state.PitchRate,400*dt);
                if(!defending) InjectLook(motorYaw*dt,motorPitch*dt);
            }
            else if(!state.Motor) {motorYaw=motorPitch=0;}
            if(state.Motor && (local.IsSwimming() || local.IsEncumbered()))
            { held.Forward=held.Strafe=0; held.Sprint=false; edge=null; }
            if(approach.Active) StepApproach(active); else StepTravel(active);
            if (defending)
            {
                held.Forward = held.Strafe = 0; held.Sprint = false; held.Block = true;
                held.Deadline = reflex.Deadline; edge = null;
            }
            else if (state.Held && !state.Motor) edge = null;
        }
        void Release()
        {
            travel.Cancel("controls released");
            approach.Cancel("controls released");
            held.Clear(); edge = null;
            if (ownInput && controlled)
            {
                releasing = true;
                try
                {
                    // Auto-run is a normal input toggle, never a transform/velocity write.
                    controlled.m_autoRun = false;
                    bool toggleOff = controlled.ToggleBlock && (bool)InstalledBindings.Blocking.GetValue(controlled);
                    controlled.SetControls(Vector3.zero, false, false, false, false, toggleOff, false, false, false, false, false);
                }
                finally { releasing = false; ownInput = false; controlled = null; }
            }
            else { ownInput = false; controlled = null; }
        }
        public void Look(float yaw, float pitch)
        {
            RequireReady(); edge = null; InjectLook(yaw,pitch);
        }
        void InjectLook(float yaw,float pitch)
        {
            injectingLook = true;
            try { Player.m_localPlayer.SetMouseLook(new Vector2(yaw, pitch)); }
            finally { injectingLook = false; }
        }
        public void Aim(float x, float y, bool ground, int frameId)
        {
            RequireReady();
            var camera = GameCamera.instance.GetComponent<Camera>();
            var view=frames.GetView(frameId);
            var ray = view.Ray(x,y);
            var direction = ray.direction.normalized;
            aimedGround=null;
            if (ground)
            {
                // A flat-ground estimate from the supplied image point and our
                // own body/camera geometry. No terrain query or physics raycast.
                var p = Player.m_localPlayer;
                if (view.Ground(x,y,out var target))
                {
                    aimedGround=target; aimedAt=MainThreadDispatcher.Now;
                    var eye = p.m_eye.position;
                    var offset = camera.transform.InverseTransformDirection(camera.transform.position-eye);
                    var rotation = camera.transform.rotation;
                    for (int i=0;i<12;i++)
                    {
                        var from = eye+rotation*offset;
                        if ((target-from).sqrMagnitude < .01f) break;
                        rotation=Quaternion.LookRotation(target-from,Vector3.up);
                    }
                    direction=rotation*Vector3.forward;
                }
            }
            var forward = camera.transform.forward;
            float yaw = Mathf.DeltaAngle(Mathf.Atan2(forward.x, forward.z) * Mathf.Rad2Deg, Mathf.Atan2(direction.x,direction.z) * Mathf.Rad2Deg);
            float pitch = (Mathf.Asin(direction.y) - Mathf.Asin(forward.y)) * Mathf.Rad2Deg;
            Look(Mathf.Clamp(yaw,-90,90), Mathf.Clamp(pitch,-60,60));
        }
        public void RenewTravel() { travel.Renew(MainThreadDispatcher.Now); approach.Renew(MainThreadDispatcher.Now); }
        public void CancelTravel(string reason) { travel.Cancel(reason); approach.Cancel(reason); }
        public object TravelAction(string action,System.Collections.Generic.Dictionary<string,object> args)
        {
            if(action=="halt") { travel.Cancel("deliberate stop"); return Json.Obj("ok",true,"travel",travel.Snapshot()); }
            RequireReady();
            var p=Player.m_localPlayer;var pos=p.transform.position;
            var view=frames.GetView(Convert.ToInt32(args["frame_id"]));
            var now=MainThreadDispatcher.Now;
            if(travelFrame!=0 && !travel.Active && travel.Reason!="arrived" && view.Time<travelStepped)
                return Json.Obj("ok",false,"error","Movement was interrupted after this image. Observe again before choosing a new intention.");
            if(action=="approach_interact")
            {
                if(!view.Ground(Convert.ToSingle(args["x"]),Convert.ToSingle(args["y"]),out var ground) ||
                    Vector3.ProjectOnPlane(ground-pos,Vector3.up).magnitude>10)
                    return Json.Obj("ok",false,"error","Choose the base of a nearby visible target, within ten meters. This is an approximate flat-ground approach.");
                float distance=Vector3.ProjectOnPlane(ground-pos,Vector3.up).magnitude;
                if(Vector3.Distance(view.Body,pos)>2 && Vector3.Dot(Vector3.ProjectOnPlane(ground-view.Body,Vector3.up),Vector3.ProjectOnPlane(ground-pos,Vector3.up))<0)
                    return Json.Obj("ok",false,"error","The selected point was passed while thinking; observe again before approaching it.");
                // Validate the specific name before changing an existing route.
                approach.Start((string)args["expected_name"],distance>1.2f,p.GetHealth(),now,engine.MaxActionMs);
                travel.Cancel("new close interaction");
                approachPoint=ground+Vector3.up*.45f;
                if(distance>1.2f)travel.Start(pos.x,pos.z,pos.y,ground.x,ground.z,p.GetHealth(),false,8000,now,engine.MaxActionMs);
                travelFrame=view.Id;travelStepped=now;
                return Json.Obj("ok",true,"approach_interaction",approach.Snapshot());
            }
            // A health/water/block interruption requires a new view, not a late
            // replacement plan based on the frame from before that interruption.
            Vector3 target;
            bool selected;
            if(action=="stride")
            {
                var heading=Vector3.ProjectOnPlane(view.Forward,Vector3.up).normalized;
                // Anchor to the OBSERVED body, not a later position reached while
                // inference runs. A delayed answer cannot extend into unseen ground.
                target=view.Body+Quaternion.AngleAxis(Convert.ToSingle(args["heading"]),Vector3.up)*heading*Convert.ToSingle(args["distance"]);
                selected=heading.sqrMagnitude>.5f;
            }
            else selected=view.Ground(Convert.ToSingle(args["x"]),Convert.ToSingle(args["y"]),out target);
            if(!selected ||
                Vector3.ProjectOnPlane(target-pos,Vector3.up).magnitude>20)
                return Json.Obj("ok",false,"error","Choose nearer visible ground, within 20 meters; avoid sky, water and steep slopes.");
            var intended=Vector3.ProjectOnPlane(target-view.Body,Vector3.up);
            var remaining=Vector3.ProjectOnPlane(target-pos,Vector3.up);
            if(Vector3.Distance(view.Body,pos)>2 && Vector3.Dot(intended,remaining)<0)
                return Json.Obj("ok",false,"error","You already passed that image-selected point while thinking. Observe again; do not backtrack to an obsolete waypoint.");
            if(remaining.magnitude<=1.2f)
                return Json.Obj("ok",false,"error","That point is already within arrival distance. Halt to inspect/rest, or choose farther visible ground using the approximate range guide.");
            travel.Cancel("new destination"); // reset the previous short lease
            approach.Cancel("new travel destination");
            travel.Start(pos.x,pos.z,pos.y,target.x,target.z,p.GetHealth(),(bool)args["sprint"],action=="stride" ? 10000 : Convert.ToInt32(args["budget_ms"]),now,engine.MaxActionMs);
            travelFrame=view.Id;travelStepped=now;
            return Json.Obj("ok",true,"travel",travel.Snapshot());
        }
        void StepTravel(bool active)
        {
            var p=Player.m_localPlayer;
            if(!p) {travel.Cancel("player unavailable");return;}
            var now=MainThreadDispatcher.Now;var pos=p.transform.position;
            bool wasActive=travel.Active;
            if(!travel.Step(pos.x,pos.z,pos.y,p.GetHealth(),p.GetMaxHealth(),active,p.IsSwimming(),p.IsEncumbered(),now))
            { if(wasActive)travelStepped=now;return; }
            // Apply is called twice per Unity frame; steer only once per frame.
            if(Time.frameCount!=lastTravelRenderFrame)
            {
                lastTravelRenderFrame=Time.frameCount;
                var forward=GameCamera.instance.transform.forward;
                float desired=Mathf.Atan2((float)travel.TargetX-pos.x,(float)travel.TargetZ-pos.z)*Mathf.Rad2Deg;
                float angle=Mathf.DeltaAngle(Mathf.Atan2(forward.x,forward.z)*Mathf.Rad2Deg,desired);
                float step=180f*Mathf.Min(Time.deltaTime,.05f);
                float pitch=-8f-Mathf.Asin(Mathf.Clamp(forward.y,-1,1))*Mathf.Rad2Deg;
                if(approach.Active) FocusApproach(0,0); else Look(Mathf.Clamp(angle,-step,step),Mathf.Clamp(pitch,-step*.4f,step*.4f));
                // Walk along the desired world bearing while the camera turns.
                // Camera-relative forward/strafe avoids stop-turn-walk stair steps.
                float radians=angle*Mathf.Deg2Rad;
                travelForward=Mathf.Cos(radians);travelStrafe=Mathf.Sin(radians);
                if(approach.Active && travel.Distance<3){travelForward*=.65f;travelStrafe*=.65f;}
            }
            held.Forward=travelForward;held.Strafe=travelStrafe;held.Block=false;
            held.Sprint=travel.Sprint && p.GetStamina()>20 && travel.Distance>3;
            held.Deadline=travel.LeaseDeadline;
        }
        int lastTravelRenderFrame=-1;
        float travelForward,travelStrafe;
        int lastApproachFrame=-1;
        void FocusApproach(float yawOffset,float pitchOffset)
        {
            var camera=GameCamera.instance.GetComponent<Camera>();var eye=Player.m_localPlayer.m_eye.position;
            var offset=camera.transform.InverseTransformDirection(camera.transform.position-eye);
            var rotation=camera.transform.rotation;
            for(int i=0;i<12;i++)
            {
                var direction=approachPoint-(eye+rotation*offset);
                if(direction.sqrMagnitude<.01f)break;
                rotation=Quaternion.LookRotation(direction,Vector3.up);
            }
            var desired=rotation*Vector3.forward;var forward=camera.transform.forward;
            float yaw=Mathf.DeltaAngle(Mathf.Atan2(forward.x,forward.z)*Mathf.Rad2Deg,Mathf.Atan2(desired.x,desired.z)*Mathf.Rad2Deg)+yawOffset;
            float pitch=(Mathf.Asin(Mathf.Clamp(desired.y,-1,1))-Mathf.Asin(Mathf.Clamp(forward.y,-1,1)))*Mathf.Rad2Deg+pitchOffset;
            float dt=Mathf.Min(Time.deltaTime,.05f);
            Look(Mathf.Clamp(yaw,-120*dt,120*dt),Mathf.Clamp(pitch,-80*dt,80*dt));
        }
        string Caption(GameObject target)
        {
            // Same Hoverable callback as Hud.UpdateCrosshair for the one object
            // under the normal player's crosshair. Never search nearby objects.
            if(Hud.IsUserHidden())return "";
            var hover=target ? target.GetComponentInParent<Hoverable>() : null;
            return hover==null ? "" : Plain(hover.GetHoverText());
        }
        void StepApproach(bool active)
        {
            var p=Player.m_localPlayer;long now=MainThreadDispatcher.Now;
            if(!p || !approach.Step(active,p.GetHealth(),p.GetMaxHealth(),p.IsSwimming(),p.IsEncumbered(),now))
            {travel.Cancel("close interaction stopped");held.Clear();return;}
            InstalledBindings.UpdateHover.Invoke(p,null);
            var target=p.GetHoverObject();string caption=Caption(target);
            bool matches=approach.Matches(caption);
            if(matches)
            {
                travel.Cancel("named target in reach");approach.Arrived(now);held.Clear();
                if(approach.Confirm(target.GetInstanceID(),caption,now))
                    approach.Submitted(InteractTarget(approach.Expected,target.GetInstanceID()));
                return;
            }
            approach.Confirm(0,"",now);
            if(approach.Phase=="approaching")
            {
                StepTravel(active);
                if(!travel.Active)
                {
                    if(travel.Reason=="arrived")approach.Arrived(now);
                    else {approach.Cancel(travel.Reason);held.Clear();return;}
                }
            }
            if(approach.Phase=="aiming")
            {
                held.Clear();
                if(!string.IsNullOrWhiteSpace(caption)) {approach.Cancel("different visible target: "+caption.Split('\n')[0]);return;}
                if(lastApproachFrame!=Time.frameCount)
                {
                    lastApproachFrame=Time.frameCount;
                    int step=(int)((now-approach.AimingSince)/(double)MainThreadDispatcher.Ms(350));
                    float yaw=step==3 ? -6 : step==4 ? 6 : 0;
                    float pitch=step==1 ? -7 : step==2 ? 7 : step==5 ? -14 : step==6 ? 14 : 0;
                    FocusApproach(yaw,pitch);
                }
            }
        }
        public bool PrecisionReady(int frameId)
        {
            var view=frames.GetView(frameId);
            return Vector3.Distance(Player.m_localPlayer.transform.position,view.Body)<=.75f &&
                Vector3.Angle(GameCamera.instance.transform.forward,view.Forward)<=12;
        }
        public bool MotorReady(int frameId)
        {
            var view=frames.GetView(frameId);
            return MainThreadDispatcher.Now-view.Time<=MainThreadDispatcher.Ms(900) &&
                Vector3.Distance(Player.m_localPlayer.transform.position,view.Body)<4 &&
                Vector3.Angle(GameCamera.instance.transform.forward,view.Forward)<60;
        }
        public object Pulse(string action, int slot)
        {
            RequireReady(); edge = null;
            var p = Player.m_localPlayer;
            if (action == "interact")
                return InteractTarget();
            if (action == "use_hotbar") { p.UseHotbarItem(slot); return Json.Obj("ok",true,"submitted",true); }
            if (action != "jump" && action != "crouch" && action != "primary_attack" && action != "secondary_attack")
                throw new ArgumentException("Unknown normal input action");
            edge = action; edgeDeadline = MainThreadDispatcher.Now + MainThreadDispatcher.Ms(250);
            return Json.Obj("ok", true, "submitted", true);
        }
        object InteractTarget(string expected=null,int targetId=0)
        {
                var p=Player.m_localPlayer;
                InstalledBindings.UpdateHover.Invoke(p, null);
                var target = p.GetHoverObject();
                string caption=Caption(target);
                interaction = Json.Obj("had_target", target != null, "hover_text", caption);
                if (!target) return Json.Obj("ok", false, "error", "Nothing is in interaction reach at the crosshair. Aim at a visible pickup or move closer.", "interaction", interaction);
                if(expected!=null && (target.GetInstanceID()!=targetId || !approach.Matches(caption)))
                    return Json.Obj("ok",false,"error","The named crosshair target changed before interaction");
                if (target.GetComponentInParent<Interactable>() == null)
                    return Json.Obj("ok",false,"error","The crosshair is on a surface with no normal interaction. Aim at a visible pickup or station.","interaction",interaction);
                if (target)
                {
                    bool wasVisible = InventoryGui.IsVisible();
                    InstalledBindings.Interact.Invoke(p, new object[] { target, false, false });
                    if (!wasVisible) inventory.AdoptStationPanel();
                }
                return Json.Obj("ok", true, "submitted", true, "interaction", interaction);
        }
        public void SendChat(string text, string channel)
        {
            RequireReady();
            if (!Chat.instance || text.Length > ChatLimit || text.TrimStart().StartsWith("/")) throw new InvalidOperationException("Chat unavailable or invalid");
            var type = channel == "normal" ? Talker.Type.Normal : channel == "shout" ? Talker.Type.Shout :
                channel == "whisper" ? Talker.Type.Whisper : throw new ArgumentException("Unknown chat channel");
            Chat.instance.SendText(type, text);
        }
        public object InventoryAction(string action, System.Collections.Generic.Dictionary<string, object> arguments)
        {
            RequireReady();
            if (map.Owned) return Json.Obj("ok",false,"error","Close the map before using inventory controls");
            return inventory.Call(action, arguments);
        }
        public object MapAction(string action, System.Collections.Generic.Dictionary<string,object> arguments)
        {
            RequireReady();
            if (inventory.Owned) return Json.Obj("ok",false,"error","Close the inventory before using map controls");
            return map.Call(action,arguments);
        }
        static void ControlsPrefix(Player __instance, ref Vector3 movedir, ref bool attack, ref bool attackHold,
            ref bool secondaryAttack, ref bool secondaryAttackHold, ref bool block, ref bool blockHold,
            ref bool jump, ref bool crouch, ref bool run, ref bool autoRun, ref bool dodge)
        {
            var a = current;
            if (a == null || !a.ownInput || a.releasing || __instance != a.controlled) return;
            bool wantedBlock = false, sprint = false;
            string pulse = null;
            Vector3 movement = Vector3.zero;
            try
            {
                if (movedir.sqrMagnitude > 0.001f || attack || attackHold || secondaryAttack || secondaryAttackHold || blockHold || jump || crouch || run || autoRun || dodge)
                    a.engine.Stop("physical control takeover");
                if (!a.engine.Paused && a.Ready)
                {
                    long now = MainThreadDispatcher.Now;
                    if (now < a.held.Deadline)
                    {
                        movement = Vector3.ClampMagnitude(new Vector3(a.held.Strafe, 0, a.held.Forward), 1f);
                        sprint = a.held.Sprint; wantedBlock = a.held.Block;
                    }
                    if (now < a.edgeDeadline) pulse = a.edge;
                }
            }
            catch (Exception ex) { a.engine.Stop("input hook exception: " + ex.GetType().Name); }
            a.edge = null; __instance.m_autoRun = false;
            movedir = movement; run = sprint; autoRun = dodge = false;
            attack = attackHold = pulse == "primary_attack";
            secondaryAttack = secondaryAttackHold = pulse == "secondary_attack";
            jump = pulse == "jump"; crouch = pulse == "crouch";
            blockHold = wantedBlock;
            block = __instance.ToggleBlock && wantedBlock != (bool)InstalledBindings.Blocking.GetValue(__instance);
        }
        static void LookPrefix(Player __instance, Vector2 mouseLook)
        {
            var a = current;
            if (a != null && a.ownInput && !a.injectingLook && __instance == a.controlled && mouseLook.sqrMagnitude > 0.01f)
                a.engine.Stop("physical camera takeover");
        }
        static void ChatDelivered(Terminal __instance, PlatformUserID user, string text, Talker.Type type)
        {
            var a = current;
            if (a == null || __instance != Chat.instance || type == Talker.Type.Ping || !user.IsValid) return;
            try
            {
                if (!ZNet.TryGetPlayerByPlatformUserID(user, out var info)) return;
                if (type == Talker.Type.Shout) text = text.ToUpper();
                else if (type == Talker.Type.Whisper) text = text.ToLowerInvariant();
                string name = CensorShittyWords.FilterUGC(info.m_name, UGCType.CharacterName, user, 0L);
                // UserInfo and routed IDs are sender-supplied payloads in this build.
                // A server-roster match does not authenticate an individual relayed RPC.
                if (a.messages.Count < 500)
                    a.messages.Enqueue((a.WorldId, name, user.ToString(), type.ToString().ToLowerInvariant(), text, DateTime.UtcNow.ToString("O")));
            }
            catch (Exception ex) { a.log("chat capture exception: " + ex.GetType().Name); }
        }
        public void DrainChat()
        {
            while (messages.TryDequeue(out var message))
                if (message.World == WorldId)
                    engine.ReceiveChat(message.Name, message.Id, false, message.Channel, message.Text, message.Time);
        }
        public void Dispose() { inventory.Cancel(); map.Cancel(); Release(); harmony.UnpatchSelf(); if (current == this) current = null; }
    }
}
