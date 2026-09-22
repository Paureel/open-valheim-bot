using System;

namespace ValheimCodexBridge
{
    // Only our own motion/vitals. No pathfinding, world lookup or enemy queries.
    public sealed class TravelIntent
    {
        public bool Active { get; private set; }
        public string Reason { get; private set; } = "idle";
        public long LeaseDeadline { get; private set; }
        public double TargetX, TargetZ, Distance, Travelled;
        public bool Sprint;
        long budget, checkedAt;
        int leaseMs;
        double lastX, lastZ, lastY, checkX, checkZ, health;
        static double Range(double x,double z,double a,double b) => Math.Sqrt((x-a)*(x-a)+(z-b)*(z-b));
        public void Start(double x,double z,double y,double tx,double tz,double hp,bool sprint,int budgetMs,long now,int maxLeaseMs=900)
        {
            if (budgetMs<1000 || budgetMs>10000 || Range(x,z,tx,tz)>20) throw new ArgumentException("Travel exceeds visible-point bounds");
            leaseMs=Math.Min(900,Math.Max(1,maxLeaseMs));
            TargetX=tx;TargetZ=tz;lastX=checkX=x;lastZ=checkZ=z;lastY=y;health=hp;
            Sprint=sprint;Travelled=0;Distance=Range(x,z,tx,tz);checkedAt=now;
            budget=now+MainThreadDispatcher.Ms(budgetMs);Active=true;Reason="travelling";LeaseDeadline=0;
            Renew(now);
        }
        public void Cancel(string reason) { if(Active) Reason=reason;Active=false;LeaseDeadline=0; }
        public void Renew(long now)
        {
            // A late heartbeat cannot resurrect an expired route.
            if (!Active) return;
            if (now>=budget || (LeaseDeadline!=0 && now>=LeaseDeadline)) {Cancel("heartbeat or travel budget expired");return;}
            LeaseDeadline=Math.Min(budget,now+MainThreadDispatcher.Ms(leaseMs));
        }
        public bool Step(double x,double z,double y,double hp,double maxHp,bool safe,bool swimming,bool encumbered,long now)
        {
            if(!Active)return false;
            if(!safe)Cancel("gameplay unavailable");
            else if(now>=LeaseDeadline || now>=budget)Cancel("heartbeat or travel budget expired");
            else if(hp < Math.Min(health,maxHp)-.2)Cancel("damage taken");
            else if(swimming || encumbered)Cancel(swimming ? "entered water" : "encumbered");
            else if(y<lastY-1.5)Cancel("fall detected");
            if(!Active)return false;
            Travelled+=Range(x,z,lastX,lastZ);lastX=x;lastZ=z;health=hp;
            // Track a one-second window, not each heartbeat's tiny displacement.
            Distance=Range(x,z,TargetX,TargetZ);
            if(Distance<=1.2)Cancel("arrived");
            else if(now-checkedAt>=MainThreadDispatcher.Ms(1200))
            {
                if(Range(x,z,checkX,checkZ)<.3)Cancel("blocked");
                checkedAt=now;checkX=x;checkZ=z;lastY=y;
            }
            return Active;
        }
        public object Snapshot()=>Json.Obj("active",Active,"reason",Reason,"distance_m",Distance,"travelled_m",Travelled,
            "approximate_target",true,"sprint_requested",Sprint);
    }
}
