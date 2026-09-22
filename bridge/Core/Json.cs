using System;
using System.Collections;
using System.Globalization;
using System.Text;

namespace ValheimCodexBridge
{
    // Writer adapted from myrcutio/ValheimMCP (MIT; see vendor/ValheimMCP/LICENSE).
    public static class Json
    {
        public static string Write(object value)
        {
            if (value == null) return "null";
            if (value is string s) return Str(s);
            if (value is bool b) return b ? "true" : "false";
            if (value is IDictionary dict)
            {
                var parts = new System.Collections.Generic.List<string>();
                foreach (DictionaryEntry e in dict) parts.Add(Str((string)e.Key) + ":" + Write(e.Value));
                return "{" + string.Join(",", parts) + "}";
            }
            if (value is IEnumerable seq)
            {
                var parts = new System.Collections.Generic.List<string>();
                foreach (var e in seq) parts.Add(Write(e));
                return "[" + string.Join(",", parts) + "]";
            }
            var num = Convert.ToDouble(value, CultureInfo.InvariantCulture);
            if (double.IsNaN(num) || double.IsInfinity(num)) throw new FormatException("Non-finite number");
            return Convert.ToString(value, CultureInfo.InvariantCulture);
        }
        public static string Str(string value)
        {
            var b = new StringBuilder("\"");
            foreach (var c in value)
                if (c == '\\' || c == '"') b.Append('\\').Append(c);
                else if (c < 32) b.Append("\\u").Append(((int)c).ToString("x4"));
                else b.Append(c);
            return b.Append('"').ToString();
        }
        public static System.Collections.Generic.Dictionary<string, object> Obj(params object[] pairs)
        {
            var result = new System.Collections.Generic.Dictionary<string, object>();
            for (int i = 0; i < pairs.Length; i += 2) result.Add((string)pairs[i], pairs[i+1]);
            return result;
        }
    }
}
