using System;
using System.Collections.Generic;
namespace ValheimCodexBridge
{
    public interface IGameAdapter
    {
        // All members are called only from the Unity main thread.
        bool Ready { get; }
        bool GameplayReady { get; }
        bool HasHeldInput { get; }
        string Reason { get; }
        string WorldId { get; }
        string CharacterName { get; }
        int ChatLimit { get; }
        object Status();
        ImageResult Observe();
        void Apply(ControlState state);
        void Look(float yaw, float pitch);
        object Pulse(string action, int slot);
        void Aim(float x, float y, bool ground, int frameId);
        object TravelAction(string action, Dictionary<string,object> arguments);
        void RenewTravel();
        void CancelTravel(string reason);
        bool PrecisionReady(int frameId);
        bool MotorReady(int frameId);
        void SendChat(string text, string channel);
        object InventoryAction(string action, Dictionary<string, object> arguments);
        object MapAction(string action, Dictionary<string, object> arguments);
    }
    public sealed class ControlState
    {
        public float Forward, Strafe, YawRate, PitchRate;
        public bool Motor;
        public bool Sprint, Block;
        // Monotonic deadline is also enforced inside the game's physics input hook.
        public long Deadline;
        public bool Held => Forward != 0 || Strafe != 0 || YawRate != 0 || PitchRate != 0 || Sprint || Block;
        public void Clear() { Forward = Strafe = YawRate = PitchRate = 0; Motor = Sprint = Block = false; Deadline = 0; }
    }
    public sealed class BridgeSettings
    {
        public int Port = 8731;
        public int MaxActionMs = 1500;
        public bool CombatEnabled;
        public bool ChatEnabled = true;
        public int ChatLimit = 160;
        public double ChatCooldownSeconds = 4;
        public string ExpectedCharacter = "Codex";
        public string ExpectedWorld = "configure-your-world";
        public HashSet<string> Owners = new HashSet<string>(StringComparer.Ordinal);
    }
    public sealed class ChatEvent
    {
        public long EventId;
        public string Timestamp, Sender, SenderId, Channel, Text;
        public bool IdentityVerified;
        // No position is collected by default. Never enumerate remote players.
        public object ToJson() => Json.Obj("event_id", EventId, "timestamp", Timestamp,
            "sender", Sender, "sender_id", SenderId, "identity_verified", IdentityVerified,
            "channel", Channel, "text", Text);
    }
}
