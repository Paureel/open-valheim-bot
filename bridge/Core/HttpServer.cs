using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;

namespace ValheimCodexBridge
{
    // MCP/HTTP transport adapted from ValheimMCP. No console routes exist here.
    public sealed class HttpServer : IDisposable
    {
        readonly HttpListener listener = new HttpListener();
        readonly SemaphoreSlim clients = new SemaphoreSlim(16);
        readonly BridgeEngine engine;
        readonly string token;
        readonly Action<string> log;
        readonly int port;
        volatile bool running;
        public HttpServer(BridgeEngine engine, int port, string token, Action<string> log)
        {
            if (token == null || token.Length < 32) throw new ArgumentException("Token required");
            if (port < 1024 || port > 65535) throw new ArgumentException("Invalid port");
            this.engine=engine; this.port=port; this.token=token; this.log=log;
            listener.Prefixes.Add("http://127.0.0.1:" + port + "/");
        }
        public void Start()
        {
            listener.Start(); running=true;
            new Thread(Loop) { IsBackground=true, Name="ValheimCodexBridge-http" }.Start();
            log("MCP listening on 127.0.0.1:" + port);
        }
        void Loop()
        {
            while(running)
            {
                HttpListenerContext ctx;
                try { ctx=listener.GetContext(); } catch { if(!running) return; continue; }
                if(!clients.Wait(0)) { Write(ctx,503,Json.Obj("error","busy")); continue; }
                ThreadPool.QueueUserWorkItem(_ => { try { Handle(ctx); }
                    catch(Exception ex) { log("HTTP failure: " + ex.GetType().Name); try { Write(ctx,500,Json.Obj("error","request failed")); } catch {} }
                    finally { clients.Release(); } });
            }
        }
        void Handle(HttpListenerContext ctx)
        {
            var req=ctx.Request;
            if(req.RemoteEndPoint.Address.ToString() != "127.0.0.1" || req.Headers["Host"] != "127.0.0.1:"+port || req.Headers["Origin"] != null)
            { Write(ctx,403,Json.Obj("error","local non-browser clients only")); return; }
            if(!Same(req.Headers["Authorization"],"Bearer "+token)) { Write(ctx,401,Json.Obj("error","unauthorized")); return; }
            if(req.Url.AbsolutePath=="/health" && req.HttpMethod=="GET") { Write(ctx,200,MiniJson.Parse(engine.Health)); return; }
            if(req.HttpMethod!="POST") { Write(ctx,405,Json.Obj("error","POST required")); return; }
            if(req.Url.AbsolutePath=="/control/stop") { engine.Stop("local operator"); Write(ctx,200,Json.Obj("ok",true)); return; }
            if(req.Url.AbsolutePath=="/control/resume") { engine.ResumeLocal(); Write(ctx,200,Json.Obj("ok",true)); return; }
            if(req.Url.AbsolutePath=="/control/travel-heartbeat") { Write(ctx,200,engine.RenewTravel()); return; }
            if(req.Url.AbsolutePath!="/mcp") { Write(ctx,404,Json.Obj("error","unknown route")); return; }
            if(req.ContentLength64<0 || req.ContentLength64>65536) { Write(ctx,413,Json.Obj("error","body too large")); return; }
            if(!(req.ContentType??"").StartsWith("application/json",StringComparison.OrdinalIgnoreCase)) { Write(ctx,415,Json.Obj("error","JSON required")); return; }
            object id=null;
            try
            {
                string body;
                using(var sr=new StreamReader(req.InputStream,Encoding.UTF8)) body=sr.ReadToEnd();
                var r=MiniJson.Parse(body) as Dictionary<string,object>;
                if(r==null || !r.ContainsKey("jsonrpc") || (string)r["jsonrpc"]!="2.0" || !r.ContainsKey("method")) throw new ArgumentException("Invalid request");
                r.TryGetValue("id",out id); string method=(string)r["method"];
                if(!r.ContainsKey("id")) { Write(ctx,202,null); return; }
                var p=r.ContainsKey("params") ? (Dictionary<string,object>)r["params"] : Json.Obj();
                object result;
                switch(method)
                {
                    case "initialize": result=Json.Obj("protocolVersion", "2025-03-26", "capabilities",Json.Obj("tools",Json.Obj()),"serverInfo",Json.Obj("name","ValheimCodexBridge","version","0.1.0")); break;
                    case "ping": result=Json.Obj(); break;
                    case "tools/list": result=Json.Obj("tools",engine.Tools); break;
                    case "tools/call":
                        try
                        {
                            var value=engine.Call((string)p["name"],p.ContainsKey("arguments")?(Dictionary<string,object>)p["arguments"]:Json.Obj());
                            var content=value is ImageResult img ? Json.Obj("type","image","mimeType","image/png","data",Convert.ToBase64String(img.Png)) : Json.Obj("type","text","text",Json.Write(value));
                            result=Json.Obj("content",value is ImageResult frame && frame.Metadata!=null ?
                                new[]{content,Json.Obj("type","text","text",Json.Write(frame.Metadata))} : new[]{content},"isError",false);
                        }
                        catch(Exception ex) { var e=ex is AggregateException ? ex.GetBaseException() : ex;
                            log("tool failed: "+ e.GetType().Name);
                            result=Json.Obj("content",new[]{Json.Obj("type","text","text",e.Message)},"isError",true); }
                        break;
                    default: Write(ctx,200,Json.Obj("jsonrpc","2.0","id",id,"error",Json.Obj("code",-32601,"message","Unknown method"))); return;
                }
                Write(ctx,200,Json.Obj("jsonrpc","2.0","id",id,"result",result));
            }
            catch(Exception) { Write(ctx,200,Json.Obj("jsonrpc","2.0","id",id,"error",Json.Obj("code",-32600,"message","Invalid JSON-RPC request"))); }
        }
        static bool Same(string a,string b) { if(a==null || a.Length!=b.Length)return false; int d=0;for(int i=0;i<a.Length;i++)d|=a[i]^b[i];return d==0; }
        static void Write(HttpListenerContext ctx,int status,object value)
        {
            byte[] data=value==null?Array.Empty<byte>():Encoding.UTF8.GetBytes(Json.Write(value));
            ctx.Response.StatusCode=status;ctx.Response.ContentType="application/json";ctx.Response.Headers["Cache-Control"]="no-store";
            ctx.Response.ContentLength64=data.Length;ctx.Response.OutputStream.Write(data,0,data.Length);ctx.Response.Close();
        }
        public void Dispose() { engine.Stop("server shutdown"); running=false;listener.Close(); }
    }
}
