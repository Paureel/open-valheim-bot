using System.Collections.Immutable;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text.Json;

if(args.Length==0) { Console.Error.WriteLine("Usage: AssemblyInspector <installed managed DLL> [...]"); return 2; }
var targetNames=new HashSet<string>{"Player","PlayerController","Chat","Talker","Terminal","ZInput","GameCamera","UserInfo","ZNet","ZRoutedRpc","Humanoid","Character","InventoryGui","InventoryGrid","Inventory","Recipe","SplitDialog"};
var report=new List<object>();
foreach(var path in args)
{
    using var stream=File.OpenRead(path);
    using var pe=new PEReader(stream);
    if(!pe.HasMetadata) continue;
    var reader=pe.GetMetadataReader();
    var types=new List<object>();
    foreach(var handle in reader.TypeDefinitions)
    {
        var type=reader.GetTypeDefinition(handle); var name=reader.GetString(type.Name);
        if(!type.GetDeclaringType().IsNil) continue; // e.g. Version.Player is not the Player component
        if(!targetNames.Contains(name)) continue;
        var methods=new List<object>();
        foreach(var mh in type.GetMethods())
        {
            var method=reader.GetMethodDefinition(mh); var sig=method.DecodeSignature(new Names(), (object?)null);
            methods.Add(new {name=reader.GetString(method.Name),attributes=method.Attributes.ToString(),
                returns=sig.ReturnType,parameters=sig.ParameterTypes,
                parameter_names=method.GetParameters().Select(ph=>reader.GetString(reader.GetParameter(ph).Name)).ToArray(),
                il_offset=method.RelativeVirtualAddress,metadata_token=System.Reflection.Metadata.Ecma335.MetadataTokens.GetToken(mh)});
        }
        var fields=type.GetFields().Select(fh=>reader.GetFieldDefinition(fh)).Select(f=>new {
            name=reader.GetString(f.Name), type=f.DecodeSignature(new Names(), (object?)null), attributes=f.Attributes.ToString()}).ToArray();
        types.Add(new {name,methods,fields});
    }
    stream.Position=0;
    report.Add(new {path=Path.GetFullPath(path),sha256=Convert.ToHexStringLower(SHA256.HashData(stream)),
        mvid=reader.GetGuid(reader.GetModuleDefinition().Mvid),types});
}
Console.WriteLine(JsonSerializer.Serialize(new{verified=false,assemblies=report},new JsonSerializerOptions{WriteIndented=true}));
return 0;

sealed class Names : ISignatureTypeProvider<string,object?>
{
    public string GetArrayType(string e,ArrayShape s)=>e+"["+new string(',',s.Rank-1)+"]";
    public string GetByReferenceType(string e)=>"ref "+e;
    public string GetFunctionPointerType(MethodSignature<string> s)=>"delegate*";
    public string GetGenericInstantiation(string g,ImmutableArray<string> a)=>g+"<"+string.Join(",",a)+">";
    public string GetGenericMethodParameter(object? c,int i)=>"!!"+i;
    public string GetGenericTypeParameter(object? c,int i)=>"!"+i;
    public string GetModifiedType(string m,string u,bool r)=>u;
    public string GetPinnedType(string e)=>e+" pinned";
    public string GetPointerType(string e)=>e+"*";
    public string GetPrimitiveType(PrimitiveTypeCode c)=>c.ToString();
    public string GetSZArrayType(string e)=>e+"[]";
    public string GetTypeFromDefinition(MetadataReader r,TypeDefinitionHandle h,byte k)=>r.GetString(r.GetTypeDefinition(h).Name);
    public string GetTypeFromReference(MetadataReader r,TypeReferenceHandle h,byte k)=>r.GetString(r.GetTypeReference(h).Name);
    public string GetTypeFromSpecification(MetadataReader r,object? c,TypeSpecificationHandle h,byte k)=>r.GetTypeSpecification(h).DecodeSignature(this,c);
}
