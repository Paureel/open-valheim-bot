namespace ValheimCodexBridge
{
    // Only own-HUD health/stamina. No enemy detection or auto-attacking.
    public sealed class DamageReflex
    {
        float previous = -1;
        public long Deadline { get; private set; }
        public int Triggers { get; private set; }
        public bool Step(float health, float stamina, bool allowed, long now, float maxHealth = float.PositiveInfinity)
        {
            if (!allowed || health <= 0) Deadline = 0;
            else if (previous >= 0 && health < System.Math.Min(previous, maxHealth) - 0.1f && stamina >= 10)
            { Deadline = now + MainThreadDispatcher.Ms(1000); Triggers++; }
            previous = health;
            if (stamina < 5 || now >= Deadline) Deadline = 0;
            return Deadline > now;
        }
    }
}
