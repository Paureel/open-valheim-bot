using System;
using System.Collections.Generic;
using UnityEngine;

namespace ValheimCodexBridge
{
    // The normal player's explored map only. No pin/terrain data is exported.
    internal sealed class MapController
    {
        Player owner;
        long world;
        bool closing;
        public bool Owned => owner != null;
        public object Snapshot() => Json.Obj("open", Owned && !closing);
        public void Tick(BridgeEngine engine)
        {
            if (!Owned) return;
            if (engine.Paused || !Application.isFocused || owner != Player.m_localPlayer || owner.IsDead() || ZNet.World == null || ZNet.World.m_uid != world)
            { Cancel(); return; }
            if (ZInput.GetMouseButton(0) || ZInput.GetMouseButton(1) || ZInput.GetKeyDown(KeyCode.Escape) ||
                ZInput.GetButtonDown("Map") || ZInput.GetButtonDown("JoyMap") || ZInput.GetButtonDown("JoyButtonB") || ZInput.GetMouseScrollWheel()!=0)
            { owner=null; engine.Stop("physical map takeover"); return; }
            if (!Minimap.IsOpen())
            {
                bool expected=closing; owner=null; closing=false;
                if (!expected) engine.Stop("map closed outside bridge");
            }
        }
        public void Cancel()
        {
            if (Owned && Minimap.instance) Minimap.instance.SetMapMode(Minimap.MapMode.Small);
            owner=null; closing=false;
        }
        public object Call(string action, Dictionary<string,object> args)
        {
            if (!Minimap.instance || Game.m_noMap) return Json.Obj("ok",false,"error","Map unavailable under the current world rules");
            if (action=="open_map")
            {
                if (!Owned && Minimap.IsOpen()) return Json.Obj("ok",false,"error","Manual map remains under human control");
                owner=Player.m_localPlayer; world=ZNet.World.m_uid; closing=false;
                Minimap.instance.SetMapMode(Minimap.MapMode.Large);
            }
            else
            {
                if (!Owned || closing) return Json.Obj("ok",false,"error","Open the map through the bridge first");
                if (action=="close_map") { Minimap.instance.SetMapMode(Minimap.MapMode.Small); closing=true; }
                else if (action=="map_zoom") Minimap.instance.LargeZoom *= Mathf.Pow(.5f,Convert.ToInt32(args["steps"]));
                else throw new ArgumentException("Unknown map action");
            }
            return Json.Obj("ok",true,"map",Snapshot());
        }
    }
}
