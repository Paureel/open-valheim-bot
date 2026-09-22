using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using HarmonyLib;
using UnityEngine;

namespace ValheimCodexBridge
{
    // Reviewed from native Steam Valheim 1.0.15 / build 25390630.
    internal static class InstalledBindings
    {
        public static readonly MethodInfo TakeInput = Required(typeof(Player), "TakeInput", Type.EmptyTypes);
        public static readonly MethodInfo UpdateHover = Required(typeof(Player), "UpdateHover", Type.EmptyTypes);
        public static readonly MethodInfo Interact = Required(typeof(Player), "Interact", new[] { typeof(GameObject), typeof(bool), typeof(bool) });
        public static readonly FieldInfo Blocking = AccessTools.Field(typeof(Character), "m_blocking") ?? throw new MissingFieldException("Character.m_blocking");
        public static MethodInfo Required(Type type, string name, Type[] parameters) =>
            AccessTools.DeclaredMethod(type, name, parameters) ?? throw new MissingMethodException(type.FullName, name);
        public static void Verify()
        {
            using var reader = new StreamReader(typeof(InstalledBindings).Assembly.GetManifestResourceStream("ValheimCodexBridge.reviewed-assemblies.json"));
            var reviewed = (Dictionary<string, object>)MiniJson.Parse(reader.ReadToEnd());
            string directory = Path.GetDirectoryName(typeof(Player).Assembly.Location);
            foreach (var entry in reviewed)
            {
                using var input = File.OpenRead(Path.Combine(directory, entry.Key));
                using var sha = SHA256.Create();
                string actual = BitConverter.ToString(sha.ComputeHash(input)).Replace("-", "").ToLowerInvariant();
                if (actual != (string)entry.Value)
                    throw new InvalidOperationException("Unreviewed game assembly: " + entry.Key + "; inspect updated APIs and rebuild before enabling control");
            }
            InventoryController.Verify();
            if (Blocking.FieldType != typeof(bool)) throw new InvalidOperationException("Blocking field changed");
        }
    }
}
