using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Experimental.Rendering;
using UnityEngine.Rendering;
namespace ValheimCodexBridge
{
    // Real final frame, including the player's camera, post-processing and HUD.
    internal sealed class PlayerViewCapture : MonoBehaviour
    {
        public Func<bool> CanCapture;
        public Action<string> OnFailure;
        public string RecordingRequestPath;
        long recordingCheckAt;
        bool recording;
        byte[] png;
        long captured;
        string world;
        int sequence;
        double captureMs;
        Task<byte[]> pending;
        View pendingView;
        double pendingCaptureMs;
        View view;
        readonly Dictionary<int,View> delivered = new Dictionary<int,View>();
        public View Observed { get; private set; }
        int CaptureIntervalMs()
        {
            long now=MainThreadDispatcher.Now;
            if(now>=recordingCheckAt)
            {
                recordingCheckAt=now+MainThreadDispatcher.Ms(1000);
                recording=false;
                try
                {
                    // A local recording utility may request at most 90 seconds
                    // of faster camera capture. No game controls are granted.
                    long unix=DateTimeOffset.UtcNow.ToUnixTimeSeconds();
                    if(!String.IsNullOrEmpty(RecordingRequestPath) && File.Exists(RecordingRequestPath) &&
                        Int64.TryParse(File.ReadAllText(RecordingRequestPath),out long until))
                        recording=until>unix && until<=unix+90;
                }
                catch(IOException) { }
                catch(UnauthorizedAccessException) { }
            }
            return recording ? 50 : 250;
        }
        internal sealed class View
        {
            public int Id;
            public long Time;
            public string World;
            public Vector3 Body, Forward, Near00,Near10,Near01,Far00,Far10,Far01;
            public Ray Ray(float x,float y) {
                var near=Near00+(Near10-Near00)*x+(Near01-Near00)*(1-y);
                var far=Far00+(Far10-Far00)*x+(Far01-Far00)*(1-y);
                return new Ray(near,(far-near).normalized);
            }
            public bool Ground(float x,float y,out Vector3 point) {
                var ray=Ray(x,y);var plane=new Plane(Vector3.up,Body+Vector3.up*.25f);
                point=Vector3.zero;
                if(!plane.Raycast(ray,out float distance) || distance<=0 || distance>35)return false;
                point=ray.GetPoint(distance);return true;
            }
            public object[] RangeGuide()
            {
                var rows=new List<object>();
                foreach(float y in new[]{.3f,.4f,.45f,.5f,.55f,.6f,.65f,.7f,.8f})
                    if(Ground(.5f,y,out var point))
                    {
                        var delta=point-Body;delta.y=0;
                        var forward=Forward;forward.y=0;
                        // Omit points behind our feet; these are geometry guides,
                        // never a claim that ground is clear, reachable or flat.
                        if(Vector3.Dot(delta,forward)>0)
                            rows.Add(Json.Obj("x",.5,"y",y,"estimated_distance_m",Math.Round(delta.magnitude,1)));
                    }
                return rows.ToArray();
            }
        }
        public View GetView(int id=0)
        {
            var selected=id==0 ? Observed : delivered.TryGetValue(id,out var value) ? value : null;
            if(selected==null || MainThreadDispatcher.Now-selected.Time>MainThreadDispatcher.Ms(20000) ||
                ZNet.World==null || selected.World!="world:"+ZNet.World.m_uid)
                throw new InvalidOperationException("Observed image expired; get a new view");
            return selected;
        }
        public double AgeMs => captured == 0 ? -1 : (MainThreadDispatcher.Now - captured) * 1000.0 / System.Diagnostics.Stopwatch.Frequency;
        public ImageResult Latest()
        {
            if (png == null || AgeMs > 1500 || ZNet.World == null || world != "world:" + ZNet.World.m_uid)
                throw new InvalidOperationException("Fresh player frame unavailable; wait for a focused game frame");
            Observed=view;
            delivered[view.Id]=view;
            foreach(var id in new List<int>(delivered.Keys))
                if(captured-delivered[id].Time>MainThreadDispatcher.Ms(20000))delivered.Remove(id);
            return new ImageResult(png,Json.Obj("frame_id",view.Id,"age_ms",AgeMs,
                "capture_ms",captureMs,"screen_width",Screen.width,"screen_height",Screen.height,
                "readback_mode",SystemInfo.supportsAsyncGPUReadback ? "async" : "blocking",
                "camera_yaw",Mathf.Atan2(view.Forward.x,view.Forward.z)*Mathf.Rad2Deg,
                "flat_ground_range_guide",view.RangeGuide(),"range_guide_note","Own camera/flat-plane geometry only. Inspect the image for actual terrain, hazards and obstacles."));
        }
        IEnumerator Start()
        {
            var endOfFrame = new WaitForEndOfFrame();
            while (true)
            {
                yield return endOfFrame;
                try
                {
                    if (CanCapture == null || !CanCapture()) { png = null; captured = 0; pendingView=null; continue; }
                    if(pending!=null)
                    {
                        if(!pending.IsCompleted)continue;
                        var encoded=pending.GetAwaiter().GetResult(); pending=null;
                        if(pendingView!=null && ZNet.World!=null && pendingView.World=="world:"+ZNet.World.m_uid)
                        {
                            png=encoded; view=pendingView; captured=view.Time; world=view.World;
                            captureMs=pendingCaptureMs;
                        }
                        pendingView=null;
                    }
                    if (png != null && AgeMs < CaptureIntervalMs()) continue;
                    var camera = GameCamera.instance.GetComponent<Camera>();
                    if (!camera || !camera.isActiveAndEnabled || GameCamera.InFreeFly()) { png = null; captured = 0; continue; }
                    long captureStart=MainThreadDispatcher.Now;
                    pending=CaptureFrame();
                    pendingCaptureMs=(MainThreadDispatcher.Now-captureStart)*1000.0/System.Diagnostics.Stopwatch.Frequency;
                    pendingView=new View {Id=++sequence,Time=captureStart,World="world:"+ZNet.World.m_uid,Body=Player.m_localPlayer.transform.position,
                        Forward=camera.transform.forward,
                        Near00=camera.ViewportToWorldPoint(new Vector3(0,0,camera.nearClipPlane)),
                        Near10=camera.ViewportToWorldPoint(new Vector3(1,0,camera.nearClipPlane)),
                        Near01=camera.ViewportToWorldPoint(new Vector3(0,1,camera.nearClipPlane)),
                        Far00=camera.ViewportToWorldPoint(new Vector3(0,0,30)),
                        Far10=camera.ViewportToWorldPoint(new Vector3(1,0,30)),
                        Far01=camera.ViewportToWorldPoint(new Vector3(0,1,30))};
                }
                catch (Exception ex)
                {
                    png = null; captured = 0;
                    OnFailure?.Invoke("frame capture failed: " + ex.GetType().Name);
                    enabled = false;
                    yield break;
                }
            }
        }
        static Task<byte[]> CaptureFrame()
        {
            if(!SystemInfo.supportsAsyncGPUReadback)
            {
                var raw=CaptureFrameBlocking(out int w,out int h,out GraphicsFormat f);
                return Task.Run(()=>ImageConversion.EncodeArrayToPNG(raw,f,(uint)w,(uint)h));
            }
            int width=Math.Min(960,Screen.width);
            int height=Math.Max(1,Mathf.RoundToInt(width*(float)Screen.height/Screen.width));
            var full=RenderTexture.GetTemporary(Screen.width,Screen.height,0,RenderTextureFormat.ARGB32);
            var target=RenderTexture.GetTemporary(width,height,0,RenderTextureFormat.ARGB32);
            var completion=new TaskCompletionSource<byte[]>();
            try
            {
                ScreenCapture.CaptureScreenshotIntoRenderTexture(full);
                if(SystemInfo.graphicsUVStartsAtTop)
                    Graphics.Blit(full,target,new Vector2(1,-1),new Vector2(0,1));
                else Graphics.Blit(full,target);
                // Keep both textures alive until the GPU has finished copying.
                // Never block the rendering thread waiting for MLX/GPU work.
                AsyncGPUReadback.Request(target,0,TextureFormat.RGBA32,request=>
                {
                    try
                    {
                        if(request.hasError)throw new InvalidOperationException("GPU readback failed");
                        var raw=request.GetData<byte>().ToArray();
                        // Only the copied pixels cross onto the encoder thread.
                        Task.Run(()=>ImageConversion.EncodeArrayToPNG(raw,GraphicsFormat.R8G8B8A8_UNorm,(uint)width,(uint)height))
                            .ContinueWith(encoded=>
                            {
                                if(encoded.IsFaulted)completion.TrySetException(encoded.Exception);
                                else completion.TrySetResult(encoded.Result);
                            });
                    }
                    catch(Exception ex){completion.TrySetException(ex);}
                    finally
                    {
                        RenderTexture.ReleaseTemporary(target);
                        RenderTexture.ReleaseTemporary(full);
                    }
                });
            }
            catch
            {
                RenderTexture.ReleaseTemporary(target);
                RenderTexture.ReleaseTemporary(full);
                throw;
            }
            return completion.Task;
        }
        static byte[] CaptureFrameBlocking(out int width,out int height,out GraphicsFormat format)
        {
            width = Math.Min(960, Screen.width);
            height = Math.Max(1, Mathf.RoundToInt(width * (float)Screen.height / Screen.width));
            Texture2D pixels = null;
            RenderTexture full = null, target = null;
            var previous = RenderTexture.active;
            try
            {
                // Keep the full-resolution framebuffer on the GPU. The old
                // path read it to CPU, uploaded it again, then downscaled it.
                // Read back only the small final player-view image.
                full = RenderTexture.GetTemporary(Screen.width,Screen.height,0,RenderTextureFormat.ARGB32);
                ScreenCapture.CaptureScreenshotIntoRenderTexture(full);
                target = RenderTexture.GetTemporary(width, height, 0, RenderTextureFormat.ARGB32);
                if(SystemInfo.graphicsUVStartsAtTop)
                    Graphics.Blit(full,target,new Vector2(1,-1),new Vector2(0,1));
                else Graphics.Blit(full,target);
                RenderTexture.active = target;
                pixels = new Texture2D(width, height, TextureFormat.RGB24, false);
                pixels.ReadPixels(new Rect(0, 0, width, height), 0, 0, false);
                format=pixels.graphicsFormat;
                return pixels.GetRawTextureData();
            }
            finally
            {
                RenderTexture.active = previous;
                if (target != null) RenderTexture.ReleaseTemporary(target);
                if (pixels != null) Destroy(pixels);
                if (full != null) RenderTexture.ReleaseTemporary(full);
            }
        }
    }
}
