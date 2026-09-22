using System;

namespace ValheimCodexBridge
{
    // One short approach/aim/interaction intention. Its heartbeat cannot create
    // another intention or repeat a submitted interaction.
    public sealed class InteractionIntent
    {
        public bool Active { get; private set; }
        public string Expected { get; private set; }
        public string Phase { get; private set; } = "idle";
        public string Reason { get; private set; } = "idle";
        public object Result { get; private set; }
        public long LeaseDeadline { get; private set; }
        public long AimingSince { get; private set; }
        long budget, matchingSince;
        int leaseMs, matchingTarget;
        double health;
        public void Start(string expected, bool approach, double hp, long now, int maxLeaseMs)
        {
            expected=expected.Trim();
            if(expected.Length<3 || expected.Length>80 || Array.Exists(expected.ToCharArray(),char.IsControl) ||
                expected.Equals("open",StringComparison.OrdinalIgnoreCase) || expected.Equals("pick up",StringComparison.OrdinalIgnoreCase) ||
                expected.Equals("use",StringComparison.OrdinalIgnoreCase)) throw new ArgumentException("Choose a specific visible target name");
            Expected=expected;health=hp;leaseMs=Math.Min(900,Math.Max(1,maxLeaseMs));
            budget=now+MainThreadDispatcher.Ms(8000);LeaseDeadline=0;matchingTarget=0;matchingSince=0;
            Active=true;Phase=approach ? "approaching" : "aiming";Reason="working";Result=null;
            AimingSince=approach ? 0 : now;Renew(now);
        }
        public void Renew(long now)
        {
            if(!Active)return;
            if(now>=budget || LeaseDeadline!=0 && now>=LeaseDeadline) {Cancel("heartbeat or interaction budget expired");return;}
            LeaseDeadline=Math.Min(budget,now+MainThreadDispatcher.Ms(leaseMs));
        }
        public void Cancel(string reason) {if(Active){Reason=reason;Phase="stopped";}Active=false;LeaseDeadline=0;}
        public bool Step(bool safe,double hp,double maxHp,bool swimming,bool encumbered,long now)
        {
            if(!Active)return false;
            if(!safe)Cancel("gameplay unavailable");
            else if(now>=LeaseDeadline || now>=budget)Cancel("heartbeat or interaction budget expired");
            else if(hp<Math.Min(health,maxHp)-.2)Cancel("damage taken");
            else if(swimming || encumbered)Cancel(swimming ? "entered water" : "encumbered");
            else if(Phase=="aiming" && now-AimingSince>MainThreadDispatcher.Ms(2500))Cancel("named target not found in reach");
            health=hp;return Active;
        }
        public void Arrived(long now) {if(Active && Phase=="approaching"){Phase="aiming";AimingSince=now;}}
        public bool Matches(string caption)
        {
            if(string.IsNullOrEmpty(caption) || string.IsNullOrEmpty(Expected))return false;
            string first=caption.Split('\n')[0];
            int at=first.IndexOf(Expected,StringComparison.OrdinalIgnoreCase);
            if(at<0)return false;
            int end=at+Expected.Length;
            return (at==0 || !char.IsLetterOrDigit(first[at-1])) && (end==first.Length || !char.IsLetterOrDigit(first[end]));
        }
        public bool Confirm(int targetId,string caption,long now)
        {
            if(!Active)return false;
            if(targetId==0 || !Matches(caption)){matchingTarget=0;matchingSince=0;return false;}
            if(matchingTarget!=targetId){matchingTarget=targetId;matchingSince=now;return false;}
            return now-matchingSince>=MainThreadDispatcher.Ms(120);
        }
        public void Submitted(object result) {Result=result;Cancel("interaction submitted once");Phase="submitted";}
        public object Snapshot()=>Json.Obj("active",Active,"phase",Phase,"reason",Reason,"expected_name",Expected,"result",Result);
    }
}
