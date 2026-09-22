using ValheimCodexBridge;

var sim = new Simulation();
var settings = new BridgeSettings {ExpectedWorld="simulation",ExpectedCharacter="Codex",MaxActionMs=1500};
settings.Owners.Add("simulation-owner-id");
var log=new List<string>();
var engine=new BridgeEngine(sim,settings,s=>{lock(log)log.Add(s);});
engine.Tick();
if(args.Contains("--serve"))
{
    string Arg(string name) => args[Array.IndexOf(args,name)+1];
    int port=int.Parse(Arg("--port"));
    using var server=new HttpServer(engine,port,File.ReadAllText(Arg("--token-file")).Trim(),_=>{});
    engine.ReceiveChat("Test player","simulation-owner-id",true,"normal","Codex, turn around.");
    server.Start(); Console.WriteLine("SIMULATION ONLY: listening on 127.0.0.1:"+port);Console.Out.Flush();
    bool running=true;Console.CancelKeyPress+=(_,e)=>{e.Cancel=true;running=false;};
    while(running) {engine.Tick();Thread.Sleep(10);}
    return 0;
}
int passed=0;
void Check(bool value,string message) { if(!value)throw new Exception(message);passed++;Console.WriteLine("PASS "+message); }
object Call(string name,Dictionary<string,object> a=null)
{
    var task=Task.Run(()=>engine.Call(name,a??Json.Obj()));
    while(!task.IsCompleted) {engine.Tick();Thread.Sleep(1);}
    return task.GetAwaiter().GetResult();
}
bool Reject(Action action) {try{action();return false;}catch{return true;}}
Check(Reject(()=>Call("move",Json.Obj("forward",1,"strafe",0,"duration_ms",50))),"startup paused");
engine.ResumeLocal();engine.Tick();
Call("move",Json.Obj("forward",1,"strafe",0,"duration_ms",50,"sprint",true));engine.Tick();
Check(sim.Held,"lease applies input");Thread.Sleep(80);engine.Tick();Check(!sim.Held,"watchdog expires all held input without heartbeat");
Call("move",Json.Obj("forward",1,"strafe",0,"duration_ms",40));
Check(sim.Deadline>MainThreadDispatcher.Now,"physics adapter receives monotonic deadline");
Thread.Sleep(60);Check(MainThreadDispatcher.Now>=sim.Deadline,"physics deadline expires even without an engine tick");
engine.Tick();Check(sim.Deadline==0,"released state clears physics deadline");
Check(Reject(()=>Call("move",Json.Obj("forward",double.NaN,"strafe",0,"duration_ms",100))),"NaN rejected");
Check(Reject(()=>Call("move",Json.Obj("forward",1,"strafe",0,"duration_ms",5000))),"oversized duration rejected");
Check(Reject(()=>Call("move",Json.Obj("forward",true,"strafe",0,"duration_ms",50))),"boolean numeric coercion rejected");
Check(Reject(()=>Call("run_command",Json.Obj("text","god"))),"console execution not exposed");
var motorArgs=Json.Obj("forward",1,"strafe",0,"yaw_rate",30,"pitch_rate",0,"sprint",false,"block",false,"button","none","duration_ms",800,"frame_id",1);
Call("motor",motorArgs);engine.Tick();Check(sim.Held,"fresh local motor acquires continuous input");
sim.SawRelease=false;
Call("motor",motorArgs);engine.Tick();Check(!sim.SawRelease,"renewing motor does not insert a released-input frame");
Thread.Sleep(850);engine.Tick();Check(!sim.Held,"dead local worker loses its motor lease within 900ms");
sim.MotorSafe=false;
Check(!(bool)((Dictionary<string,object>)Call("motor",motorArgs))["ok"] && !sim.Held,"stale motor frame cannot acquire input");
sim.MotorSafe=true;motorArgs["button"]="primary_attack";
Check(Reject(()=>Call("motor",motorArgs)),"motor cannot bypass combat gate");
motorArgs["button"]="none";motorArgs["duration_ms"]=901;
Check(Reject(()=>Call("motor",motorArgs)),"motor lease cannot exceed 900ms");
motorArgs["duration_ms"]=800;
engine.Stop("motor stop race");engine.Tick();
Check(Reject(()=>Call("motor",motorArgs)) && !sim.Held,"late motor result cannot override stop");
engine.ResumeLocal();engine.Tick();
Check((bool)((Dictionary<string,object>)Call("stride",Json.Obj("heading",30,"distance",16,"frame_id",1,"sprint",false)))["ok"],"stride reaches the normal local travel adapter");
Check(Reject(()=>Call("stride",Json.Obj("heading",0,"distance",100,"frame_id",1,"sprint",false))),"stride cannot exceed its visible corridor bound");
Check(Reject(()=>Call("stride",Json.Obj("heading",0,"distance",12,"frame_id",0,"sprint",false))),"stride requires an exact captured image");
Check(Reject(()=>Call("primary_attack")),"combat gate enforced");
Call("aim_at",Json.Obj("x",.3,"y",.7));
Check(Reject(()=>Call("aim_at",Json.Obj("x",1.1,"y",.5))),"image aiming rejects out-of-frame coordinates");
var reflex=new DamageReflex(); long now=MainThreadDispatcher.Now;
Check(!reflex.Step(25,50,true,now),"damage reflex does not trigger on first health reading");
Check(reflex.Step(20,50,true,now),"damage reflex briefly blocks after own health drops");
Check(!reflex.Step(20,50,true,now+MainThreadDispatcher.Ms(1100)),"damage reflex expires without model input");
Check(!reflex.Step(15,50,false,now),"damage reflex cannot bypass pause or disabled combat");
Check(!reflex.Step(10,4,true,now),"damage reflex preserves last stamina");
Check(reflex.Step(9,50,true,now)&&!reflex.Step(9,50,false,now),"stop cancels an active damage reflex");
var fedReflex=new DamageReflex();fedReflex.Step(40,50,true,now,40);
Check(!fedReflex.Step(39,50,true,now,39),"food health-cap decay does not trigger damage reflex");
TravelIntent Route(int budget=10000) {var t=new TravelIntent();t.Start(0,0,0,0,18,25,false,budget,now);return t;}
var route=Route();
for(int ms=200;ms<=6000;ms+=200) {var tick=now+MainThreadDispatcher.Ms(ms);route.Renew(tick);route.Step(0,ms/500.0,0,25,25,true,false,false,tick);}
Check(route.Active && route.Travelled>11,"travel continues smoothly across 30 short renewals while planning");
Check(!route.Step(0,12,0,25,25,true,false,false,now+MainThreadDispatcher.Ms(7000)),"lost travel heartbeat releases within 900ms");
route.Renew(now+MainThreadDispatcher.Ms(7100));Check(!route.Active,"late heartbeat cannot restart expired travel");
route=Route();
for(int ms=200;ms<=1200;ms+=200) {var tick=now+MainThreadDispatcher.Ms(ms);route.Renew(tick);route.Step(0,0,0,25,25,true,false,false,tick);}
Check(!route.Active && route.Reason=="blocked","travel stops pushing a blocked route");
route=Route();Check(!route.Step(0,1,0,24,25,true,false,false,now),"damage interrupts purposeful travel");
route=Route();Check(!route.Step(0,1,0,25,25,true,true,false,now),"water entry interrupts travel");
route=Route();Check(!route.Step(0,1,0,25,25,true,false,true,now),"encumbrance interrupts travel");
route=Route();Check(!route.Step(0,1,-2,25,25,true,false,false,now),"fall interrupts travel");
route=Route();Check(!route.Step(0,17,0,25,25,true,false,false,now) && route.Reason=="arrived","destination arrival is a deliberate stop");
route=Route();Check(!route.Step(0,1,0,25,25,false,false,false,now),"menu or focus loss cancels travel");
route=Route(1000);
for(int ms=200;ms<=1000;ms+=200) {var tick=now+MainThreadDispatcher.Ms(ms);route.Renew(tick);route.Step(0,ms/500.0,0,25,25,true,false,false,tick);}
Check(!route.Active,"heartbeats cannot extend the chosen travel budget");
route=Route();route.Cancel("rest");route.Renew(now);Check(!route.Active,"rest cannot become automatic movement");
route=Route();route.Start(0,0,0,0,18,25,false,1000,now,100);
Check(route.LeaseDeadline==now+MainThreadDispatcher.Ms(100),"travel respects a shorter configured input lease");
Check(Reject(()=>route.Start(0,0,0,0,30,25,false,10000,now)),"distant travel target rejected");
InteractionIntent Interaction(bool walking=true) {var x=new InteractionIntent();x.Start("Wanderer",walking,25,now,900);return x;}
var interactionIntent=Interaction();
Check(interactionIntent.Matches("Tombstone Wanderer\n[E] Open") && !interactionIntent.Matches("Tombstone Other\nWanderer") && !interactionIntent.Matches("Tombstone WandererTwo"),"interaction matches a specific visible caption name, not instruction text or partial names");
Check(!interactionIntent.Confirm(1,"Tombstone Wanderer",now) && interactionIntent.Confirm(1,"Tombstone Wanderer",now+MainThreadDispatcher.Ms(150)),"named crosshair target must remain stable before interaction");
Check(!interactionIntent.Confirm(2,"Tombstone Wanderer",now+MainThreadDispatcher.Ms(160)),"crosshair target change resets interaction confirmation");
interactionIntent.Submitted(Json.Obj("ok",true));interactionIntent.Renew(now);
Check(!interactionIntent.Active && !interactionIntent.Confirm(2,"Tombstone Wanderer",now+MainThreadDispatcher.Ms(400)),"submitted interaction cannot repeat or restart from heartbeats");
interactionIntent=Interaction();interactionIntent.Renew(now+MainThreadDispatcher.Ms(1000));
Check(!interactionIntent.Active,"lost interaction heartbeat cannot be renewed late");
interactionIntent=Interaction(false);
for(int ms=200;ms<=2600;ms+=200) {var tick=now+MainThreadDispatcher.Ms(ms);interactionIntent.Renew(tick);interactionIntent.Step(true,25,25,false,false,tick);}
Check(!interactionIntent.Active && interactionIntent.Reason=="named target not found in reach","bounded local aiming does not search indefinitely");
interactionIntent=Interaction();
for(int ms=200;ms<=8200;ms+=200) {var tick=now+MainThreadDispatcher.Ms(ms);interactionIntent.Renew(tick);interactionIntent.Step(true,25,25,false,false,tick);}
Check(!interactionIntent.Active,"interaction heartbeat cannot extend the eight-second intention");
interactionIntent=Interaction();Check(!interactionIntent.Step(true,24,25,false,false,now),"damage interrupts close interaction");
interactionIntent=Interaction();Check(!interactionIntent.Step(false,25,25,false,false,now),"focus/menu loss interrupts close interaction");
interactionIntent=Interaction();Check(!interactionIntent.Step(true,25,25,true,false,now),"water interrupts close interaction");
interactionIntent=Interaction();interactionIntent.Cancel("manual stop");interactionIntent.Renew(now);Check(!interactionIntent.Active,"manual stop cannot be cleared by close-interaction heartbeat");
Check(Reject(()=>new InteractionIntent().Start("Open",true,25,now,900)),"generic interaction instruction is not a target name");
Call("move",Json.Obj("forward",1,"strafe",0,"duration_ms",1000));engine.Tick();
engine.ReceiveChat("Owner","impostor-id",true,"normal","!codex stop");Check(!engine.Paused,"display-name impersonation has no privilege");
engine.ReceiveChat("Owner","simulation-owner-id",false,"normal","!codex stop");Check(!engine.Paused,"unverified identity has no privilege");
engine.ReceiveChat("Owner","simulation-owner-id",true,"normal","!codex stop");engine.Tick();Check(engine.Paused&&!sim.Held,"verified owner stop releases and latches");
Check(Reject(()=>Call("look",Json.Obj("delta_yaw",180,"delta_pitch",0))),"actions cannot clear stop latch");
engine.ResumeLocal();Call("send_chat",Json.Obj("text","hello","type","normal"));
Check(sim.Sent=="hello","adapter send path invoked");
Check(Reject(()=>Call("send_chat",Json.Obj("text","hello again"))),"chat cooldown enforced");
Call("move",Json.Obj("forward",1,"strafe",0,"duration_ms",1000));
Call("open_inventory"); engine.Tick();
Check(sim.InventoryOpen && !sim.Held,"opening inventory releases movement");
Check(!(bool)((Dictionary<string,object>)Call("move",Json.Obj("forward",1,"strafe",0,"duration_ms",100)))["ok"],"movement is rejected while inventory is open");
settings.CombatEnabled=true;
Check(!(bool)((Dictionary<string,object>)Call("primary_attack"))["ok"],"enabled combat is rejected while inventory is open");
Call("close_inventory"); Call("move",Json.Obj("forward",1,"strafe",0,"duration_ms",100)); engine.Tick();
Check(sim.Held,"closing inventory restores gameplay controls");
sim.PrecisionSafe=false;
Check(!(bool)((Dictionary<string,object>)Call("primary_attack",Json.Obj("frame_id",123)))["ok"] && sim.PrecisionFrame==123,"precise actions validate the exact delivered frame");
engine.Tick();Check(!sim.Held,"stale precise action releases previous movement");
sim.PrecisionSafe=true;
Check((bool)((Dictionary<string,object>)Call("interact",Json.Obj("frame_id",124)))["ok"],"fresh precise action is allowed");
engine.Stop("test");engine.Tick();
Check(Call("get_inventory")!=null,"inventory inspection is read-only during pause");
Check(Reject(()=>Call("open_inventory")),"inventory mutations cannot clear pause");
engine.ResumeLocal();engine.Tick();
var dispatcher=new MainThreadDispatcher();int calls=0;
Call("move",Json.Obj("forward",1,"strafe",0,"duration_ms",1000));Call("open_map");engine.Tick();
Check(sim.MapOpen&&!sim.Held,"opening map releases movement");
Check(!(bool)((Dictionary<string,object>)Call("look",Json.Obj("delta_yaw",5,"delta_pitch",0)))["ok"],"map prevents gameplay look");
Call("map_zoom",Json.Obj("steps",2));Call("close_map");Call("move",Json.Obj("forward",1,"strafe",0,"duration_ms",100));engine.Tick();
Check(sim.Held,"closing map restores gameplay input");
engine.Stop("map safety test");engine.Tick();Check(Reject(()=>Call("open_map")),"map actions cannot clear pause");
engine.ResumeLocal();engine.Tick();
var stale=Task.Run(()=>{try{dispatcher.Invoke(()=>{calls++;return null;},30);}catch{}});stale.Wait();dispatcher.Pump();
Check(calls==0,"timed-out queued work never executes later");
var queued=Task.Run(()=>{try{dispatcher.Invoke(()=>{calls++;return null;},500);}catch{}});Thread.Sleep(30);dispatcher.CancelPending();dispatcher.Pump();queued.Wait();
Check(calls==0,"stop cancels queued work");
Check(Reject(()=>MiniJson.Parse("{\"a\":1,\"a\":2}")),"duplicate JSON keys rejected");
Check(Reject(()=>MiniJson.Parse("{}garbage")),"trailing JSON rejected");
Check(Reject(()=>MiniJson.Parse(new string('[',30)+new string(']',30))),"deep JSON rejected");
var picture=Call("observe_player_view");Check(picture is ImageResult,"image content contract works");
sim.Ready=false;engine.Tick();Check(engine.Paused,"loss of local player latches pause");
Check(Call("get_status")!=null,"own status remains readable while control is unavailable");
int before=((object[])((Dictionary<string,object>)Call("get_chat"))["events"]).Length;
sim.WorldId="another-world";engine.ReceiveChat("Other player","other-id",false,"normal","Different world dialogue");
sim.WorldId="simulation";
Check(((object[])((Dictionary<string,object>)Call("get_chat"))["events"]).Length==before,"other-world chat is excluded from configured-world memory");
Console.WriteLine($"{passed} core safety checks passed. Simulation does not verify Valheim APIs.");
return 0;

sealed class Simulation : IGameAdapter
{
    public bool Ready {get;set;}=true;
    public bool InventoryOpen;
    public bool MapOpen;
    public bool GameplayReady => Ready && !InventoryOpen && !MapOpen;
    public bool HasHeldInput => Held && Deadline>MainThreadDispatcher.Now;
    public object MapAction(string action, Dictionary<string,object> args) {if(action=="open_map")MapOpen=true;if(action=="close_map")MapOpen=false;return Json.Obj("ok",true);}
    public object InventoryAction(string action, Dictionary<string,object> args) { if(action=="open_inventory") InventoryOpen=true; if(action=="close_inventory") InventoryOpen=false; return Json.Obj("ok",true); }
    public string Reason=>"SIMULATION, not Valheim";
    public string WorldId {get;set;}="simulation";
    public string CharacterName=>"Codex";
    public int ChatLimit=>160;
    public bool Held;
    public bool SawRelease;
    public long Deadline;
    public string Sent;
    public object Status()=>Json.Obj("health",100,"stamina",100,"dead",false,"simulation",true);
    int imageSequence;
    public ImageResult Observe()=>new ImageResult(Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII="),Json.Obj("frame_id",++imageSequence,"age_ms",0,"camera_yaw",0));
    public void Apply(ControlState state) {if(Held && !state.Held)SawRelease=true;Held=state.Held;Deadline=state.Deadline;}
    public void Look(float yaw,float pitch){}
    public object Pulse(string action,int slot)=>Json.Obj("ok",true);
    public void Aim(float x,float y,bool ground,int frameId){}
    public object TravelAction(string action,Dictionary<string,object> args)=>Json.Obj("ok",true);
    public void RenewTravel(){}
    public void CancelTravel(string reason){}
    public bool PrecisionSafe=true;
    public bool MotorSafe=true;
    public bool MotorReady(int frameId) => MotorSafe && frameId>0;
    public int PrecisionFrame;
    public bool PrecisionReady(int frameId) {PrecisionFrame=frameId;return PrecisionSafe;}
    public void SendChat(string text,string channel)=>Sent=text;
}
