using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
namespace ValheimCodexBridge
{
    internal static class AssemblyProbe
    {
        public static void Write(string path)
        {
            var names = new HashSet<string>{"Player","PlayerController","Chat","Talker","ZInput","GameCamera","UserInfo","ZNet","ZRoutedRpc","Humanoid","Character"};
            var report=new List<object>();
            foreach(var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                foreach(var name in names)
                {
                    var type=asm.GetType(name,false);
                    if(type==null) continue;
                    var methods=new List<object>();
                    foreach(var method in type.GetMethods(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.Static|BindingFlags.DeclaredOnly))
                        methods.Add(method.ToString());
                    string hash=null;
                    if(File.Exists(asm.Location)) using(var sha=SHA256.Create()) using(var stream=File.OpenRead(asm.Location)) hash=BitConverter.ToString(sha.ComputeHash(stream)).Replace("-","").ToLowerInvariant();
                    report.Add(Json.Obj("type",name,"assembly",asm.FullName,"path",asm.Location,"sha256",hash,"methods",methods));
                }
            }
            File.WriteAllText(path,Json.Write(Json.Obj("verified",false,"captured_at",DateTime.UtcNow.ToString("O"),"assemblies",report)));
        }
    }
}
